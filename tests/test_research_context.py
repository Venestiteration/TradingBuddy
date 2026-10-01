from datetime import datetime, timedelta, timezone
import unittest

from app.services.research_context import (
    classify_question_focus,
    select_research_context,
)
from app.services.research_prompt import compose_research_prompt


NOW = datetime(2026, 9, 28, 8, tzinfo=timezone.utc)


def sample_evidence(index, *, published_at=None, title=None):
    return {
        "evidence_id": f"e{index}",
        "source_type": "news",
        "source_level": "secondary",
        "title": title or f"合同进展 {index}",
        "excerpt": f"公司披露合同进展 {index}",
        "published_at": published_at
        or f"2026-09-{28 - min(index, 20):02d}T01:00:00+00:00",
        "content_status": "excerpt",
    }


def selected_event(evidence):
    return {
        "cluster_id": "1:10",
        "title": "公司合同进展",
        "published_at": "2026-09-28T01:00:00+00:00",
        "conflict_status": "none",
        "evidence": evidence,
    }


class ResearchContextTest(unittest.TestCase):
    def test_prompt_layers_product_constitution_first(self):
        prompt = compose_research_prompt("event")
        self.assertLess(prompt.index("产品宪法"), prompt.index("研究思维"))
        self.assertLess(prompt.index("研究思维"), prompt.index("任务模板"))
        self.assertIn("不推断用户持仓", prompt)
        self.assertIn("结论前置", prompt)

    def test_prompt_rejects_unsupported_mode(self):
        with self.assertRaisesRegex(ValueError, "unsupported research mode"):
            compose_research_prompt("trade")

    def test_context_is_bounded_and_selected_cluster_first(self):
        evidence = [sample_evidence(index) for index in range(20)]
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同对盈利有什么影响？",
            snapshot={"price": 10.2},
            selected_event=selected_event(evidence[:3]),
            daily_brief={"events": []},
            evidence_items=evidence,
            thesis=None,
            recent_messages=[{"role": "user", "content": str(i)} for i in range(9)],
        )
        self.assertLessEqual(len(context["evidence"]), 15)
        self.assertLessEqual(len(context["recent_messages"]), 6)
        self.assertEqual(context["evidence"][0]["evidence_id"], evidence[0]["evidence_id"])
        self.assertNotIn("assumed_risk_tolerance", context)

    def test_selected_cluster_evidence_is_not_truncated_by_background_cap(self):
        selected = [sample_evidence(index) for index in range(15)]
        background = [
            sample_evidence(
                index + 100,
                published_at="2026-09-27T01:00:00+00:00",
                title=f"合同背景 {index}",
            )
            for index in range(20)
        ]

        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同进展如何？",
            snapshot=None,
            selected_event=selected_event(selected),
            daily_brief={"events": []},
            evidence_items=background,
            thesis=None,
            recent_messages=[],
        )

        self.assertEqual(
            [item["evidence_id"] for item in context["evidence"][:15]],
            [item["evidence_id"] for item in selected],
        )
        self.assertEqual(len(context["evidence"]), 27)

    def test_daily_headline_cluster_precedes_question_overlap(self):
        selected = sample_evidence(1, title="公司人事变动")
        headline = sample_evidence(2, title="主要合同进展")
        overlap = sample_evidence(3, title="合同对盈利的影响")
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同对盈利有什么影响？",
            snapshot=None,
            selected_event=selected_event([selected]),
            daily_brief={
                "headline": {"cluster_id": "1:20", "title": "主要合同进展"},
                "events": [
                    {"cluster_id": "1:20", "evidence": [headline]},
                ],
            },
            evidence_items=[overlap, headline, selected],
            thesis=None,
            recent_messages=[],
        )
        self.assertEqual(
            [item["evidence_id"] for item in context["evidence"]],
            ["e1", "e2", "e3"],
        )

    def test_daily_brief_nested_evidence_and_raw_are_removed_from_context(self):
        headline_evidence = [sample_evidence(index) for index in range(15)]
        daily_brief = {
            "headline": {
                "cluster_id": "1:20",
                "title": "主要合同进展",
                "evidence": headline_evidence,
                "raw": {"provider_payload": "must-not-leak"},
            },
            "known_facts": [
                {
                    "claim": "公司披露合同进展",
                    "evidence_ids": ["e0"],
                    "detail": {
                        "evidence": [headline_evidence[0]],
                        "raw": {"model_input": "must-not-leak"},
                    },
                }
            ],
            "events": [],
        }
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同进展如何？",
            snapshot=None,
            selected_event=None,
            daily_brief=daily_brief,
            evidence_items=[],
            thesis=None,
            recent_messages=[],
        )

        def nested_keys(value):
            if isinstance(value, dict):
                return set(value) | {
                    key
                    for child in value.values()
                    for key in nested_keys(child)
                }
            if isinstance(value, list):
                return {
                    key for child in value for key in nested_keys(child)
                }
            return set()

        self.assertEqual(len(context["evidence"]), 12)
        self.assertFalse({"evidence", "raw"} & nested_keys(context["daily_brief"]))

    def test_question_overlap_excludes_items_older_than_90_days(self):
        recent = sample_evidence(
            1,
            title="合同与盈利",
            published_at=(NOW - timedelta(days=89)).isoformat(),
        )
        old = sample_evidence(
            2,
            title="合同与盈利",
            published_at=(NOW - timedelta(days=91)).isoformat(),
        )
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同对盈利有什么影响？",
            snapshot=None,
            selected_event={
                "cluster_id": "1:10",
                "title": "人事变动",
                "published_at": NOW.isoformat(),
                "evidence": [],
            },
            daily_brief={"events": []},
            evidence_items=[old, recent],
            thesis=None,
            recent_messages=[],
        )
        self.assertEqual(
            [item["evidence_id"] for item in context["evidence"]], ["e1"]
        )

    def test_old_ai_answer_is_conversation_not_evidence(self):
        evidence = [sample_evidence(1)]
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同有什么影响？",
            snapshot=None,
            selected_event=selected_event(evidence),
            daily_brief={"events": []},
            evidence_items=evidence,
            thesis=None,
            recent_messages=[
                {"role": "assistant", "content": "assistant-answer 是上一轮模型文本"}
            ],
        )
        ids = {item["evidence_id"] for item in context["evidence"]}
        self.assertNotIn("assistant-answer", ids)

    def test_ai_generated_rows_are_not_accepted_as_evidence(self):
        ai_row = {
            **sample_evidence(99),
            "source_type": "ai_output",
            "title": "模型生成的合同结论",
        }
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同有什么影响？",
            snapshot=None,
            selected_event=selected_event([ai_row]),
            daily_brief={"events": []},
            evidence_items=[ai_row],
            thesis=None,
            recent_messages=[],
        )
        self.assertEqual(context["evidence"], [])

    def test_missing_and_unknown_source_types_are_not_accepted_as_evidence(self):
        missing = {**sample_evidence(97)}
        missing.pop("source_type")
        unknown = {**sample_evidence(98), "source_type": "generated_summary"}
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同有什么影响？",
            snapshot=None,
            selected_event=selected_event([missing, unknown]),
            daily_brief={"events": []},
            evidence_items=[missing, unknown],
            thesis=None,
            recent_messages=[],
        )
        self.assertEqual(context["evidence"], [])

    def test_original_evidence_source_types_are_accepted(self):
        evidence = []
        for index, source_type in enumerate(("market", "announcement", "news")):
            evidence.append({**sample_evidence(index), "source_type": source_type})
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同有什么影响？",
            snapshot=None,
            selected_event=selected_event(evidence),
            daily_brief={"events": []},
            evidence_items=evidence,
            thesis=None,
            recent_messages=[],
        )
        self.assertEqual(
            [item["source_type"] for item in context["evidence"]],
            ["market", "announcement", "news"],
        )

    def test_recent_messages_are_relevant_labeled_trimmed_and_last_six(self):
        messages = [
            {"role": "user", "content": f"合同进展 {index}" + "x" * 2100}
            for index in range(8)
        ]
        messages.insert(4, {"role": "assistant", "content": "不相关的分红信息"})
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同进展如何？",
            snapshot=None,
            selected_event=selected_event([]),
            daily_brief={"events": []},
            evidence_items=[],
            thesis=None,
            recent_messages=messages,
        )
        self.assertEqual(len(context["recent_messages"]), 6)
        self.assertTrue(
            all(
                item["context_type"] == "conversation"
                for item in context["recent_messages"]
            )
        )
        self.assertTrue(
            all(len(item["content"]) <= 2000 for item in context["recent_messages"])
        )
        self.assertTrue(context["recent_messages"][0]["content"].startswith("合同进展 2"))

    def test_context_only_exposes_explicit_asset_and_confirmed_thesis_fields(self):
        context = select_research_context(
            asset={
                "id": 7,
                "stock_code": "600000",
                "stock_name": "浦发银行",
                "asset_type": "holding",
                "quantity": 200,
                "cost_price": 9.8,
            },
            question="公司怎么样？",
            snapshot={"price": 10.2, "quantity": 999},
            selected_event=None,
            daily_brief={"events": []},
            evidence_items=[],
            thesis={
                "version": 3,
                "core_thesis": "收入稳定",
                "watch_variables": "毛利率",
                "invalid_conditions": "收入下降",
                "status": "已由你确认",
                "ai_suggestion": "这不是确认内容",
            },
            recent_messages=[],
        )
        self.assertEqual(
            context["asset"],
            {"stock_code": "600000", "stock_name": "浦发银行"},
        )
        self.assertEqual(
            set(context["confirmed_thesis"]),
            {"version", "core_thesis", "watch_variables", "invalid_conditions"},
        )
        self.assertNotIn("quantity", context["market_snapshot"])
        self.assertIn("不构成交易指令", context["product_boundary"])

    def test_unconfirmed_thesis_is_not_included(self):
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="公司怎么样？",
            snapshot=None,
            selected_event=None,
            daily_brief={"events": []},
            evidence_items=[],
            thesis={"core_thesis": "模型猜测", "status": "draft"},
            recent_messages=[],
        )
        self.assertNotIn("confirmed_thesis", context)

    def test_thesis_without_affirmative_confirmation_marker_is_not_included(self):
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="公司怎么样？",
            snapshot=None,
            selected_event=None,
            daily_brief={"events": []},
            evidence_items=[],
            thesis={"version": 4, "core_thesis": "收入稳定"},
            recent_messages=[],
        )
        self.assertNotIn("confirmed_thesis", context)

    def test_confirmed_true_allows_whitelisted_thesis_fields(self):
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="公司怎么样？",
            snapshot=None,
            selected_event=None,
            daily_brief={"events": []},
            evidence_items=[],
            thesis={
                "version": 4,
                "core_thesis": "收入稳定",
                "confirmed": True,
                "ai_suggestion": "不应包含",
            },
            recent_messages=[],
        )
        self.assertEqual(
            context["confirmed_thesis"],
            {"version": 4, "core_thesis": "收入稳定"},
        )

    def test_question_focus_changes_density_not_safety(self):
        self.assertEqual(classify_question_focus("这个市盈率是什么意思？"), "concept")
        self.assertEqual(classify_question_focus("我现在很恐慌怎么办？"), "emotion")
        self.assertEqual(classify_question_focus("这件事影响公司利润吗？"), "asset_analysis")
        self.assertEqual(classify_question_focus("帮我定买入和止损计划"), "trading_plan")
        self.assertEqual(classify_question_focus("发生了什么？"), "information")


if __name__ == "__main__":
    unittest.main()
