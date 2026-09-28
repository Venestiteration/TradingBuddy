import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from app.services.ai import (
    AIError,
    RESEARCH_SCHEMA,
    run_grounded_stream,
    validate_research_result,
)
from app.services.visitor_ai import VisitorAIConfig


CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="test-model",
    base_url="https://api.openai.com/v1",
    resolved_ips=("8.8.8.8",),
)


def sample_evidence(**overrides):
    evidence = {
        "evidence_id": "e1",
        "title": "公司签署合同",
        "excerpt": "公司披露已签署合同",
        "content_status": "excerpt",
        "source_type": "announcement",
        "source_level": "primary",
        "published_at": "2026-09-28T01:00:00+00:00",
    }
    evidence.update(overrides)
    return evidence


def valid_result(**overrides):
    result = {
        "answer_mode": "event",
        "core_conclusion": "事件值得跟踪，但证据尚不足以确认财务影响。",
        "key_tension": "合同已披露，但履约与收入确认尚待核验。",
        "impact_state": "watch",
        "sections": [],
        "facts": [{"claim": "公司签署合同", "evidence_ids": ["e1"]}],
        "impact_paths": [],
        "inferences": [],
        "unknowns": ["尚不清楚收入确认时点"],
        "watch_signals": ["后续履约公告"],
        "thesis_relationship": "尚未触及已确认判断的失效条件。",
        "follow_up_question": "是否要继续核验合同履约节点？",
        "confidence": "medium",
        "safety_boundary": "以上为研究信息整理，不构成投资建议。",
    }
    result.update(overrides)
    return result


def selected_context(**overrides):
    context = {
        "asset": {"stock_code": "600000", "stock_name": "浦发银行"},
        "question": "这件事有什么影响？",
        "product_boundary": "仅做研究信息整理。",
        "evidence": [sample_evidence()],
    }
    context.update(overrides)
    return context


def parsed_sse(stream):
    events = []
    for chunk in stream:
        lines = chunk.strip().splitlines()
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


class ResearchAIValidationTest(unittest.TestCase):
    def test_research_schema_is_strict_and_does_not_request_compatibility_aliases(self):
        expected = {
            "answer_mode", "core_conclusion", "key_tension", "impact_state",
            "sections", "facts", "impact_paths", "inferences", "unknowns",
            "watch_signals", "thesis_relationship", "follow_up_question",
            "confidence", "safety_boundary",
        }

        self.assertEqual(set(RESEARCH_SCHEMA["required"]), expected)
        self.assertEqual(set(RESEARCH_SCHEMA["properties"]), expected)
        self.assertFalse(RESEARCH_SCHEMA["additionalProperties"])
        self.assertNotIn("conclusion", RESEARCH_SCHEMA["properties"])
        self.assertNotIn("next_checks", RESEARCH_SCHEMA["properties"])

    def test_title_only_claim_cannot_add_number(self):
        lookup = {
            "e1": sample_evidence(
                title="公司签署合同", excerpt="", content_status="title_only"
            )
        }
        result = valid_result(
            facts=[{"claim": "合同金额10亿元", "evidence_ids": ["e1"]}]
        )

        with self.assertRaises(AIError):
            validate_research_result(result, lookup, "none")

    def test_title_only_number_cannot_be_justified_by_coincidental_snapshot_value(self):
        lookup = {
            "e1": sample_evidence(
                title="公司签署合同", excerpt="", content_status="title_only"
            ),
            "__market_snapshot__": {"price": 10},
        }
        result = valid_result(
            facts=[{"claim": "合同金额10亿元", "evidence_ids": ["e1"]}]
        )

        with self.assertRaisesRegex(AIError, "仅标题"):
            validate_research_result(result, lookup, "none")

    def test_full_cited_evidence_can_support_number_alongside_title_only_source(self):
        lookup = {
            "e1": sample_evidence(
                title="公司签署合同", excerpt="", content_status="title_only"
            ),
            "e2": sample_evidence(
                evidence_id="e2",
                title="公司签署合同",
                excerpt="合同金额为10亿元",
                content_status="full",
            ),
        }
        result = valid_result(
            facts=[{"claim": "合同金额10亿元", "evidence_ids": ["e1", "e2"]}]
        )

        cleaned, _ = validate_research_result(result, lookup, "none")

        self.assertEqual(cleaned["facts"], result["facts"])

    def test_fact_number_must_appear_in_its_cited_evidence(self):
        lookup = {
            "e1": sample_evidence(excerpt="公司披露已签署合同"),
            "e2": sample_evidence(
                evidence_id="e2", title="合同金额10亿元", excerpt=""
            ),
        }
        result = valid_result(
            facts=[{"claim": "合同金额10亿元", "evidence_ids": ["e1"]}]
        )

        with self.assertRaisesRegex(AIError, "数字"):
            validate_research_result(result, lookup, "none")

    def test_iso_date_evidence_supports_localized_date_claim(self):
        lookup = {
            "e1": sample_evidence(
                title="公司于2026-09-28签署合同",
                excerpt="公司已签署合同",
            )
        }
        result = valid_result(
            facts=[
                {"claim": "公司于2026年9月28日签署合同", "evidence_ids": ["e1"]}
            ]
        )

        cleaned, _ = validate_research_result(result, lookup, "none")

        self.assertEqual(cleaned["facts"], result["facts"])

    def test_section_number_can_come_from_whitelisted_market_snapshot(self):
        lookup = {
            "e1": sample_evidence(),
            "__market_snapshot__": {"price": 10.25, "private_note": 999},
        }
        result = valid_result(
            sections=[
                {"heading": "行情参照", "body": "当前价格为10.25元。", "evidence_ids": []}
            ]
        )

        cleaned, _ = validate_research_result(result, lookup, "none")

        self.assertEqual(cleaned["sections"][0]["body"], "当前价格为10.25元。")

    def test_section_number_cannot_come_from_non_whitelisted_snapshot_field(self):
        lookup = {
            "e1": sample_evidence(),
            "__market_snapshot__": {"price": 10.25, "private_note": 999},
        }
        result = valid_result(
            sections=[
                {"heading": "内部备注", "body": "内部编号为999。", "evidence_ids": []}
            ]
        )

        with self.assertRaisesRegex(AIError, "数字"):
            validate_research_result(result, lookup, "none")

    def test_conflict_caps_confidence_and_requires_unknown(self):
        result = valid_result(confidence="high", unknowns=[])

        cleaned, notes = validate_research_result(
            result, {"e1": sample_evidence()}, "possible"
        )

        self.assertEqual(cleaned["confidence"], "low")
        self.assertEqual(cleaned["impact_state"], "insufficient")
        self.assertTrue(any("冲突" in item for item in cleaned["unknowns"]))
        self.assertTrue(any("冲突" in item for item in notes))

    def test_invalid_reference_is_rejected(self):
        result = valid_result(
            facts=[{"claim": "事实", "evidence_ids": ["missing"]}]
        )

        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_reference_to_malformed_evidence_is_rejected(self):
        result = valid_result()

        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": None}, "none")

    def test_invalid_section_reference_is_rejected(self):
        result = valid_result(
            sections=[{"heading": "结论", "body": "已披露", "evidence_ids": ["missing"]}]
        )

        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_trading_instruction_is_rejected(self):
        result = valid_result(core_conclusion="建议买入并设置止损")

        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_runtime_validation_rejects_extra_model_fields(self):
        result = valid_result(conclusion="旧字段不应由模型返回")

        with self.assertRaisesRegex(AIError, "额外字段"):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_runtime_validation_reports_wrong_enum_type_as_schema_error(self):
        result = valid_result(answer_mode={"unexpected": True})

        with self.assertRaises(AIError) as raised:
            validate_research_result(result, {"e1": sample_evidence()}, "none")

        self.assertEqual(raised.exception.category, "schema")


