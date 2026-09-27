import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database as db
from app.main import create_app


def sample_event(**overrides):
    event = {
        "cluster_id": "1:10",
        "asset_id": 1,
        "dynamic_ids": [10],
        "title": "公司签署重大供货合同",
        "summary": "公司披露已签署供货合同。",
        "published_at": "2026-09-28T01:00:00+00:00",
        "category": "日常经营与重大合同",
        "kinds": ["announcement", "news"],
        "content_status": "excerpt",
        "conflict_status": "none",
        "conflicts": [],
        "attention_score": 86.0,
        "attention_factors": {},
        "source_count": 2,
        "evidence": [
            {
                "evidence_id": "e1",
                "title": "公司签署重大供货合同",
                "excerpt": "公司披露已签署供货合同。",
                "source_level": "primary",
                "source_type": "announcement",
                "content_status": "excerpt",
                "published_at": "2026-09-28T01:00:00+00:00",
                "source_url": "https://example.test/e1",
                "raw": {"document_text": "不应对外暴露"},
            }
        ],
    }
    event.update(overrides)
    return event


class ResearchBriefAPITest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        timestamp = datetime(2026, 9, 28, tzinfo=timezone.utc).isoformat()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, "
            "notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)",
            (timestamp, timestamp),
        )
        self.client = TestClient(create_app())

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    @patch("app.services.research_brief.build_research_events")
    def test_brief_is_an_event_report_not_a_single_news_copy(self, events):
        events.return_value = [sample_event(asset_id=self.asset_id, source_count=3)]

        response = self.client.get(
            f"/api/assets/{self.asset_id}/research-brief?hours=24"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["headline"]["cluster_id"], "1:10")
        self.assertIn("known_facts", body)
        self.assertIn("why_it_matters", body)
        self.assertIn("impact_paths", body)
        self.assertIn("unknowns", body)
        self.assertEqual(body["coverage"]["event_count"], 1)
        self.assertEqual(body["coverage"]["source_count"], 3)
        self.assertEqual(body["why_it_matters"][0]["basis"], "rule")
        self.assertEqual(body["impact_paths"][0]["basis"], "rule")
        self.assertNotIn("raw", body["sources"][0])
        self.assertNotIn("不应对外暴露", json.dumps(body, ensure_ascii=False))

    @patch("app.services.research_brief.build_research_events")
    def test_title_only_never_creates_causes_or_numbers(self, events):
        events.return_value = [
            sample_event(
                asset_id=self.asset_id,
                content_status="title_only",
                summary="",
            )
        ]

        body = self.client.get(
            f"/api/assets/{self.asset_id}/research-brief?hours=24"
        ).json()

        self.assertEqual(body["known_facts"][0]["claim"], events.return_value[0]["title"])
        self.assertEqual(body["why_it_matters"], [])
        self.assertEqual(body["impact_paths"], [])
        self.assertIn("当前仅有标题", body["unknowns"][0])

    @patch("app.services.research_brief.build_research_events", return_value=[])
    def test_empty_brief_is_readable(self, _events):
        body = self.client.get(
            f"/api/assets/{self.asset_id}/research-brief?hours=24"
        ).json()

        self.assertEqual(body["status"], "empty")
        self.assertEqual(body["events"], [])
        self.assertIsNone(body["headline"])
        self.assertEqual(body["coverage"], {"event_count": 0, "source_count": 0})

    @patch("app.services.research_brief.build_research_events")
    def test_conflict_is_preserved(self, events):
        events.return_value = [
            sample_event(
                asset_id=self.asset_id,
                conflict_status="possible",
                conflicts=[{"title": "10亿元"}, {"title": "12亿元"}],
            )
        ]

        body = self.client.get(
            f"/api/assets/{self.asset_id}/research-brief?hours=24"
        ).json()

        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["conflict_status"], "possible")
        self.assertTrue(any("冲突" in item for item in body["unknowns"]))

    @patch("app.routers.research_brief.get_research_event")
    def test_event_detail_is_asset_scoped(self, get_event):
        event = sample_event(asset_id=self.asset_id)
        get_event.return_value = event

        response = self.client.get(
            f"/api/assets/{self.asset_id}/research-events/1%3A10"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event"], event)
        self.assertEqual(get_event.call_args.args[0:2], (self.asset_id, "1:10"))

    @patch("app.routers.research_brief.get_research_event", return_value=None)
    def test_missing_or_cross_asset_event_returns_404(self, _get_event):
        response = self.client.get(
            f"/api/assets/{self.asset_id}/research-events/2%3A10"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "研究事件不存在或不属于当前标的")

    def test_brief_rejects_non_24_hour_window_and_missing_asset(self):
        invalid_window = self.client.get(
            f"/api/assets/{self.asset_id}/research-brief?hours=48"
        )
        missing_asset = self.client.get("/api/assets/9999/research-brief?hours=24")

        self.assertEqual(invalid_window.status_code, 422)
        self.assertEqual(missing_asset.status_code, 404)


if __name__ == "__main__":
    unittest.main()
