from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from app.services.research_events import (
    build_research_events,
    cluster_dynamic_rows,
    get_research_event,
)


def dynamic(row_id, title, published_at, *, kind="news", summary="", evidence=None):
    return {
        "id": row_id,
        "asset_id": 7,
        "kind": kind,
        "category": "媒体报道" if kind == "news" else "日常经营与重大合同",
        "canonical_title": title,
        "summary": summary,
        "published_at": published_at,
        "importance_score": 70.0,
        "content_status": "excerpt" if summary else "title_only",
        "conflict_status": "none",
        "evidence": evidence or [],
    }


class ResearchEventClusteringTest(TestCase):
    def test_duplicate_media_reports_form_one_stable_cluster(self):
        first = dynamic(11, "公司签署重大供货合同", "2026-09-28T01:00:00+00:00")
        second = dynamic(18, "公司签订重大供货合同", "2026-09-28T03:00:00+00:00")
        events = cluster_dynamic_rows(
            [first, second], now=datetime(2026, 9, 28, 8, tzinfo=timezone.utc)
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cluster_id"], "7:11")
        self.assertEqual(events[0]["dynamic_ids"], [11, 18])

    def test_new_member_does_not_change_cluster_id(self):
        base = [dynamic(11, "公司签署重大供货合同", "2026-09-28T01:00:00+00:00")]
        expanded = base + [
            dynamic(24, "公司签订重大供货合同", "2026-09-28T04:00:00+00:00")
        ]
        self.assertEqual(
            cluster_dynamic_rows(base)[0]["cluster_id"],
            cluster_dynamic_rows(expanded)[0]["cluster_id"],
        )

    def test_conflicting_numbers_are_retained(self):
        rows = [
            dynamic(3, "合同金额为10亿元", "2026-09-28T01:00:00+00:00"),
            dynamic(4, "合同金额为12亿元", "2026-09-28T02:00:00+00:00"),
        ]
        event = cluster_dynamic_rows(rows)[0]
        self.assertEqual(event["conflict_status"], "possible")
        self.assertEqual(
            {item["title"] for item in event["conflicts"]},
            {row["canonical_title"] for row in rows},
        )

    def test_market_words_alone_do_not_merge_unrelated_events(self):
        rows = [
            dynamic(1, "公司获得新订单", "2026-09-28T01:00:00+00:00"),
            dynamic(2, "公司股价上涨", "2026-09-28T02:00:00+00:00"),
        ]
        self.assertEqual(len(cluster_dynamic_rows(rows)), 2)

    def test_short_negated_media_claims_merge_and_remain_conflicting(self):
        rows = [
            dynamic(1, "公司中标", "2026-09-28T01:00:00+00:00"),
            dynamic(2, "公司未中标", "2026-09-28T02:00:00+00:00"),
        ]

        events = cluster_dynamic_rows(rows)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["conflict_status"], "possible")
        self.assertEqual(
            {item["title"] for item in events[0]["conflicts"]},
            {"公司中标", "公司未中标"},
        )

    def test_conflicting_numbers_in_summaries_are_retained(self):
        rows = [
            dynamic(
                3,
                "公司签订重大供货合同",
                "2026-09-28T01:00:00+00:00",
                summary="合同金额为10亿元",
            ),
            dynamic(
                4,
                "公司签订重大供货合同",
                "2026-09-28T02:00:00+00:00",
                summary="合同金额为12亿元",
            ),
        ]

        event = cluster_dynamic_rows(rows)[0]

        self.assertEqual(event["conflict_status"], "possible")
        self.assertEqual(
            {item["summary"] for item in event["conflicts"]},
            {"合同金额为10亿元", "合同金额为12亿元"},
        )

    def test_media_cluster_span_cannot_grow_past_36_hours_by_chaining(self):
        rows = [
            dynamic(5, "公司签订重大供货合同", "2026-09-25T00:00:00+00:00"),
            dynamic(6, "公司签订重大供货合同", "2026-09-26T11:00:00+00:00"),
            dynamic(7, "公司签订重大供货合同", "2026-09-27T22:00:00+00:00"),
        ]

        events = cluster_dynamic_rows(rows)

        self.assertEqual(len(events), 2)
        self.assertIn([5, 6], [event["dynamic_ids"] for event in events])
        self.assertIn([7], [event["dynamic_ids"] for event in events])

    def test_mixed_cluster_span_cannot_grow_past_72_hours_by_chaining(self):
        announcement = dynamic(
            8,
            "公司签订重大供货合同",
            "2026-09-23T00:00:00+00:00",
            kind="announcement",
        )
        first_news = dynamic(
            9, "公司签订重大供货合同", "2026-09-26T00:00:00+00:00"
        )
        chained_news = dynamic(
            10, "公司签订重大供货合同", "2026-09-27T12:00:00+00:00"
        )
        first_news["category"] = announcement["category"]
        chained_news["category"] = announcement["category"]

        events = cluster_dynamic_rows([announcement, first_news, chained_news])

        self.assertEqual(len(events), 2)
        self.assertIn([8, 9], [event["dynamic_ids"] for event in events])
        self.assertIn([10], [event["dynamic_ids"] for event in events])

    def test_event_shape_and_evidence_are_stable_and_deduplicated(self):
        shared = {
            "evidence_id": "shared",
            "title": "一级公告标题",
            "source_level": "primary",
            "content_status": "full",
            "raw": {"provider": "cninfo"},
        }
        weaker = {
            "evidence_id": "secondary",
            "title": "媒体标题",
            "source_level": "secondary",
            "content_status": "excerpt",
            "raw": {"provider": "eastmoney_news"},
        }
        rows = [
            dynamic(
                11,
                "公司签署重大供货合同",
                "2026-09-28T01:00:00+00:00",
                summary="有限摘要",
                evidence=[weaker, shared],
            ),
            dynamic(
                18,
                "公司签订重大供货合同",
                "2026-09-28T03:00:00+00:00",
                evidence=[shared.copy()],
            ),
        ]

        event = cluster_dynamic_rows(rows, now=datetime(2026, 9, 28, 8, tzinfo=timezone.utc))[0]

        self.assertEqual(
            set(event),
            {
                "cluster_id",
                "asset_id",
                "dynamic_ids",
                "title",
                "summary",
                "published_at",
                "category",
                "kinds",
                "content_status",
                "conflict_status",
                "conflicts",
                "attention_score",
                "attention_factors",
                "source_count",
                "evidence",
            },
        )
        self.assertEqual(event["title"], "一级公告标题")
        self.assertEqual(event["summary"], "有限摘要")
        self.assertEqual([item["evidence_id"] for item in event["evidence"]], ["shared", "secondary"])
        self.assertEqual(event["source_count"], 2)

    @patch("app.services.research_events.dynamic_evidence")
    @patch("app.services.research_events.list_public_dynamics")
    def test_build_and_get_load_linked_evidence(self, list_rows, linked_evidence):
        start = datetime(2026, 9, 28, tzinfo=timezone.utc)
        end = datetime(2026, 9, 29, tzinfo=timezone.utc)
        list_rows.return_value = [
            dynamic(11, "公司签署重大供货合同", "2026-09-28T01:00:00+00:00")
        ]
        linked_evidence.return_value = [{"evidence_id": "e-11"}]

        events = build_research_events(7, start, end)
        selected = get_research_event(7, "7:11", start, end)

        self.assertEqual(events[0]["evidence"], [{"evidence_id": "e-11"}])
        self.assertEqual(selected["cluster_id"], "7:11")
        list_rows.assert_called_with(7, start, end, kind="all")
        linked_evidence.assert_called_with(11, asset_id=7)


if __name__ == "__main__":
    import unittest

    unittest.main()
