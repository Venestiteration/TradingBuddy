"""用户判断草稿：浏览、编辑并确认草稿；浏览器本地模式暂不支持 AI 生成。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import database as db
from ..services.thesis_draft import (
    confirm_draft,
    default_context,
    serialize_draft,
    validate_selection,
)
from .assets import _asset_row

router = APIRouter(prefix="/api/assets/{asset_id}")


class DraftGenerateRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class DraftUpdateRequest(BaseModel):
    message_ids: list[int] = Field(default_factory=list, max_length=50)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    user_content: dict


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


@router.post("/thesis-drafts/generate", status_code=410)
def generate_thesis_draft(asset_id: int, payload: DraftGenerateRequest) -> None:
    _asset_row(asset_id)
    raise HTTPException(
        status_code=410,
        detail="AI 判断草稿暂不支持浏览器本地模式；可继续查看数据和来源。",
    )


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
