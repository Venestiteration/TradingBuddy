import sqlite3
import unittest

from app import database


class DatabaseSchemaTest(unittest.TestCase):
    def test_existing_theses_table_is_extended_without_losing_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE assets (id INTEGER PRIMARY KEY, stock_code TEXT, stock_name TEXT, "
            "asset_type TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE theses (id INTEGER PRIMARY KEY, asset_id INTEGER, version INTEGER, "
            "core_thesis TEXT, watch_variables TEXT, invalid_conditions TEXT, status TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO theses VALUES (1, 7, 1, '原判断', '收入', '需求下降', '已由你确认', '2026-09-01')"
        )

        database.ensure_schema(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(theses)")}
        self.assertTrue({
            "change_summary_json", "source_message_ids_json", "source_evidence_ids_json",
            "creation_method", "base_version",
        }.issubset(columns))
        self.assertEqual(conn.execute("SELECT core_thesis FROM theses").fetchone()[0], "原判断")
        self.assertIsNotNone(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='importance_daily'"
        ).fetchone())
        self.assertIsNotNone(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thesis_drafts'"
        ).fetchone())


if __name__ == "__main__":
    unittest.main()
