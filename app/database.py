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

CREATE TABLE IF NOT EXISTS importance_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    signal_date TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('public', 'upstream', 'market', 'cross_asset')),
    direction TEXT NOT NULL DEFAULT 'unknown'
        CHECK (direction IN ('positive', 'negative', 'mixed', 'neutral', 'unknown')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    factor_scores_json TEXT NOT NULL DEFAULT '{}',
    raw_score REAL NOT NULL,
    score REAL NOT NULL,
    calibrated_confidence REAL,
    formula_version TEXT NOT NULL DEFAULT 'importance-v1',
    source_status TEXT NOT NULL DEFAULT 'fresh'
        CHECK (source_status IN ('fresh', 'cached', 'decayed', 'baseline')),
    origin_signal_id INTEGER REFERENCES importance_signals(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS importance_signal_evidence (
    signal_id INTEGER NOT NULL REFERENCES importance_signals(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    PRIMARY KEY (signal_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS importance_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    score_date TEXT NOT NULL,
    public_score REAL NOT NULL,
    upstream_score REAL NOT NULL,
    market_score REAL,
    cross_asset_score REAL NOT NULL,
    composite_score REAL,
    dominant_category TEXT,
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete', 'cached')),
    formula_version TEXT NOT NULL DEFAULT 'importance-v1',
    details_json TEXT NOT NULL DEFAULT '{}',
    calculated_at TEXT NOT NULL,
    UNIQUE (asset_id, score_date, formula_version)
);

CREATE TABLE IF NOT EXISTS thesis_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL DEFAULT 0,
    selected_message_ids_json TEXT NOT NULL DEFAULT '[]',
    selected_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    ai_suggestion_json TEXT NOT NULL DEFAULT '{}',
    user_content_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'confirmed', 'discarded')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_thesis_id INTEGER REFERENCES theses(id)
);

CREATE TABLE IF NOT EXISTS public_dynamics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('announcement', 'news')),
    category TEXT NOT NULL,
    canonical_title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    importance_score REAL NOT NULL,
    importance_factors_json TEXT NOT NULL DEFAULT '{}',
    formula_version TEXT NOT NULL DEFAULT 'public-dynamics-v1',
    content_status TEXT NOT NULL DEFAULT 'title_only'
        CHECK (content_status IN ('title_only', 'excerpt', 'full')),
    conflict_status TEXT NOT NULL DEFAULT 'none'
        CHECK (conflict_status IN ('none', 'possible')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (asset_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS public_dynamic_evidence (
    dynamic_id INTEGER NOT NULL REFERENCES public_dynamics(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK (relation IN ('primary', 'corroborating', 'related')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (dynamic_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS source_sync_state (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL,
    last_success_at TEXT,
    last_status TEXT NOT NULL CHECK (last_status IN ('success', 'empty', 'failed')),
    last_error_code TEXT,
    last_error_message TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, provider)
);

CREATE TABLE IF NOT EXISTS public_dynamics_sync_state (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    last_attempt_at TEXT NOT NULL,
    last_complete_at TEXT,
    last_status TEXT NOT NULL CHECK (last_status IN ('complete', 'partial', 'failed')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_cache (
    evidence_id TEXT PRIMARY KEY REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    document_url TEXT NOT NULL,
    document_hash TEXT,
    mime_type TEXT,
    byte_size INTEGER,
    extraction_status TEXT NOT NULL
        CHECK (extraction_status IN ('pending', 'extracted', 'unsupported', 'failed')),
    extracted_text TEXT NOT NULL DEFAULT '',
    extracted_at TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_importance_signal_asset_date
    ON importance_signals(asset_id, signal_date, category);
CREATE INDEX IF NOT EXISTS idx_importance_daily_asset_date
    ON importance_daily(asset_id, score_date);
CREATE INDEX IF NOT EXISTS idx_thesis_draft_asset_status
    ON thesis_drafts(asset_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_public_dynamics_asset_time
    ON public_dynamics(asset_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_dynamic_evidence_evidence
    ON public_dynamic_evidence(evidence_id);
CREATE INDEX IF NOT EXISTS idx_source_sync_state_asset
    ON source_sync_state(asset_id, provider);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


THESIS_COLUMNS = {
    "change_summary_json": "TEXT NOT NULL DEFAULT '{}'",
    "source_message_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "source_evidence_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "creation_method": "TEXT NOT NULL DEFAULT 'manual'",
    "base_version": "INTEGER",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """创建新表并为旧版 theses 表补充字段，重复执行安全。"""
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(theses)")}
    for column, definition in THESIS_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE theses ADD COLUMN {column} {definition}")


_schema_ready = False


@contextmanager
def get_conn():
    global _schema_ready
    settings.prepare()
    conn = sqlite3.connect(settings.db_file, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not _schema_ready:
        ensure_schema(conn)
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
        ensure_schema(conn)


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
