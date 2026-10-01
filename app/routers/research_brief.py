from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..services.ai import run_grounded_stream
from ..services.research_brief import build_research_brief
from ..services.research_events import get_research_event
from ..services.visitor_ai import VisitorAIConfig, visitor_ai_config
from .assets import _asset_row
from .research import _build_route_context, _sse_response


router = APIRouter(prefix="/api")


class ResearchBriefStreamRequest(BaseModel):
    asset_id: int
    cluster_id: Optional[str] = Field(default=None, max_length=80)
    question: Optional[str] = Field(default=None, max_length=2000)


@router.get("/assets/{asset_id}/research-brief")
def research_brief(asset_id: int, hours: int = Query(24, ge=24, le=24)) -> dict:
    return build_research_brief(_asset_row(asset_id), hours=hours)


@router.get("/assets/{asset_id}/research-events/{cluster_id}")
def research_event_detail(asset_id: int, cluster_id: str) -> dict:
    asset = _asset_row(asset_id)
    end = datetime.now(timezone.utc)
    event = get_research_event(
        asset["id"], cluster_id, end - timedelta(days=90), end
    )
    if event is None:
        raise HTTPException(
            status_code=404, detail="研究事件不存在或不属于当前标的"
        )
    return {"event": event, "fetched_at": db.utcnow()}


@router.post("/research-brief/stream")
def research_brief_stream(
    payload: ResearchBriefStreamRequest,
    config: Annotated[VisitorAIConfig, Depends(visitor_ai_config)],
) -> StreamingResponse:
    asset = dict(_asset_row(payload.asset_id))
    question = (payload.question or "").strip() or (
        "请解读今日研究简报的核心变化、影响路径与待验证事项。"
    )
    context, daily_brief, selected_event = _build_route_context(
        asset,
        question,
        cluster_id=payload.cluster_id,
    )
    if payload.cluster_id is not None:
        conflict_status = str(
            (selected_event or {}).get("conflict_status") or "none"
        )
    else:
        conflict_status = str(daily_brief.get("conflict_status") or "none")
    generator = run_grounded_stream(
        config=config,
        mode="daily",
        context=context,
        conflict_status=conflict_status,
    )
    return _sse_response(generator)
