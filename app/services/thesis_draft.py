"""把对话与证据整理成可审阅、可确认的判断草稿。"""
from __future__ import annotations

import json

from .. import database as db
from .ai import call_structured_model
from .visitor_ai import VisitorAIConfig

ALLOWED_CHANGE_TYPES = {"added", "modified", "removed", "unchanged"}

REFERENCE_PROPERTIES = {
    "change_type": {"type": "string", "enum": sorted(ALLOWED_CHANGE_TYPES)},
    "message_ids": {"type": "array", "items": {"type": "integer"}},
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
}

THESIS_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "base_version": {"type": "integer"},
        "core_thesis": {
            "type": "object",
            "properties": {
                **REFERENCE_PROPERTIES,
                "suggested_text": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["change_type", "suggested_text", "message_ids", "evidence_ids", "reason"],
            "additionalProperties": False,
        },
        "watch_variables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {**REFERENCE_PROPERTIES, "text": {"type": "string"}},
                "required": ["change_type", "text", "message_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "invalid_conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {**REFERENCE_PROPERTIES, "text": {"type": "string"}},
                "required": ["change_type", "text", "message_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["base_version", "core_thesis", "watch_variables", "invalid_conditions", "summary"],
    "additionalProperties": False,
}


def validate_suggestion(result: dict, message_ids: set[int], evidence_ids: set[str]) -> dict:
    """只保留输入上下文中存在的引用，避免模型臆造证据编号。"""
    if not isinstance(result, dict) or not isinstance(result.get("core_thesis"), dict):
        raise ValueError("AI 返回的判断草稿结构无效")
    core = result["core_thesis"]
    core["message_ids"] = [value for value in core.get("message_ids", []) if value in message_ids]
    core["evidence_ids"] = [value for value in core.get("evidence_ids", []) if value in evidence_ids]
    for field in ("watch_variables", "invalid_conditions"):
        cleaned = []
        for item in result.get(field, []):
            if not isinstance(item, dict) or item.get("change_type") not in ALLOWED_CHANGE_TYPES:
                continue
            item["message_ids"] = [value for value in item.get("message_ids", []) if value in message_ids]
            item["evidence_ids"] = [value for value in item.get("evidence_ids", []) if value in evidence_ids]
            item["insufficient_basis"] = not item["message_ids"] and not item["evidence_ids"]
            cleaned.append(item)
        result[field] = cleaned
    core["insufficient_basis"] = not core["message_ids"] and not core["evidence_ids"]
    return result


def generate_suggestion(
    config: VisitorAIConfig,
    base_version: int,
    thesis: dict | None,
    messages: list[dict],
    evidence: list[dict],
) -> dict:
    """让模型提出判断变化建议，但不允许它直接产生交易建议。"""
    result = call_structured_model(
        config,
        instructions=(
            "比较用户已确认判断与所选对话、证据，只整理对判断的新增、修改、删除或不变建议。"
            "不要提供买卖、仓位、目标价或交易时点建议。每项建议必须引用输入中的消息或证据编号。"
        ),
        context={
            "base_version": base_version,
            "current_thesis": thesis,
            "messages": messages,
            "evidence": evidence,
        },
        schema=THESIS_DRAFT_SCHEMA,
        schema_name="thesis_draft",
        max_tokens=2200,
    )
    try:
        returned_version = int(result.get("base_version", -1))
    except (TypeError, ValueError):
        returned_version = -1
    if returned_version != base_version:
        raise ValueError("AI 返回的判断基础版本不一致")
    core = result.get("core_thesis") or {}
    if core.get("change_type") not in ALLOWED_CHANGE_TYPES:
        raise ValueError("AI 返回了无效的判断变更类型")
    return validate_suggestion(
        result,
        {int(item["id"]) for item in messages},
        {str(item["evidence_id"]) for item in evidence},
    )


def _rows_for_ids(table: str, id_column: str, ids: list, where: str, params: tuple) -> list[dict]:
    """按固定内部调用方查询 ID；table/column 不接收用户原始字符串。"""
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return db.query(
        f"SELECT * FROM {table} WHERE {id_column} IN ({marks}) AND {where}",
        (*ids, *params),
    )


def _loads(value: str | None, default):
    try:
        return json.loads(value or json.dumps(default))
    except json.JSONDecodeError:
        return default


def default_context(asset_id: int) -> dict:
    asset = db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise LookupError("资产不存在")
    thesis = db.query_one(
        "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC LIMIT 1", (asset_id,)
    )
    if thesis:
        default_messages = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? AND created_at > ? ORDER BY created_at LIMIT 50",
            (asset_id, thesis["created_at"]),
        )
        remaining = max(0, 50 - len(default_messages))
        older = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? AND created_at <= ? ORDER BY created_at DESC LIMIT ?",
            (asset_id, thesis["created_at"], remaining),
        )
        older.reverse()
        messages = older + default_messages
    else:
        messages = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? ORDER BY created_at DESC LIMIT 50", (asset_id,),
        )
        messages.reverse()
        default_messages = messages[-20:]

    evidence_ids = {row["event_id"] for row in default_messages if row.get("event_id")}
    analysis_ids = [row["analysis_id"] for row in default_messages if row.get("analysis_id")]
    if analysis_ids:
        marks = ",".join("?" for _ in analysis_ids)
        analyses = db.query(
            f"SELECT event_id FROM analyses WHERE asset_id = ? AND id IN ({marks})",
            (asset_id, *analysis_ids),
        )
        evidence_ids.update(row["event_id"] for row in analyses if row.get("event_id"))

    evidence = db.query(
        "SELECT * FROM evidence WHERE stock_code = ? "
        "ORDER BY CASE source_level WHEN 'primary' THEN 0 ELSE 1 END, "
        "COALESCE(published_at, fetched_at) DESC LIMIT 30",
        (asset["stock_code"],),
    )
    draft = db.query_one(
        "SELECT * FROM thesis_drafts WHERE asset_id = ? AND status = 'draft' "
        "ORDER BY updated_at DESC LIMIT 1", (asset_id,),
    )
    if draft:
        draft["selected_message_ids"] = _loads(draft.get("selected_message_ids_json"), [])
        draft["selected_evidence_ids"] = _loads(draft.get("selected_evidence_ids_json"), [])
        draft["ai_suggestion"] = _loads(draft.get("ai_suggestion_json"), {})
        draft["user_content"] = _loads(draft.get("user_content_json"), {})

    default_message_ids = [row["id"] for row in default_messages]
    available_evidence_ids = {row["evidence_id"] for row in evidence}
    default_evidence_ids = [value for value in evidence_ids if value in available_evidence_ids][:30]
    return {
        "current_thesis": thesis,
        "base_version": int((thesis or {}).get("version", 0)),
        "messages": messages,
        "evidence": evidence[:30],
        "selected_message_ids": (draft or {}).get("selected_message_ids", default_message_ids),
        "selected_evidence_ids": (draft or {}).get("selected_evidence_ids", default_evidence_ids),
        "draft": draft,
    }