class ResearchAIStreamTest(unittest.TestCase):
    def test_schema_parse_failure_from_provider_gets_one_repair_attempt(self):
        calls = []

        def fake_model(config, instructions, context):
            calls.append(deepcopy(context))
            if len(calls) == 1:
                raise AIError("schema", "模型输出不是合法 JSON")
            return valid_result()

        with patch("app.services.ai._call_model", side_effect=fake_model), patch(
            "app.services.ai.get_evidence", return_value=sample_evidence()
        ):
            events = parsed_sse(
                run_grounded_stream(
                    config=CONFIG,
                    mode="event",
                    context=selected_context(),
                    conflict_status="none",
                )
            )

        self.assertEqual(len(calls), 2)
        self.assertIn("validation_feedback", calls[1])
        self.assertIn("completed", [name for name, _ in events])

    def test_first_validation_failure_is_repaired_once_and_aliases_are_output_only(self):
        invalid = valid_result(
            facts=[{"claim": "事实", "evidence_ids": ["missing"]}]
        )
        repaired = valid_result()
        calls = []

        def fake_model(config, instructions, context):
            calls.append((instructions, deepcopy(context)))
            return invalid if len(calls) == 1 else repaired

        with patch("app.services.ai._call_model", side_effect=fake_model), patch(
            "app.services.ai.get_evidence", return_value=sample_evidence()
        ):
            events = parsed_sse(
                run_grounded_stream(
                    config=CONFIG,
                    mode="event",
                    context=selected_context(),
                    conflict_status="none",
                )
            )

        completed = [payload for name, payload in events if name == "completed"]
        self.assertEqual(len(calls), 2)
        self.assertIn("validation_feedback", calls[1][1])
        self.assertEqual(len(completed), 1)
        result = completed[0]["result"]
        self.assertEqual(result["conclusion"], repaired["core_conclusion"])
        self.assertEqual(result["next_checks"], repaired["watch_signals"])
        self.assertNotIn("conclusion", repaired)
        self.assertNotIn("next_checks", repaired)

    def test_second_validation_failure_emits_failed_without_result(self):
        invalid = valid_result(
            facts=[{"claim": "事实", "evidence_ids": ["missing"]}]
        )

        with patch("app.services.ai._call_model", return_value=invalid) as call:
            events = parsed_sse(
                run_grounded_stream(
                    config=CONFIG,
                    mode="event",
                    context=selected_context(),
                    conflict_status="none",
                )
            )

        self.assertEqual(call.call_count, 2)
        self.assertNotIn("completed", [name for name, _ in events])
        self.assertEqual(events[-1][0], "failed")
        self.assertEqual(events[-1][1]["category"], "schema")


if __name__ == "__main__":
    unittest.main()
