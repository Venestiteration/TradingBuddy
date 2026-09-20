import sqlite3
import unittest

from app import database


class PublicDynamicsSchemaTest(unittest.TestCase):
    def test_schema_creates_public_dynamics_tables_and_indexes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        database.ensure_schema(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({
            "public_dynamics",
            "public_dynamic_evidence",
            "source_sync_state",
            "public_dynamics_sync_state",
            "document_cache",
        }.issubset(tables))

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(public_dynamics)")
        }
        self.assertTrue({
            "canonical_key",
            "importance_factors_json",
            "conflict_status",
        }.issubset(columns))

        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(public_dynamics)")
        }
        self.assertIn("idx_public_dynamics_asset_time", indexes)


if __name__ == "__main__":
    unittest.main()
