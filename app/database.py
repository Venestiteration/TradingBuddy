"""SQLite 访问层：建表、查询与 kv 缓存。单进程单用户，WAL 模式。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL UNIQUE,
    stock_name TEXT NOT NULL,
    asset_type TEXT NOT NULL DEFAULT 'watchlist'
        CHECK (asset_type IN ('watchlist', 'holding')),
    quantity REAL,
    cost_price REAL,
    notifications_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS theses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    core_thesis TEXT NOT NULL,
    watch_variables TEXT NOT NULL DEFAULT '',
    invalid_conditions TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '已由你确认',
    created_at TEXT NOT NULL,
    UNIQUE (asset_id, version)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    stock_code TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_level TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    content_status TEXT NOT NULL DEFAULT 'excerpt',
    raw TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    event_id TEXT,
    evidence_fingerprint TEXT NOT NULL DEFAULT '',
    thesis_version INTEGER,
    mode TEXT NOT NULL DEFAULT 'research',
    model TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL,
    validation TEXT NOT NULL DEFAULT 'passed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    event_id TEXT,
    analysis_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_theses_asset ON theses(asset_id, version);
CREATE INDEX IF NOT EXISTS idx_analyses_asset ON analyses(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_asset ON messages(asset_id, created_at);
CREATE INDEX IF NOT EXISTS idx_evidence_stock ON evidence(stock_code);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


_schema_ready = False


@contextmanager
def get_conn():
    global _schema_ready
    settings.prepare()
    conn = sqlite3.connect(settings.db_file, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not _schema_ready:
        conn.executescript(SCHEMA)
        _schema_ready = True
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings.prepare()
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with get_conn() as conn:
        cursor = conn.execute(sql, params)
        return cursor.lastrowid


def kv_get(key: str, max_age_seconds: float | None = None) -> dict | None:
    """读取 kv 缓存。max_age_seconds 超期返回 None，但不删除（作为降级数据仍可用）。"""
    row = query_one("SELECT value, fetched_at FROM kv WHERE key = ?", (key,))
    if not row:
        return None
    if max_age_seconds is not None:
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
            age = (datetime.now(timezone.utc).astimezone() - fetched).total_seconds()
            if age > max_age_seconds:
                return None
        except ValueError:
            return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return None


def kv_get_stale(key: str) -> dict | None:
    """读取 kv 缓存（允许过期），用于失败降级。"""
    return kv_get(key, max_age_seconds=None)


def kv_set(key: str, value: dict | list) -> None:
    execute(
        "INSERT INTO kv (key, value, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at",
        (key, json.dumps(value, ensure_ascii=False), utcnow()),
    )
