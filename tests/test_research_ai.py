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


def title_only_result(**overrides):
    result = valid_result(
        core_conclusion="标题显示公司签署合同，正文未提供，影响无法核验。",
        key_tension="仅有标题信息，正文未提供。",
        facts=[{"claim": "公司签署合同", "evidence_ids": ["e1"]}],
        sections=[],
        impact_paths=[],
        inferences=[],
        unknowns=["正文未提供，原因无法核验。"],
        watch_signals=["等待后续公告。"],
        thesis_relationship="证据不足，无法核验已确认判断。",
        follow_up_question="是否要继续核验公司签署合同？",
    )
    result.update(overrides)
    return result


def parsed_sse(stream):
    events = []
    for chunk in stream:
        lines = chunk.strip().splitlines()
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


class ResearchAIValidationTest(unittest.TestCase):
    def test_all_visible_strings_reject_unsupported_numbers(self):
        overrides = [
            {field: "合同金额999亿元"} for field in (
                "core_conclusion", "key_tension", "thesis_relationship",
                "follow_up_question", "safety_boundary",
            )
        ] + [
            {field: ["合同金额999亿元"]} for field in ("unknowns", "watch_signals")
        ] + [
            {"impact_paths": [{"path": "合同金额999亿元可能增加收入", "evidence_ids": ["e1"], "uncertainty": "未确认"}]},
            {"inferences": [{"claim": "合同可能增加收入", "evidence_ids": ["e1"], "uncertainty": "金额999亿元未确认"}]},
        ]
        for override in overrides:
            with self.subTest(override=override), self.assertRaisesRegex(AIError, "数字"):
                validate_research_result(valid_result(**override), {"e1": sample_evidence()}, "none")

    def test_inference_numbers_must_come_from_cited_not_unrelated_evidence(self):
        lookup = {"e1": sample_evidence(), "e2": sample_evidence(excerpt="合同金额10亿元")}
        for field, text_field in (("impact_paths", "path"), ("inferences", "claim")):
            for references in ([], ["e1"]):
                with self.subTest(field=field, refs=references), self.assertRaises(AIError):
                    validate_research_result(valid_result(**{field: [{text_field: "合同金额10亿元可能增加收入", "evidence_ids": references, "uncertainty": "仍需观察"}]}), lookup, "none")
            result = valid_result(**{field: [{text_field: "合同金额10亿元可能增加收入", "evidence_ids": ["e2"], "uncertainty": "仍需观察"}]})
            validate_research_result(result, lookup, "none")

    def test_title_only_cannot_turn_negated_title_into_positive_fact(self):
        for title in ("公司未签署合同", "公司尚未签署合同", "公司否认签署合同"):
            lookup = {"e1": sample_evidence(title=title, excerpt="", content_status="title_only")}
            with self.subTest(title=title), self.assertRaisesRegex(AIError, "否定"):
                validate_research_result(title_only_result(), lookup, "none")
            safe = title_only_result(
                core_conclusion=f"标题显示{title}，正文未提供。",
                facts=[{"claim": title, "evidence_ids": ["e1"]}],
                follow_up_question="是否继续核验？",
            )
            validate_research_result(safe, lookup, "none")

    def test_postposed_advice_and_value_endorsements_are_rejected(self):
        for advice in ("买入更合适", "卖出更稳妥", "当前价位具备投资价值", "现价值得买入", "现在是建仓良机", "持有更划算", "投资价值突出"):
            with self.subTest(advice=advice), self.assertRaisesRegex(AIError, "交易指令"):
                validate_research_result(valid_result(core_conclusion=advice), {"e1": sample_evidence()}, "none")

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

    def test_title_only_safe_restatement_and_uncertainty_are_accepted(self):
        lookup = {
            "e1": sample_evidence(
                title="公司签署合同", excerpt="", content_status="title_only"
            )
        }

        cleaned, _ = validate_research_result(title_only_result(), lookup, "none")

        self.assertEqual(cleaned["facts"][0]["claim"], "公司签署合同")

    def test_title_only_rejects_invented_detail_in_every_evidence_derived_area(self):
        lookup = {
            "e1": sample_evidence(
                title="公司签署合同", excerpt="", content_status="title_only"
            )
        }
        cases = {
            "core_conclusion": {"core_conclusion": "需求增长推动公司签署合同。"},
            "key_tension": {"key_tension": "客户需求强劲，但产能待核验。"},
            "sections": {
                "sections": [{
                    "heading": "原因", "body": "需求增长推动合同签署。", "evidence_ids": ["e1"]
                }]
            },
            "facts": {
                "facts": [{"claim": "公司因需求增长签署合同", "evidence_ids": ["e1"]}]
            },
            "impact_paths": {
                "impact_paths": [{
                    "path": "合同将提升利润", "evidence_ids": ["e1"], "uncertainty": "尚待核验"
                }]
            },
            "inferences": {
                "inferences": [{
                    "claim": "需求增长带动合同", "evidence_ids": ["e1"], "uncertainty": "尚待核验"
                }]
            },
            "unknowns": {"unknowns": ["客户需求是否持续增长尚不清楚。"]},
            "watch_signals": {"watch_signals": ["客户需求增长。"]},
            "thesis_relationship": {"thesis_relationship": "需求增长已验证原判断。"},
            "follow_up_question": {
                "follow_up_question": "是否要核验需求增长原因？"
            },
        }

        for label, override in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(AIError, "仅标题"):
                validate_research_result(title_only_result(**override), lookup, "none")

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

    def test_conflict_appends_normalized_unknown_even_after_false_no_conflict_text(self):
        result = valid_result(confidence="high", unknowns=["未发现冲突。"])

        cleaned, _ = validate_research_result(
            result, {"e1": sample_evidence()}, "possible"
        )

        expected = "来源信息存在冲突，相关事实尚待进一步核验。"
        self.assertEqual(cleaned["unknowns"].count(expected), 1)
        self.assertNotIn("未发现冲突。", cleaned["unknowns"])

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

    def test_common_hold_position_and_allocation_instructions_are_rejected(self):
        instructions = (
            "建议持有",
            "应持有",
            "应当持有",
            "必须持有",
            "可以持有",
            "半仓持有",
            "可继续持有",
            "耐心持有",
            "坚定持有",
            "控制仓位",
            "调整仓位",
            "维持仓位",
            "仓位控制在半仓",
            "仓位降至半仓",
            "仓位设为五成",
            "保持半仓",
            "逢低配置",
            "逢低布局",
            "分批建仓",
            "分批配置",
            "建议观望",
            "保持观望",
            "建议暂避",
            "建议回避",
            "暂时规避",
            "规避该股",
            "空仓观望",
        )

        for instruction in instructions:
            with self.subTest(instruction=instruction), self.assertRaises(AIError):
                validate_research_result(
                    valid_result(core_conclusion=instruction),
                    {"e1": sample_evidence()},
                    "none",
                )

    def test_direct_prefix_position_limit_and_nonparticipation_are_rejected(self):
        instructions = (
            "请持有",
            "不要持有",
            "持有为宜",
            "仓位不超过三成",
            "暂不参与",
        )

        for instruction in instructions:
            with self.subTest(instruction=instruction), self.assertRaises(AIError):
                validate_research_result(
                    valid_result(core_conclusion=instruction),
                    {"e1": sample_evidence()},
                    "none",
                )

    def test_broad_direct_actions_are_rejected_in_user_facing_fields(self):
        cases = (
            valid_result(core_conclusion="不妨持有"),
            valid_result(inferences=[{
                "claim": "宜持有",
                "evidence_ids": ["e1"],
                "uncertainty": "仍需观察",
            }]),
            valid_result(core_conclusion="持仓不得超过三成"),
            valid_result(inferences=[{
                "claim": "暂不介入",
                "evidence_ids": ["e1"],
                "uncertainty": "仍需观察",
            }]),
        )

        for result in cases:
            with self.subTest(result=result), self.assertRaises(AIError):
                validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_ordinary_explanatory_holding_language_is_not_rejected(self):
        result = valid_result(
            core_conclusion="公司持有子公司股权，目前仅能确认这一披露事实。"
        )

        cleaned, _ = validate_research_result(
            result, {"e1": sample_evidence()}, "none"
        )

        self.assertEqual(cleaned["core_conclusion"], result["core_conclusion"])

    def test_factual_subject_holding_language_is_allowed_in_facts(self):
        factual_statements = (
            "公司可以持有子公司股权。",
            "基金必须持有百分之五的现金。",
            "监管建议银行持有充足资本。",
            "法规要求基金持仓不低于八成。",
            "公司将仓位降至半仓。",
        )

        for statement in factual_statements:
            with self.subTest(statement=statement):
                result = valid_result(
                    facts=[{"claim": statement, "evidence_ids": ["e1"]}]
                )
                cleaned, _ = validate_research_result(
                    result, {"e1": sample_evidence()}, "none"
                )
                self.assertEqual(cleaned["facts"][0]["claim"], statement)

    def test_trading_like_fact_still_requires_valid_evidence(self):
        invalid_evidence_sets = ([], ["missing"])

        for evidence_ids in invalid_evidence_sets:
            with self.subTest(evidence_ids=evidence_ids), self.assertRaises(AIError):
                validate_research_result(
                    valid_result(facts=[{
                        "claim": "法规要求基金持仓不低于八成。",
                        "evidence_ids": evidence_ids,
                    }]),
                    {"e1": sample_evidence()},
                    "none",
                )

    def test_cited_direct_advice_is_rejected_in_every_visible_container(self):
        cases = {
            "fact": valid_result(facts=[{
                "claim": "建议买入并持有",
                "evidence_ids": ["e1"],
            }]),
            "fact_with_non_user_subject": valid_result(facts=[{
                "claim": "公司将仓位降至半仓后不妨持有",
                "evidence_ids": ["e1"],
            }]),
            "section": valid_result(sections=[{
                "heading": "操作建议",
                "body": "建议买入并持有",
                "evidence_ids": ["e1"],
            }]),
            "unknown": valid_result(unknowns=["信息有限，但建议买入并持有"]),
            "inference_uncertainty": valid_result(inferences=[{
                "claim": "影响尚待确认",
                "evidence_ids": ["e1"],
                "uncertainty": "不确定时建议买入并持有",
            }]),
        }

        for label, result in cases.items():
            with self.subTest(label=label), self.assertRaises(AIError):
                validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_safety_boundary_is_also_checked_for_direct_advice(self):
        with self.assertRaises(AIError):
            validate_research_result(
                valid_result(safety_boundary="建议买入并持有"),
                {"e1": sample_evidence()},
                "none",
            )

    def test_evidence_backed_factual_section_is_not_scanned_as_advice(self):
        section = {
            "heading": "已披露行为",
            "body": "公司将仓位降至半仓后披露了该事项。",
            "evidence_ids": ["e1"],
        }

        cleaned, _ = validate_research_result(
            valid_result(sections=[section]), {"e1": sample_evidence()}, "none"
        )

        self.assertEqual(cleaned["sections"], [section])

    def test_non_factual_section_direct_action_is_rejected(self):
        result = valid_result(sections=[{
            "heading": "下一步",
            "body": "不妨持有",
            "evidence_ids": [],
        }])

        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_position_and_waiting_terms_without_directive_context_are_not_rejected(self):
        result = valid_result(
            core_conclusion="机构持仓数据为五成，市场仍处于观望状态。"
        )

        cleaned, _ = validate_research_result(
            result, {"e1": sample_evidence()}, "none"
        )

        self.assertEqual(cleaned["core_conclusion"], result["core_conclusion"])

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
    def test_legacy_route_keywords_are_adapted_to_selected_context(self):
        captured_contexts = []

        def fake_model(config, instructions, context):
            captured_contexts.append(deepcopy(context))
            return valid_result()

        with patch("app.services.ai._call_model", side_effect=fake_model), patch(
            "app.services.ai.get_evidence", return_value=sample_evidence()
        ):
            events = parsed_sse(
                run_grounded_stream(
                    config=CONFIG,
                    mode="research",
                    asset={
                        "stock_code": "600000",
                        "stock_name": "浦发银行",
                        "quantity": 100,
                        "cost_price": 9.5,
                    },
                    question="这件事有什么影响？",
                    event={
                        "event_id": "e1",
                        "title": "公司签署合同",
                        "published_at": "2026-09-28T01:00:00+00:00",
                        "source_type": "announcement",
                    },
                    evidence_items=[sample_evidence()],
                    thesis=None,
                    recent_messages=[],
                    snapshot=None,
                )
            )

        completed = [payload for name, payload in events if name == "completed"]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["event_id"], "e1")
        self.assertEqual(
            captured_contexts[0]["asset"],
            {"stock_code": "600000", "stock_name": "浦发银行"},
        )

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
