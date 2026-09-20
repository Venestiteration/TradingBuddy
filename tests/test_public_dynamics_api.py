import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import database as db
from app.main import create_app
from app.services.document_text import DocumentRejected
from app.services.public_dynamics import list_public_dynamics


class PublicDynamicsAPITest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        self.now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        timestamp = self.now.isoformat()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)",
            (timestamp, timestamp),
        )
        for index, (hours_ago, kind) in enumerate(((2, "announcement"), (12, "news"), (30, "news"))):
            published_at = (self.now - timedelta(hours=hours_ago)).isoformat()
            db.execute(
                "INSERT INTO public_dynamics (asset_id, canonical_key, kind, category, canonical_title, summary, "
                "published_at, importance_score, created_at, updated_at) "
                "VALUES (?, ?, ?, '测试', ?, '摘要', ?, 50, ?, ?)",
                (self.asset_id, f"dynamic-{index}", kind, f"动态 {index}", published_at, timestamp, timestamp),
            )
        db.execute(
            "INSERT INTO public_dynamics_sync_state (asset_id, last_attempt_at, last_complete_at, last_status, updated_at) "
            "VALUES (?, ?, ?, 'complete', ?)",
            (self.asset_id, timestamp, timestamp, timestamp),
        )
        self.dynamic_id = db.query_one(
            "SELECT id FROM public_dynamics ORDER BY id LIMIT 1"
        )["id"]
        self.client = TestClient(create_app())

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    @patch("app.routers.public_dynamics.utcnow")
    def test_feed_returns_complete_24_hour_window(self, mocked_utcnow):
        mocked_utcnow.return_value = self.now
        response = self.client.get(f"/api/assets/{self.asset_id}/public-dynamics?hours=24&kind=all")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["counts"], {"all": 2, "official": 1, "media": 1})
        self.assertEqual(len(body["items"]), 2)
        self.assertIn("window_start", body)
        self.assertIn("window_end", body)
        self.assertIn("source_status", body)
        self.assertEqual(body["source_status"]["status"], "complete")

    @patch("app.routers.public_dynamics.utcnow")
    def test_feed_filters_official_items(self, mocked_utcnow):
        mocked_utcnow.return_value = self.now
        response = self.client.get(f"/api/assets/{self.asset_id}/public-dynamics?kind=official")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["kind"], "announcement")

    def test_feed_rejects_unsupported_kind(self):
        response = self.client.get(f"/api/assets/{self.asset_id}/public-dynamics?kind=unsupported")
        self.assertEqual(response.status_code, 422)

    def test_source_status_and_missing_detail(self):
        status = self.client.get(f"/api/assets/{self.asset_id}/public-dynamics/source-status")
        missing = self.client.get("/api/public-dynamics/9999")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "complete")
        self.assertEqual(missing.status_code, 404)

    def test_daily_importance_exposes_recent_public_count(self):
        timestamp = db.utcnow()
        db.execute(
            "INSERT INTO public_dynamics (asset_id, canonical_key, kind, category, canonical_title, summary, "
            "published_at, importance_score, created_at, updated_at) "
            "VALUES (?, 'fresh-dynamic', 'news', '测试', '刚发布动态', '摘要', ?, 50, ?, ?)",
            (self.asset_id, timestamp, timestamp, timestamp),
        )
        db.execute(
            "INSERT INTO importance_daily (asset_id, score_date, public_score, upstream_score, market_score, "
            "cross_asset_score, composite_score, dominant_category, status, details_json, calculated_at) "
            "VALUES (?, '2026-09-21', 10, 10, 10, 10, 10, 'public', 'complete', '{}', ?)",
            (self.asset_id, timestamp),
        )

        response = self.client.get(f"/api/assets/{self.asset_id}/importance/2026-09-21")

        self.assertEqual(response.status_code, 200)
        categories = {item["category"]: item for item in response.json()["categories"]}
        now = datetime.now(timezone.utc)
        self.assertEqual(
            categories["public"]["recent_count_24h"],
            len(list_public_dynamics(self.asset_id, now - timedelta(hours=24), now)),
        )
        self.assertIsNone(categories["upstream"]["recent_count_24h"])

    @patch("app.routers.public_dynamics.extract_dynamic_document")
    def test_extract_endpoint_returns_cached_document_result(self, extract):
        extract.return_value = {
            "evidence_id": "evidence-1",
            "extraction_status": "extracted",
            "extracted_text": "announcement text",
        }

        response = self.client.post(
            f"/api/public-dynamics/{self.dynamic_id}/extract"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["extraction_status"], "extracted")
        extract.assert_called_once_with(self.dynamic_id)

    @patch("app.routers.public_dynamics.extract_dynamic_document")
    def test_extract_endpoint_returns_404_before_extraction(self, extract):
        response = self.client.post("/api/public-dynamics/9999/extract")

        self.assertEqual(response.status_code, 404)
        extract.assert_not_called()

    @patch("app.routers.public_dynamics.extract_dynamic_document")
    def test_extract_endpoint_maps_rejected_document_to_422(self, extract):
        extract.side_effect = DocumentRejected("公告地址不在允许列表中")

        response = self.client.post(
            f"/api/public-dynamics/{self.dynamic_id}/extract"
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "公告地址不在允许列表中")

    @patch("app.routers.public_dynamics.extract_dynamic_document")
    def test_extract_endpoint_maps_http_failure_to_generic_503(self, extract):
        extract.side_effect = httpx.HTTPError(
            "/Users/private/report.pdf SECRET_RESPONSE_BODY"
        )

        response = self.client.post(
            f"/api/public-dynamics/{self.dynamic_id}/extract"
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "公告正文暂时无法获取")


if __name__ == "__main__":
    unittest.main()
