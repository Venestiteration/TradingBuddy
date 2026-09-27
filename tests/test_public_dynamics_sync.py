import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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

    def _sync_items(self, items):
        return sync_public_dynamics(
            self.asset,
            force=True,
            now=self.now,
            adapters=tuple(
                FakeAdapter(
                    provider,
                    provider_result(
                        provider,
                        "success",
                        [item for item in items if item.provider == provider],
                    ),
                )
                for provider in ("cninfo", "eastmoney_notices", "eastmoney_news")
            ),
        )

    def test_same_title_news_do_not_overwrite_on_incremental_reruns(self):
        early = replace(
            raw_item("eastmoney_news", "early", "news"),
            title="公司经营最新情况",
            published_at="2026-09-20T01:00:00+00:00",
        )
        late = replace(
            raw_item("eastmoney_news", "late", "news"),
            title=early.title,
            published_at="2026-09-20T12:00:00+00:00",
        )
        self._sync_items([early, late])
        before = db.query("SELECT id, canonical_key FROM public_dynamics ORDER BY id")
        self.assertEqual(len(before), 2)
        self._sync_items([early])
        self._sync_items([late])
        self.assertEqual(
            before,
            db.query("SELECT id, canonical_key FROM public_dynamics ORDER BY id"),
        )
        self.assertEqual(
            [len(dynamic_evidence(row["id"])) for row in before], [1, 1]
        )

    def test_cninfo_pdf_wins_over_newer_index_and_replaces_fallback_after_recovery(self):
        fallback = replace(
            raw_item("eastmoney_notices", "index"),
            title="关于收到监管工作函的公告",
            published_at="2026-09-20T09:00:00+00:00",
        )
        official = replace(raw_item("cninfo", "pdf"), title=fallback.title)
        self._sync_items([fallback])
        dynamic_id = db.query_one("SELECT id FROM public_dynamics")["id"]
        self.assertEqual(
            dynamic_evidence(dynamic_id)[0]["raw"]["provider"],
            "eastmoney_notices",
        )
        self._sync_items([official])
        self.assertEqual(len(db.query("SELECT id FROM public_dynamics")), 1)
        evidence = dynamic_evidence(dynamic_id)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["raw"]["provider"], "cninfo")
        self.assertEqual(evidence[0]["relation"], "primary")
        self.assertIsNotNone(evidence[0]["raw"]["document_url"])
        self._sync_items([fallback, official])
        self.assertEqual(
            dynamic_evidence(dynamic_id)[0]["raw"]["provider"], "cninfo"
        )
        self.assertEqual(
            sum(e["relation"] == "primary" for e in dynamic_evidence(dynamic_id)),
            1,
        )

    def test_metadata_recovery_for_same_evidence_adds_document_url(self):
        official = raw_item("cninfo", "recover")
        self._sync_items([replace(official, document_url=None)])
        dynamic_id = db.query_one("SELECT id FROM public_dynamics")["id"]
        self._sync_items([official])
        evidence = dynamic_evidence(dynamic_id)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["raw"]["document_url"], official.document_url)

    def test_extract_then_sync_then_cache_read_preserves_full_status(self):
        from app.services.document_text import extract_dynamic_document
        from tests.test_document_text import FakeClient, FakeResponse, FIXTURES

        official = raw_item("cninfo", "extract")
        self._sync_items([official])
        dynamic_id = db.query_one("SELECT id FROM public_dynamics")["id"]
        client = FakeClient(
            [
                FakeResponse(
                    headers={"content-type": "application/pdf"},
                    content=(FIXTURES / "searchable.pdf").read_bytes(),
                )
            ]
        )
        first = extract_dynamic_document(dynamic_id, client=client)
        self.assertEqual(first["extraction_status"], "extracted")
        # A source remains title-only after extraction; both rerun and source
        # omission must retain the extracted audit evidence and canonical state.
        fallback = replace(raw_item("eastmoney_notices", "index"), title=official.title)
        for items in ([official], [fallback]):
            self._sync_items(items)
            self.assertEqual(get_public_dynamic(dynamic_id)["content_status"], "full")
            second = extract_dynamic_document(dynamic_id, client=client)
            self.assertEqual(second, first)
            self.assertEqual(dynamic_evidence(dynamic_id)[0]["content_status"], "full")
        self.assertEqual(len(client.requested_urls), 1)

    def test_limited_news_are_persisted_without_advancing_complete_sync(self):
        complete = sync_public_dynamics(
            self.asset,
            force=True,
            now=self.now,
            adapters=(
                FakeAdapter("cninfo", provider_result("cninfo", "empty")),
                FakeAdapter(
                    "eastmoney_news", provider_result("eastmoney_news", "empty")
                ),
            ),
        )
        self.assertEqual(complete["status"], "complete")
        previous_complete_at = complete["last_complete_at"]
        later = self.now + timedelta(hours=1)
        limited = ProviderResult(
            "eastmoney_news",
            "failed",
            (raw_item("eastmoney_news", "limited", "news"),),
            later.isoformat(),
            "coverage_limited",
            "fixed first page",
        )
        result = sync_public_dynamics(
            self.asset,
            force=True,
            now=later,
            adapters=(
                FakeAdapter("cninfo", provider_result("cninfo", "empty")),
                FakeAdapter("eastmoney_news", limited),
            ),
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["last_complete_at"], previous_complete_at)
        self.assertEqual(len(db.query("SELECT * FROM public_dynamics")), 1)
        sync_state = db.query_one(
            "SELECT * FROM public_dynamics_sync_state WHERE asset_id = ?",
            (self.asset_id,),
        )
        self.assertEqual(sync_state["last_status"], "partial")
        self.assertEqual(sync_state["last_complete_at"], previous_complete_at)
        state = db.query_one(
            "SELECT * FROM source_sync_state WHERE provider = 'eastmoney_news'"
        )
        self.assertEqual(
            state["last_success_at"],
            provider_result("eastmoney_news", "empty").attempted_at,
        )
        self.assertEqual(state["last_error_code"], "coverage_limited")

    def test_blocked_provider_is_bounded_and_late_result_never_persists(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class BlockingAdapter(FakeAdapter):
            def fetch(self, *args):
                self.calls += 1
                entered.set()
                release.wait(3)
                finished.set()
                return self.result

        blocked = BlockingAdapter(
            "eastmoney_notices",
            provider_result(
                "eastmoney_notices",
                "success",
                [raw_item("eastmoney_notices", "late-result")],
            ),
        )
        adapters = (
            FakeAdapter("cninfo", provider_result("cninfo", "empty")),
            blocked,
            FakeAdapter("eastmoney_news", provider_result("eastmoney_news", "empty")),
        )
        try:
            with patch("app.services.public_dynamics.SOURCE_TIMEOUT_SECONDS", 0.05):
                start = time.monotonic()
                result = sync_public_dynamics(
                    self.asset, force=True, now=self.now, adapters=adapters
                )
                self.assertLess(time.monotonic() - start, 1)
                self.assertTrue(entered.is_set())
                provider = next(
                    p
                    for p in result["providers"]
                    if p["provider"] == "eastmoney_notices"
                )
                self.assertEqual(provider["error_code"], "TimeoutError")
                sync_public_dynamics(
                    self.asset, force=True, now=self.now, adapters=adapters
                )
                self.assertEqual(blocked.calls, 1)
                self.assertEqual(db.query("SELECT * FROM evidence"), [])
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
        # Let the worker retire before another test reuses the same provider.
        from app.services.public_dynamics import (
            _provider_workers,
            _provider_workers_lock,
        )

        with _provider_workers_lock:
            late_future = _provider_workers.get("eastmoney_notices")
        if late_future:
            late_future.result(timeout=1)
        self.assertEqual(db.query("SELECT * FROM evidence"), [])

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
