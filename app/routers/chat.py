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
from .assets import _asset_row
from .research import _build_route_context, _sse_response

router = APIRouter(prefix="/api")


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    asset_id: int
    question: str = Field(min_length=1, max_length=2000)
    cluster_id: Optional[str] = Field(default=None, max_length=80)
    event_id: Optional[str] = Field(default=None, max_length=160)
    dynamic_id: Optional[int] = None
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
    asset = dict(_asset_row(payload.asset_id))
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    context, _daily_brief, selected_event = _build_route_context(
        asset,
        question,
        cluster_id=payload.cluster_id,
        dynamic_id=payload.dynamic_id,
        event_id=payload.event_id,
        recent_messages=[item.model_dump() for item in payload.recent_messages],
    )
    conflict_status = str((selected_event or {}).get("conflict_status") or "none")

    generator = run_grounded_stream(
        config=config,
        mode="chat",
        context=context,
        conflict_status=conflict_status,
    )
    return _sse_response(generator)
