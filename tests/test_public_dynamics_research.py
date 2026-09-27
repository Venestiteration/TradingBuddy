import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database as db
from app.main import create_app
from app.services.visitor_ai import VisitorAIConfig, visitor_ai_config


def completed_stream(**kwargs):
    yield "event: completed\ndata: {}\n\n"


class PublicDynamicsResearchTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()

        now = db.utcnow()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, "
            "notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)",
            (now, now),
        )
        self.primary_evidence_id = "primary-evidence"
        self.secondary_evidence_id = "secondary-evidence"
        db.execute(
            "INSERT INTO evidence (evidence_id, stock_code, source_type, "
            "source_level, title, excerpt, published_at, fetched_at, "
            "content_status, raw) VALUES (?, '600000', 'announcement', "
            "'primary', '测试公告', '公告摘要', ?, ?, 'full', '{}')",
            (self.primary_evidence_id, now, "2020-01-01T00:00:00+00:00"),
        )
        db.execute(
            "INSERT INTO evidence (evidence_id, stock_code, source_type, "
            "source_level, title, excerpt, published_at, fetched_at, "
            "content_status, raw) VALUES (?, '600000', 'news', "
            "'secondary', '媒体核实', '新闻摘要', ?, ?, 'excerpt', '{}')",
            (self.secondary_evidence_id, now, "2020-01-01T00:00:00+00:00"),
        )
        self.dynamic_id = db.execute(
            "INSERT INTO public_dynamics (asset_id, canonical_key, kind, category, "
            "canonical_title, summary, published_at, importance_score, "
            "importance_factors_json, formula_version, content_status, "
            "conflict_status, created_at, updated_at) VALUES "
            "(?, 'dynamic-key', 'announcement', '公司公告', '聚合后公开动态', "
            "'聚合摘要', ?, 88, '{}', 'public-dynamics-v1', 'full', "
            "'none', ?, ?)",
            (self.asset_id, now, now, now),
        )
        db.execute(
            "INSERT INTO public_dynamic_evidence "
            "(dynamic_id, evidence_id, relation, created_at) VALUES (?, ?, 'primary', ?)",
            (self.dynamic_id, self.primary_evidence_id, now),
        )
        db.execute(
            "INSERT INTO public_dynamic_evidence "
            "(dynamic_id, evidence_id, relation, created_at) "
            "VALUES (?, ?, 'corroborating', ?)",
            (self.dynamic_id, self.secondary_evidence_id, now),
        )

        app = create_app()
        app.dependency_overrides[visitor_ai_config] = lambda: VisitorAIConfig(
            api_key="visitor-key",
            model="test-model",
            base_url="https://api.openai.com/v1",
            resolved_ips=("8.8.8.8",),
        )
        self.client = TestClient(app)

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    @patch("app.routers.research.run_grounded_stream", side_effect=completed_stream)
    def test_research_dynamic_loads_every_linked_evidence_without_persistence(self, run):
        response = self.client.post(
            "/api/research/stream",
            json={
                "asset_id": self.asset_id,
                "event_id": self.primary_evidence_id,
                "dynamic_id": self.dynamic_id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["evidence_id"] for item in run.call_args.kwargs["evidence_items"]},
            {self.primary_evidence_id, self.secondary_evidence_id},
        )
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM analyses")["count"], 0)

    @patch("app.routers.chat.run_grounded_stream", side_effect=completed_stream)
    def test_chat_dynamic_loads_every_linked_evidence_without_persistence(self, run):
        response = self.client.post(
            "/api/chat/stream",
            json={
                "asset_id": self.asset_id,
                "question": "这条动态有什么影响？",
                "dynamic_id": self.dynamic_id,
            },
        )

        self.assertEqual(response.status_code, 200)
        linked = {
            self.primary_evidence_id,
            self.secondary_evidence_id,
        }
        self.assertTrue(
            linked.issubset(
                {item["evidence_id"] for item in run.call_args.kwargs["evidence_items"]}
            )
        )
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM messages")["count"], 0)

    def test_dynamic_from_another_asset_is_rejected(self):
        now = db.utcnow()
        other_asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, "
            "notifications_enabled, created_at, updated_at) "
            "VALUES ('000001', '平安银行', 'watchlist', 0, ?, ?)",
            (now, now),
        )

        response = self.client.post(
            "/api/chat/stream",
            json={
                "asset_id": other_asset_id,
                "question": "这条动态有什么影响？",
                "dynamic_id": self.dynamic_id,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "公开动态不存在或不属于当前标的")

    @patch("app.routers.assets.collect_market_event")
    @patch("app.routers.assets.market_service.history")
    @patch("app.routers.assets.market_service.snapshot")
    @patch("app.routers.assets.sync_public_dynamics")
    def test_overview_prefers_canonical_dynamic_and_preserves_primary_event_id(
        self, sync, snapshot, history, collect
    ):
        sync.return_value = {"status": "complete", "synced": False}
        snapshot.return_value = {"name": "浦发银行", "price": 10, "change_pct": 0}
        history.return_value = {"rows": [], "data_time": "2026-09-21"}
        collect.return_value = {
            "events": [
                {"event_id": "legacy-news", "source_type": "news"},
                {"event_id": "market-fact", "source_type": "market"},
            ],
            "errors": [],
        }

        response = self.client.get(f"/api/assets/{self.asset_id}/overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["dynamic_id"], self.dynamic_id)
        self.assertEqual(payload["events"][0]["event_id"], self.primary_evidence_id)
        self.assertEqual(payload["events"][0]["source_count"], 2)
        self.assertEqual(payload["public_sync"], sync.return_value)
        sync.assert_called_once()
        self.assertFalse(sync.call_args.kwargs["force"])
        collect.assert_not_called()

    @patch("app.routers.assets.collect_market_event")
    @patch("app.routers.assets.market_service.history")
    @patch("app.routers.assets.market_service.snapshot")
    @patch("app.routers.assets.sync_public_dynamics")
    def test_refresh_forces_exactly_one_public_sync(
        self, sync, snapshot, history, collect
    ):
        sync.return_value = {"status": "complete", "synced": True}
        snapshot.return_value = {"name": "浦发银行", "price": 10, "change_pct": 0}
        history.return_value = {"rows": [], "data_time": "2026-09-21"}
        collect.return_value = {"events": [], "errors": []}

        response = self.client.post(f"/api/assets/{self.asset_id}/refresh")

        self.assertEqual(response.status_code, 200)
        sync.assert_called_once()
        self.assertTrue(sync.call_args.kwargs["force"])

    @patch("app.routers.assets.collect_market_event")
    @patch("app.routers.assets.market_service.history")
    @patch("app.routers.assets.market_service.snapshot")
    @patch("app.routers.assets.sync_public_dynamics", side_effect=RuntimeError("boom"))
    def test_sync_failure_keeps_market_and_local_dynamic_available(
        self, sync, snapshot, history, collect
    ):
        snapshot.return_value = {"name": "浦发银行", "price": 10, "change_pct": 0}
        history.return_value = {"rows": [], "data_time": "2026-09-21"}
        collect.return_value = {"events": [], "errors": []}

        response = self.client.get(f"/api/assets/{self.asset_id}/overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNotNone(payload["snapshot"])
        self.assertIsNotNone(payload["history"])
        self.assertEqual(payload["events"][0]["dynamic_id"], self.dynamic_id)
        self.assertIn("public_dynamics", payload["errors"])
        self.assertIsNone(payload["public_sync"])

    @patch("app.services.events._fetch_news")
    @patch("app.services.events._fetch_announcements")
    @patch("app.routers.assets.market_service.history")
    @patch("app.routers.assets.market_service.snapshot")
    def test_fresh_public_sync_never_calls_legacy_sources_and_keeps_market_fallback(
        self, snapshot, history, announcements, news
    ):
        now = db.utcnow()
        db.execute(
            "INSERT INTO public_dynamics_sync_state "
            "(asset_id, last_attempt_at, last_complete_at, last_status, updated_at) "
            "VALUES (?, ?, ?, 'complete', ?)",
            (self.asset_id, now, now, now),
        )
        snapshot.return_value = {
            "name": "浦发银行",
            "price": 10,
            "change_pct": 3,
            "price_time": now,
        }
        history.return_value = {"rows": [], "data_time": now}
        for has_canonical in (True, False):
            if not has_canonical:
                db.execute("DELETE FROM public_dynamics WHERE asset_id = ?", (self.asset_id,))
            response = self.client.get(f"/api/assets/{self.asset_id}/overview")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["public_sync"]["decision"], "fresh")
            self.assertEqual(len(body["events"]), 1)
            self.assertEqual(
                body["events"][0]["source_type"],
                "announcement" if has_canonical else "market",
            )
        announcements.assert_not_called()
        news.assert_not_called()


if __name__ == "__main__":
    unittest.main()
