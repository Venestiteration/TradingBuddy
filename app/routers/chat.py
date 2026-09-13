"""连续追问：在当前标的与证据范围内回答用户问题（SSE），并保存对话。"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..config import settings
from ..services.ai import run_grounded_stream
from ..services.evidence import get_evidence, public_evidence
from .assets import _asset_row, _current_thesis
from .research import _sse_response

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    asset_id: int
    question: str = Field(min_length=1, max_length=2000)
    event_id: Optional[str] = None


@router.get("/evidence/{evidence_id}")
def evidence_detail(evidence_id: str) -> dict:
    evidence = get_evidence(evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="证据不存在")
    return {"evidence": public_evidence(evidence), "fetched_at": db.utcnow()}


@router.get("/assets/{asset_id}/messages")
def list_messages(asset_id: int) -> dict:
    _asset_row(asset_id)
    messages = db.query(
        "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
        "WHERE asset_id = ? ORDER BY created_at DESC LIMIT 50",
        (asset_id,),
    )
    messages.reverse()
    return {"messages": messages, "fetched_at": db.utcnow()}


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    asset = _asset_row(payload.asset_id)
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    thesis = _current_thesis(asset["id"])

    # 证据范围：选中事件的证据 + 该标的最近 48 小时内的本地证据（失败降级时仍可追问）
    evidence_items = []
    selected_event = None
    if payload.event_id:
        selected = get_evidence(payload.event_id)
        if selected and selected["stock_code"] == asset["stock_code"]:
            selected_event = selected
            evidence_items.append(selected)
    extras = db.query(
        "SELECT evidence_id FROM evidence WHERE stock_code = ? AND fetched_at >= datetime('now', '-48 hours') "
        "ORDER BY fetched_at DESC LIMIT 12",
        (asset["stock_code"],),
    )
    seen = {item["evidence_id"] for item in evidence_items}
    for row in extras:
        if row["evidence_id"] not in seen:
            item = get_evidence(row["evidence_id"])
            if item:
                evidence_items.append(item)
            seen.add(row["evidence_id"])

    recent = db.query(
        "SELECT role, content FROM messages WHERE asset_id = ? ORDER BY created_at DESC LIMIT 6",
        (asset["id"],),
    )
    recent.reverse()

    snapshot = None
    try:
        from ..services.market import market_service

        snapshot = market_service.snapshot(asset["stock_code"])
    except Exception:
        pass

    def save_analysis(result: dict, fingerprint: str) -> int:
        return db.execute(
            "INSERT INTO analyses (asset_id, event_id, evidence_fingerprint, thesis_version, "
            "mode, model, result, validation, created_at) VALUES (?, ?, ?, ?, 'chat', ?, ?, ?, ?)",
            (
                asset["id"], (selected_event or {}).get("evidence_id"), fingerprint,
                (thesis or {}).get("version"), settings.openai_model, json.dumps(result, ensure_ascii=False),
                "passed", db.utcnow(),
            ),
        )

    def persist(role: str, content: str, analysis_id: int | None = None) -> None:
        db.execute(
            "INSERT INTO messages (asset_id, role, content, event_id, analysis_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (asset["id"], role, content, (selected_event or {}).get("evidence_id"),
             analysis_id, db.utcnow()),
        )

    def generator():
        persist("user", question)
        for chunk in run_grounded_stream(
            mode="chat",
            asset=dict(asset),
            question=question,
            event=selected_event,
            evidence_items=evidence_items,
            thesis=thesis,
            recent_messages=recent,
            snapshot=snapshot,
            save_result=save_analysis,
        ):
            event_name = chunk.split("\n", 1)[0].removeprefix("event: ").strip()
            data_line = chunk.split("data: ", 1)[1].rsplit("\n", 1)[0]
            body = json.loads(data_line)
            if event_name == "completed":
                persist("assistant", data_line, body.get("analysis_id"))
            yield chunk

    return _sse_response(generator())
