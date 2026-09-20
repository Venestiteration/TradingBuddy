import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import database as db
from app.services.public_dynamics import (
    decide_sync,
    dynamic_evidence,
    get_public_dynamic,
    list_public_dynamics,
    sync_public_dynamics,
)
from app.services.public_dynamics_types import ProviderResult, RawDynamic


class FakeAdapter:
    def __init__(self, provider, result):
        self.provider = provider
        self.result = result
        self.calls = 0

    def fetch(self, stock_code, start, end, attempted_at):
        self.calls += 1
        return self.result


def raw_item(provider, item_id, kind="announcement"):
    return RawDynamic(
        provider=provider,
        provider_item_id=item_id,
        stock_code="600519",
        kind=kind,
        category="风险提示" if kind == "announcement" else "媒体报道",
        title=f"{item_id} 公司公开动态",
        excerpt="可核验摘要" if kind == "news" else "",
        published_at="2026-09-20T08:00:00+00:00",
        publisher="巨潮资讯网" if provider == "cninfo" else "证券时报",
        source_url=f"https://example.test/{provider}/{item_id}",
        document_url=(
            f"https://static.cninfo.com.cn/{item_id}.pdf"
            if provider == "cninfo"
            else None
        ),
        source_level="primary" if kind == "announcement" else "secondary",
        content_status="excerpt" if kind == "news" else "title_only",
        raw_metadata={"fixture": True},
    )


def provider_result(provider, status, items=()):
    return ProviderResult(
        provider=provider,
        status=status,
        items=tuple(items),
        attempted_at="2026-09-20T10:00:00+00:00",
        error_code="upstream_error" if status == "failed" else None,
        error_message="unavailable" if status == "failed" else None,
    )


class PublicDynamicsSyncTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        created_at = db.utcnow()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, "
            "notifications_enabled, created_at, updated_at) "
            "VALUES ('600519', '贵州茅台', 'watchlist', 0, ?, ?)",
            (created_at, created_at),
        )
        self.asset = db.query_one("SELECT * FROM assets WHERE id = ?", (self.asset_id,))
        self.now = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        db.settings.database_path = self.original_db
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def test_decide_sync_obeys_24_hours_and_30_minute_failure_cooldown(self):
        fresh = {
            "last_complete_at": (self.now - timedelta(hours=23)).isoformat(),
            "last_attempt_at": (self.now - timedelta(hours=23)).isoformat(),
            "last_status": "complete",
        }
        self.assertFalse(decide_sync(fresh, False, self.now).should_sync)
        stale = {
            **fresh,
            "last_complete_at": (self.now - timedelta(hours=25)).isoformat(),
        }
        self.assertTrue(decide_sync(stale, False, self.now).should_sync)
        failed = {
            **stale,
            "last_attempt_at": (self.now - timedelta(minutes=10)).isoformat(),
            "last_status": "failed",
        }
        self.assertFalse(decide_sync(failed, False, self.now).should_sync)
        self.assertTrue(decide_sync(failed, True, self.now).should_sync)
        partial = {**failed, "last_status": "partial"}
        self.assertFalse(decide_sync(partial, False, self.now).should_sync)

    def test_one_official_provider_and_media_make_complete_status(self):
        adapters = (
            FakeAdapter(
                "cninfo",
                provider_result("cninfo", "success", [raw_item("cninfo", "official")]),
            ),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news",
                provider_result(
                    "eastmoney_news",
                    "success",
                    [raw_item("eastmoney_news", "media", kind="news")],
                ),
            ),
        )

        result = sync_public_dynamics(
            self.asset, force=True, now=self.now, adapters=adapters
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["last_complete_at"], self.now.isoformat())

    def test_media_persists_when_both_official_providers_fail(self):
        media_item = raw_item("eastmoney_news", "media-only", kind="news")
        adapters = (
            FakeAdapter("cninfo", provider_result("cninfo", "failed")),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news",
                provider_result("eastmoney_news", "success", [media_item]),
            ),
        )

        result = sync_public_dynamics(
            self.asset, force=True, now=self.now, adapters=adapters
        )

        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["last_complete_at"])
        evidence = db.query_one(
            "SELECT raw FROM evidence WHERE stock_code = ?", ("600519",)
        )
        self.assertIsNotNone(evidence)
        self.assertIn('"provider": "eastmoney_news"', evidence["raw"])

    def test_fresh_state_skips_adapters(self):
        adapters = (
            FakeAdapter("cninfo", provider_result("cninfo", "empty")),
            FakeAdapter(
                "eastmoney_notices", provider_result("eastmoney_notices", "empty")
            ),
            FakeAdapter(
                "eastmoney_news", provider_result("eastmoney_news", "empty")
            ),
        )
        first = sync_public_dynamics(
            self.asset, force=True, now=self.now, adapters=adapters
        )
        second = sync_public_dynamics(
            self.asset,
            now=self.now + timedelta(hours=23),
            adapters=adapters,
        )

        self.assertEqual(first["status"], "complete")
        self.assertFalse(second["synced"])
        self.assertEqual(second["decision"], "fresh")
        self.assertEqual([adapter.calls for adapter in adapters], [1, 1, 1])

    def test_queries_use_utc_bounds_and_parse_joined_evidence(self):
        offset_item = replace(
            raw_item("cninfo", "offset-time"),
            published_at="2026-09-20T12:00:00+08:00",
        )
        adapters = (
            FakeAdapter(
                "cninfo", provider_result("cninfo", "success", [offset_item])
            ),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news", provider_result("eastmoney_news", "empty")
            ),
        )
        sync_public_dynamics(self.asset, force=True, now=self.now, adapters=adapters)

        rows = list_public_dynamics(
            self.asset_id,
            datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 20, 5, 0, tzinfo=timezone.utc),
            kind="official",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["importance_factors"]["authority"], 95.0)
        detail = get_public_dynamic(rows[0]["id"])
        self.assertEqual(detail["evidence_count"], 1)
        self.assertEqual(detail["evidence"][0]["raw"]["provider"], "cninfo")
        self.assertEqual(detail["evidence"][0]["raw"]["publisher"], "巨潮资讯网")
        self.assertEqual(
            dynamic_evidence(rows[0]["id"], asset_id=self.asset_id)[0]["relation"],
            "primary",
        )

    def test_partial_incremental_sync_keeps_existing_evidence_links(self):
        initial_adapters = (
            FakeAdapter(
                "cninfo",
                provider_result("cninfo", "success", [raw_item("cninfo", "kept")]),
            ),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news", provider_result("eastmoney_news", "empty")
            ),
        )
        sync_public_dynamics(
            self.asset, force=True, now=self.now, adapters=initial_adapters
        )
        dynamic_id = db.query_one("SELECT id FROM public_dynamics")["id"]
        original_links = db.query(
            "SELECT evidence_id FROM public_dynamic_evidence WHERE dynamic_id = ?",
            (dynamic_id,),
        )

        partial_adapters = (
            FakeAdapter("cninfo", provider_result("cninfo", "failed")),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news", provider_result("eastmoney_news", "empty")
            ),
        )
        result = sync_public_dynamics(
            self.asset,
            force=True,
            now=self.now + timedelta(hours=1),
            adapters=partial_adapters,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            db.query(
                "SELECT evidence_id FROM public_dynamic_evidence WHERE dynamic_id = ?",
                (dynamic_id,),
            ),
            original_links,
        )

    def test_three_providers_are_fetched_concurrently(self):
        barrier = threading.Barrier(3)

        class BarrierAdapter(FakeAdapter):
            def fetch(self, stock_code, start, end, attempted_at):
                self.calls += 1
                barrier.wait(timeout=2)
                return self.result

        adapters = tuple(
            BarrierAdapter(provider, provider_result(provider, "empty"))
            for provider in ("cninfo", "eastmoney_notices", "eastmoney_news")
        )

        result = sync_public_dynamics(
            self.asset, force=True, now=self.now, adapters=adapters
        )

        self.assertEqual(result["status"], "complete")
        self.assertEqual([adapter.calls for adapter in adapters], [1, 1, 1])

    def test_write_failure_rolls_back_the_whole_sync_transaction(self):
        invalid_item = replace(raw_item("eastmoney_news", "invalid", kind="news"), title="")
        adapters = (
            FakeAdapter(
                "cninfo",
                provider_result("cninfo", "success", [raw_item("cninfo", "valid")]),
            ),
            FakeAdapter(
                "eastmoney_notices",
                provider_result("eastmoney_notices", "failed"),
            ),
            FakeAdapter(
                "eastmoney_news",
                provider_result("eastmoney_news", "success", [invalid_item]),
            ),
        )

        with self.assertRaisesRegex(ValueError, "证据标题不能为空"):
            sync_public_dynamics(
                self.asset, force=True, now=self.now, adapters=adapters
            )

        self.assertEqual(db.query("SELECT * FROM source_sync_state"), [])
        self.assertEqual(db.query("SELECT * FROM evidence"), [])
        self.assertEqual(db.query("SELECT * FROM public_dynamics"), [])
        self.assertEqual(db.query("SELECT * FROM public_dynamics_sync_state"), [])


if __name__ == "__main__":
    unittest.main()
