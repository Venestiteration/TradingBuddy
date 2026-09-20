"""首轮研究分析：对选中事件生成结构化分析（SSE）。"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ai import run_grounded_stream
from ..services.evidence import get_evidence
from ..services.public_dynamics import dynamic_evidence
from ..services.visitor_ai import VisitorAIConfig, visitor_ai_config
from .assets import _asset_row, _current_thesis

router = APIRouter(prefix="/api")


class ResearchRequest(BaseModel):
    asset_id: int
    event_id: str = Field(min_length=1)
    dynamic_id: Optional[int] = None


def _sse_response(generator):
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/research/stream")
def research_stream(
    payload: ResearchRequest,
    config: Annotated[VisitorAIConfig, Depends(visitor_ai_config)],
) -> StreamingResponse:
    asset = _asset_row(payload.asset_id)
    if payload.dynamic_id is not None:
        evidence_items = dynamic_evidence(payload.dynamic_id, asset_id=asset["id"])
        if not evidence_items:
            raise HTTPException(status_code=404, detail="公开动态不存在或不属于当前标的")
        event_evidence = evidence_items[0]
    else:
        event_evidence = get_evidence(payload.event_id)
        if not event_evidence or event_evidence["stock_code"] != asset["stock_code"]:
            raise HTTPException(status_code=404, detail="事件不存在或不属于当前标的")
        evidence_items = [event_evidence]

    thesis = _current_thesis(asset["id"])
    # 行情上下文：允许失败（AI 仍可基于事件证据分析）
    snapshot = None
    try:
        from ..services.market import market_service

        snapshot = market_service.snapshot(asset["stock_code"])
    except Exception:
        pass

    generator = run_grounded_stream(
        config=config,
        mode="research",
        asset=dict(asset),
        question=f"请分析事件「{event_evidence['title']}」对当前行情和用户判断的意义。",
        event={
            "event_id": event_evidence["evidence_id"],
            "title": event_evidence["title"],
            "published_at": event_evidence["published_at"],
            "source_type": event_evidence["source_type"],
        },
        evidence_items=evidence_items,
        thesis=thesis,
        recent_messages=[],
        snapshot=snapshot,
    )
    return _sse_response(generator)
