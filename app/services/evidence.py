"""证据对象：新闻、公告与行情事实统一为可引用、可核验的证据记录。"""
from __future__ import annotations

import hashlib
import json

from .. import database as db


def make_evidence_id(stock_code: str, title: str, source_url: str | None) -> str:
    basis = f"{stock_code}|{title}|{source_url or ''}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def make_evidence(
    stock_code: str,
    source_type: str,          # market / announcement / news
    source_level: str,         # primary / secondary
    title: str,
    excerpt: str = "",
    published_at: str | None = None,
    source_url: str | None = None,
    content_status: str = "excerpt",   # full / excerpt / title_only
    raw: dict | None = None,
) -> dict:
    title = (title or "").strip()
    excerpt = (excerpt or "").strip()
    if not title:
        raise ValueError("证据标题不能为空")
    if content_status != "title_only" and not excerpt:
        content_status = "title_only"
    return {
        "evidence_id": make_evidence_id(stock_code, title, source_url),
        "stock_code": stock_code,
        "source_type": source_type,
        "source_level": source_level,
        "title": title,
        "excerpt": excerpt[:600],
        "published_at": published_at,
        "source_url": source_url,
        "fetched_at": db.utcnow(),
        "content_status": content_status,
        "raw": raw or {},
    }


def save_evidence(evidence: dict) -> dict:
    db.execute(
        "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, title, "
        "excerpt, published_at, source_url, fetched_at, content_status, raw) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(evidence_id) DO UPDATE SET fetched_at = excluded.fetched_at",
        (
            evidence["evidence_id"], evidence["stock_code"], evidence["source_type"],
            evidence["source_level"], evidence["title"], evidence["excerpt"],
            evidence["published_at"], evidence["source_url"], evidence["fetched_at"],
            evidence["content_status"],
            json.dumps(evidence.get("raw", {}), ensure_ascii=False),
        ),
    )
    return evidence


def get_evidence(evidence_id: str) -> dict | None:
    row = db.query_one(
        "SELECT evidence_id, stock_code, source_type, source_level, title, excerpt, "
        "published_at, source_url, fetched_at, content_status, raw "
        "FROM evidence WHERE evidence_id = ?",
        (evidence_id,),
    )
    if not row:
        return None
    try:
        row["raw"] = json.loads(row.get("raw") or "{}")
    except json.JSONDecodeError:
        row["raw"] = {}
    return row


def public_evidence(evidence: dict) -> dict:
    """对外输出，剔除内部 raw 字段。"""
    return {key: value for key, value in evidence.items() if key != "raw"}
