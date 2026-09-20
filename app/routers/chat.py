"""连续追问：在当前标的与证据范围内回答用户问题（SSE）。"""
from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..services.ai import run_grounded_stream
from ..services.evidence import get_evidence, public_evidence
from ..services.visitor_ai import VisitorAIConfig, visitor_ai_config
from .assets import _asset_row, _current_thesis
from .research import _sse_response

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    asset_id: int
    question: str = Field(min_length=1, max_length=2000)
    event_id: Optional[str] = None
    recent_messages: list[ChatMessage] = Field(default_factory=list, max_length=6)


@router.get("/evidence/{evidence_id}")
def evidence_detail(evidence_id: str) -> dict:
    evidence = get_evidence(evidence_id)
    if not evidence:
        raise HTTPException(status_code=404, detail="证据不存在")
    return {"evidence": public_evidence(evidence), "fetched_at": db.utcnow()}


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    config: Annotated[VisitorAIConfig, Depends(visitor_ai_config)],
) -> StreamingResponse:
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

    snapshot = None
    try:
        from ..services.market import market_service

        snapshot = market_service.snapshot(asset["stock_code"])
    except Exception:
        pass

    generator = run_grounded_stream(
        config=config,
        mode="chat",
        asset=dict(asset),
        question=question,
        event=selected_event,
        evidence_items=evidence_items,
        thesis=thesis,
        recent_messages=[item.model_dump() for item in payload.recent_messages],
        snapshot=snapshot,
    )
    return _sse_response(generator)
