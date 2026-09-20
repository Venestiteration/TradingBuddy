import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database as db
from app.main import create_app
from app.services.visitor_ai import VisitorAIConfig, visitor_ai_config


def completed_stream(**kwargs):
    yield "event: completed\ndata: " + json.dumps({
        "mode": kwargs["mode"],
        "question": kwargs["question"],
        "event_id": (kwargs.get("event") or {}).get("event_id"),
        "model": kwargs["config"].model,
        "result": {
            "conclusion": "测试结论",
            "impact_state": "insufficient",
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "next_checks": [],
            "safety_boundary": "不构成投资建议",
        },
    }, ensure_ascii=False) + "\n\n"


class VisitorAIRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        now = db.utcnow()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)", (now, now),
        )
        db.execute(
            "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, title, excerpt, "
            "published_at, fetched_at, content_status, raw) VALUES "
            "('ev-1', '600000', 'news', 'secondary', '测试事件', '测试摘要', ?, ?, 'excerpt', '{}')",
            (now, now),
        )
        self.client = TestClient(create_app())
        self.headers = {
            "X-TB-API-Key": "visitor-key",
            "X-TB-Model": "test-model",
        }

    def configured_client(self):
        app = create_app()
        app.dependency_overrides[visitor_ai_config] = lambda: VisitorAIConfig(
            api_key="visitor-key",
            model="test-model",
            base_url="https://api.openai.com/v1",
            resolved_ips=("8.8.8.8",),
        )
        return TestClient(app)

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def test_missing_visitor_config_is_rejected(self):
        response = self.client.post("/api/research/stream", json={"asset_id": self.asset_id, "event_id": "ev-1"})
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.research.run_grounded_stream", side_effect=completed_stream)
    def test_research_does_not_persist_analysis(self, mocked):
        response = self.configured_client().post(
            "/api/research/stream",
            json={"asset_id": self.asset_id, "event_id": "ev-1"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM analyses")["count"], 0)

    @patch("app.routers.chat.run_grounded_stream", side_effect=completed_stream)
    def test_chat_uses_client_context_without_persistence(self, mocked):
        response = self.configured_client().post(
            "/api/chat/stream",
            json={
                "asset_id": self.asset_id,
                "event_id": "ev-1",
                "question": "影响是什么？",
                "recent_messages": [{"role": "user", "content": "上一问"}],
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_args.kwargs["recent_messages"], [{"role": "user", "content": "上一问"}])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM messages")["count"], 0)

    def test_overview_omits_shared_ai_history_and_health_reports_capability(self):
        health = self.client.get("/api/health").json()
        self.assertTrue(health["visitor_ai_supported"])
        with patch("app.routers.assets.market_service.snapshot", return_value={"name": "浦发银行"}), \
             patch("app.routers.assets.market_service.history", return_value={"rows": [], "data_time": "2026-09-20"}), \
             patch("app.routers.assets.collect_events", return_value={"events": [], "errors": [], "fetched_at": db.utcnow()}):
            overview = self.client.get(f"/api/assets/{self.asset_id}/overview").json()
        self.assertNotIn("messages", overview)
        self.assertNotIn("analyses", overview)
        self.assertNotIn("latest_analysis", overview)

    def test_ai_thesis_draft_generation_is_unavailable(self):
        response = self.client.post(
            f"/api/assets/{self.asset_id}/thesis-drafts/generate",
            json={"message_ids": [], "evidence_ids": []},
        )
        self.assertEqual(response.status_code, 410)
