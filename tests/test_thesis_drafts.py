import json
import tempfile
import unittest
from pathlib import Path

from app import database as db
from app.services.thesis_draft import confirm_draft


class ThesisDraftTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = db.settings.database_path
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
            "INSERT INTO theses (asset_id, version, core_thesis, watch_variables, invalid_conditions, status, created_at) "
            "VALUES (?, 1, '原判断', '收入', '需求下降', '已由你确认', ?)", (self.asset_id, now),
        )
        self.draft_id = db.execute(
            "INSERT INTO thesis_drafts (asset_id, base_version, user_content_json, status, created_at, updated_at) "
            "VALUES (?, 1, ?, 'draft', ?, ?)",
            (
                self.asset_id,
                json.dumps({
                    "core_thesis": "新判断",
                    "watch_variables": "毛利率",
                    "invalid_conditions": "销量下降",
                    "change_summary": {"core_thesis": "modified"},
                    "creation_method": "ai_assisted",
                }, ensure_ascii=False),
                now,
                now,
            ),
        )

    def tearDown(self):
        db.settings.database_path = self.original_db
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def test_confirm_creates_one_new_version_and_is_idempotent(self):
        with db.get_conn() as conn:
            first = confirm_draft(conn, self.asset_id, self.draft_id)
        with db.get_conn() as conn:
            second = confirm_draft(conn, self.asset_id, self.draft_id)
        self.assertEqual(first["id"], second["id"])
        history = db.query(
            "SELECT version, core_thesis FROM theses WHERE asset_id = ? ORDER BY version",
            (self.asset_id,),
        )
        self.assertEqual(history, [
            {"version": 1, "core_thesis": "原判断"},
            {"version": 2, "core_thesis": "新判断"},
        ])


if __name__ == "__main__":
    unittest.main()
