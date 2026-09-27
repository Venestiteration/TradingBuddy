import unittest
from dataclasses import replace

from app.services.public_dynamics_aggregate import (
    aggregate_raw_dynamics,
    classify_announcement,
    evidence_identity,
    normalize_title,
)
from app.services.public_dynamics_types import RawDynamic


def item(provider, item_id, title, published, kind="announcement", excerpt=""):
    return RawDynamic(
        provider=provider,
        provider_item_id=item_id,
        stock_code="600519",
        kind=kind,
        category="风险提示" if kind == "announcement" else "媒体报道",
        title=title,
        excerpt=excerpt,
        published_at=published,
        publisher="巨潮资讯网" if provider == "cninfo" else "证券时报",
        source_url=f"https://example.test/{item_id}",
        source_level="primary" if provider == "cninfo" else "secondary",
        content_status="excerpt" if excerpt else "title_only",
    )


class PublicDynamicsAggregateTest(unittest.TestCase):
    def test_same_title_news_eleven_hours_apart_have_distinct_stable_keys(self):
        early = item(
            "eastmoney_news",
            "early",
            "公司经营最新情况",
            "2026-09-15T01:00:00+00:00",
            "news",
        )
        late = replace(
            early,
            provider_item_id="late",
            source_url="https://example.test/late",
            published_at="2026-09-15T12:00:00+00:00",
        )
        clusters = aggregate_raw_dynamics([early, late])
        self.assertEqual(len({cluster.canonical_key for cluster in clusters}), 2)
        for row in (early, late):
            self.assertIn(
                aggregate_raw_dynamics([row])[0].canonical_key,
                {cluster.canonical_key for cluster in clusters},
            )

    def test_official_key_matches_business_date_across_providers_and_utc_days(self):
        early = item(
            "eastmoney_notices",
            "index",
            "关于收到监管工作函的公告",
            "2026-09-14T16:00:00+00:00",
        )
        late = item("cninfo", "pdf", early.title, "2026-09-15T08:00:00+00:00")
        self.assertEqual(len(aggregate_raw_dynamics([early, late])), 1)
        self.assertEqual(
            aggregate_raw_dynamics([early])[0].canonical_key,
            aggregate_raw_dynamics([late])[0].canonical_key,
        )

    def test_naive_announcement_time_is_shanghai_local_for_canonical_date(self):
        local = item(
            "eastmoney_notices",
            "index",
            "关于收到监管工作函的公告",
            "2026-09-15T23:30:00",
        )
        utc = item(
            "cninfo",
            "pdf",
            local.title,
            "2026-09-15T15:30:00+00:00",
        )

        clusters = aggregate_raw_dynamics([local, utc])

        self.assertEqual(len(clusters), 1)
        self.assertEqual(
            aggregate_raw_dynamics([local])[0].canonical_key,
            aggregate_raw_dynamics([utc])[0].canonical_key,
        )

    def test_normalize_title_removes_punctuation_and_case(self):
        self.assertEqual(normalize_title("关于 监管-函：ABC 12！"), "关于监管函abc12")

    def test_classify_announcement_uses_title_or_source_category(self):
        self.assertEqual(
            classify_announcement("关于收到监管工作函的公告", "其他"),
            "监管问询、处罚与风险提示",
        )
        self.assertEqual(
            classify_announcement("关于某事项的公告", "股东变动"),
            "分红、回购及股东变动",
        )

    def test_evidence_identity_is_stable_and_source_specific(self):
        first = item("cninfo", "1", "公告", "2026-09-15T08:00:00+08:00")
        same = item("cninfo", "1", "另一标题", "2026-09-15T08:05:00+08:00")
        other = item("cninfo", "2", "公告", "2026-09-15T08:00:00+08:00")
        self.assertEqual(evidence_identity(first), evidence_identity(same))
        self.assertNotEqual(evidence_identity(first), evidence_identity(other))

    def test_same_announcement_across_sources_merges_and_preserves_members(self):
        rows = [
            item("cninfo", "1", "关于收到监管工作函的公告", "2026-09-15T08:41:00+08:00"),
            item("eastmoney_notices", "2", "关于收到监管工作函的公告", "2026-09-15T00:00:00+08:00"),
        ]
        clusters = aggregate_raw_dynamics(rows)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0].members), 2)
        self.assertEqual(clusters[0].category, "监管问询、处罚与风险提示")

    def test_different_numbers_do_not_merge(self):
        rows = [
            item("eastmoney_news", "1", "公司签订10亿元合同", "2026-09-15T08:00:00+08:00", "news"),
            item("eastmoney_news", "2", "公司签订12亿元合同", "2026-09-15T08:05:00+08:00", "news"),
        ]
        self.assertEqual(len(aggregate_raw_dynamics(rows)), 2)

    def test_low_importance_items_are_returned_with_explainable_scores(self):
        rows = [item("cninfo", "1", "董事会会议决议公告", "2026-09-15T08:00:00+08:00")]
        cluster = aggregate_raw_dynamics(rows)[0]
        self.assertGreaterEqual(cluster.importance_score, 0)
        self.assertLessEqual(cluster.importance_score, 100)
        self.assertEqual(
            cluster.importance_factors,
            {"authority": 95.0, "materiality": 75.0, "relevance": 100.0, "completeness": 45.0},
        )


if __name__ == "__main__":
    unittest.main()
