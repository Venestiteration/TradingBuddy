"""用户判断草稿：从对话生成建议，用户确认后才创建不可变版本。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..services.ai import AIError
from ..services.thesis_draft import (
    confirm_draft,
    default_context,
    generate_suggestion,
    serialize_draft,
    validate_selection,
)
from .assets import _asset_row, _current_thesis
from .research import _sse_response

router = APIRouter(prefix="/api/assets/{asset_id}")


class DraftGenerateRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class DraftUpdateRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    user_content: dict


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/thesis-draft/context")
def thesis_context(asset_id: int) -> dict:
    _asset_row(asset_id)
    return default_context(asset_id)


@router.post("/thesis-drafts/{draft_id}/confirm")
def confirm_thesis_draft(asset_id: int, draft_id: int) -> dict:
    _asset_row(asset_id)
    try:
        with db.get_conn() as conn:
            thesis = confirm_draft(conn, asset_id, draft_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"thesis": thesis}


@router.post("/thesis-drafts/generate")
def generate_thesis_draft(asset_id: int, payload: DraftGenerateRequest) -> StreamingResponse:
    _asset_row(asset_id)
    try:
        selected = validate_selection(asset_id, payload.message_ids, payload.evidence_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    thesis = _current_thesis(asset_id)
    base_version = int((thesis or {}).get("version", 0))

    def events():
        yield _sse_event({"status": "context_ready"})
        try:
            yield _sse_event({"status": "model_running"})
            suggestion = generate_suggestion(
                base_version, thesis, selected["messages"], selected["evidence"]
            )
            yield _sse_event({"status": "validating"})
            current_content = {
                "core_thesis": (thesis or {}).get("core_thesis", ""),
                "watch_variables": (thesis or {}).get("watch_variables", ""),
                "invalid_conditions": (thesis or {}).get("invalid_conditions", ""),
                "change_summary": {},
                "creation_method": "ai_assisted",
            }
            now = db.utcnow()
            existing = db.query_one(
                "SELECT id FROM thesis_drafts WHERE asset_id = ? AND status = 'draft' "
                "ORDER BY updated_at DESC LIMIT 1", (asset_id,),
            )
            values = (
                base_version,
                json.dumps(payload.message_ids),
                json.dumps(payload.evidence_ids),
                json.dumps(suggestion, ensure_ascii=False),
                json.dumps(current_content, ensure_ascii=False),
                now,
            )
            if existing:
                db.execute(
                    "UPDATE thesis_drafts SET base_version = ?, selected_message_ids_json = ?, "
                    "selected_evidence_ids_json = ?, ai_suggestion_json = ?, user_content_json = ?, "
                    "updated_at = ? WHERE id = ?",
                    (*values, existing["id"]),
                )
                draft_id = existing["id"]
            else:
                draft_id = db.execute(
                    "INSERT INTO thesis_drafts (asset_id, base_version, selected_message_ids_json, "
                    "selected_evidence_ids_json, ai_suggestion_json, user_content_json, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
                    (
                        asset_id,
                        base_version,
                        json.dumps(payload.message_ids),
                        json.dumps(payload.evidence_ids),
                        json.dumps(suggestion, ensure_ascii=False),
                        json.dumps(current_content, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            draft = serialize_draft(db.query_one("SELECT * FROM thesis_drafts WHERE id = ?", (draft_id,)))
            yield _sse_event({"status": "completed", "draft": draft})
        except AIError as exc:
            yield _sse_event({"status": "failed", "category": exc.category, "message": str(exc)})
        except Exception as exc:
            yield _sse_event({"status": "failed", "category": "unknown", "message": str(exc)})

    return _sse_response(events())


@router.put("/thesis-drafts/{draft_id}")
def update_thesis_draft(asset_id: int, draft_id: int, payload: DraftUpdateRequest) -> dict:
    _asset_row(asset_id)
    try:
        validate_selection(asset_id, payload.message_ids, payload.evidence_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    draft = db.query_one(
        "SELECT * FROM thesis_drafts WHERE id = ? AND asset_id = ?", (draft_id, asset_id)
    )
    if not draft:
        raise HTTPException(status_code=404, detail="判断草稿不存在")
    if draft["status"] != "draft":
        raise HTTPException(status_code=409, detail="该判断草稿已经结束")
    core = str(payload.user_content.get("core_thesis") or "").strip()
    if len(core) > 2000:
        raise HTTPException(status_code=400, detail="核心判断不能超过 2000 字")
    db.execute(
        "UPDATE thesis_drafts SET selected_message_ids_json = ?, selected_evidence_ids_json = ?, "
        "user_content_json = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(payload.message_ids),
            json.dumps(payload.evidence_ids),
            json.dumps(payload.user_content, ensure_ascii=False),
            db.utcnow(),
            draft_id,
        ),
    )
    return {"draft": serialize_draft(db.query_one("SELECT * FROM thesis_drafts WHERE id = ?", (draft_id,)))}