def validate_selection(asset_id: int, message_ids: list[int], evidence_ids: list[str]) -> dict:
    if len(message_ids) > 50 or len(evidence_ids) > 30:
        raise ValueError("最多选择 50 条消息和 30 条证据")
    if len(set(message_ids)) != len(message_ids) or len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("选择项不能重复")
    asset = db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise LookupError("资产不存在")
    messages = _rows_for_ids("messages", "id", message_ids, "asset_id = ?", (asset_id,))
    evidence = _rows_for_ids(
        "evidence", "evidence_id", evidence_ids, "stock_code = ?", (asset["stock_code"],)
    )
    if {row["id"] for row in messages} != set(message_ids):
        raise LookupError("所选消息不属于当前标的")
    if {row["evidence_id"] for row in evidence} != set(evidence_ids):
        raise LookupError("所选证据不属于当前标的")
    messages.sort(key=lambda row: row["created_at"])
    evidence.sort(key=lambda row: row.get("published_at") or row.get("fetched_at") or "")
    return {"messages": messages, "evidence": evidence}


def confirm_draft(conn, asset_id: int, draft_id: int) -> dict:
    draft_row = conn.execute(
        "SELECT * FROM thesis_drafts WHERE id = ? AND asset_id = ?", (draft_id, asset_id)
    ).fetchone()
    if not draft_row:
        raise ValueError("判断草稿不存在")
    draft = dict(draft_row)
    if draft["status"] == "confirmed" and draft["confirmed_thesis_id"]:
        thesis_row = conn.execute(
            "SELECT * FROM theses WHERE id = ?", (draft["confirmed_thesis_id"],)
        ).fetchone()
        if thesis_row:
            return dict(thesis_row)

    latest = conn.execute(
        "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC LIMIT 1", (asset_id,)
    ).fetchone()
    latest_version = int(latest["version"]) if latest else 0
    if latest_version != int(draft["base_version"]):
        raise RuntimeError("判断版本已更新，请基于最新版重新整理")

    content = _loads(draft.get("user_content_json"), {})
    core = str(content.get("core_thesis") or "").strip()
    if not core:
        raise ValueError("核心判断不能为空")
    now = db.utcnow()
    cursor = conn.execute(
        "INSERT INTO theses (asset_id, version, core_thesis, watch_variables, invalid_conditions, "
        "status, created_at, change_summary_json, source_message_ids_json, source_evidence_ids_json, "
        "creation_method, base_version) VALUES (?, ?, ?, ?, ?, '已由你确认', ?, ?, ?, ?, ?, ?)",
        (
            asset_id,
            latest_version + 1,
            core,
            str(content.get("watch_variables") or "").strip(),
            str(content.get("invalid_conditions") or "").strip(),
            now,
            json.dumps(content.get("change_summary") or {}, ensure_ascii=False),
            draft["selected_message_ids_json"],
            draft["selected_evidence_ids_json"],
            content.get("creation_method") or "ai_assisted",
            latest_version,
        ),
    )
    conn.execute(
        "UPDATE thesis_drafts SET status = 'confirmed', confirmed_thesis_id = ?, updated_at = ? WHERE id = ?",
        (cursor.lastrowid, now, draft_id),
    )
    return dict(conn.execute("SELECT * FROM theses WHERE id = ?", (cursor.lastrowid,)).fetchone())


def serialize_draft(row: dict | None) -> dict | None:
    if not row:
        return row
    result = dict(row)
    result["selected_message_ids"] = _loads(result.get("selected_message_ids_json"), [])
    result["selected_evidence_ids"] = _loads(result.get("selected_evidence_ids_json"), [])
    result["ai_suggestion"] = _loads(result.get("ai_suggestion_json"), {})
    result["user_content"] = _loads(result.get("user_content_json"), {})
    return result
