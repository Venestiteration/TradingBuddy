"""首轮研究分析：对选中事件生成结构化分析（SSE）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.ai import run_grounded_stream
from ..services.evidence import get_evidence
from ..services.public_dynamics import get_public_dynamic
from ..services.research_brief import build_research_brief
from ..services.research_context import select_research_context
from ..services.research_events import build_research_events, get_research_event
from ..services.visitor_ai import VisitorAIConfig, visitor_ai_config
from .assets import _asset_row, _current_thesis

router = APIRouter(prefix="/api")


class ResearchRequest(BaseModel):
    asset_id: int
    cluster_id: Optional[str] = Field(default=None, max_length=80)
    event_id: Optional[str] = Field(default=None, max_length=160)
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


def _context_window() -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=90), end


def _cluster_event(asset: dict, cluster_id: str) -> dict:
    start, end = _context_window()
    event = get_research_event(asset["id"], cluster_id, start, end)
    if event is None:
        raise HTTPException(
            status_code=404, detail="研究事件不存在或不属于当前标的"
        )
    return event


def _dynamic_event(asset: dict, dynamic_id: int) -> dict:
    dynamic = get_public_dynamic(dynamic_id)
    if (
        not dynamic
        or dynamic["asset_id"] != asset["id"]
        or not dynamic["evidence"]
    ):
        raise HTTPException(status_code=404, detail="公开动态不存在或不属于当前标的")
    evidence_items = dynamic["evidence"]
    lead = evidence_items[0]
    return {
        "event_id": lead["evidence_id"],
        "title": dynamic["canonical_title"],
        "summary": dynamic.get("summary"),
        "published_at": dynamic["published_at"],
        "source_type": lead["source_type"],
        "category": dynamic.get("category"),
        "conflict_status": dynamic["conflict_status"],
        "evidence": evidence_items,
    }


def _evidence_event(asset: dict, event_id: str) -> dict:
    evidence = get_evidence(event_id)
    if not evidence or evidence["stock_code"] != asset["stock_code"]:
        raise HTTPException(status_code=404, detail="事件不存在或不属于当前标的")
    return {
        "event_id": evidence["evidence_id"],
        "title": evidence["title"],
        "summary": evidence.get("excerpt"),
        "published_at": evidence["published_at"],
        "source_type": evidence["source_type"],
        "conflict_status": "none",
        "evidence": [evidence],
    }


def _selected_event(
    asset: dict,
    daily_brief: dict,
    *,
    cluster_id: str | None,
    dynamic_id: int | None,
    event_id: str | None,
) -> dict | None:
    if cluster_id is not None:
        return _cluster_event(asset, cluster_id)
    if dynamic_id is not None:
        return _dynamic_event(asset, dynamic_id)
    if event_id is not None:
        return _evidence_event(asset, event_id)
    headline = daily_brief.get("headline")
    if not isinstance(headline, dict) or not headline.get("cluster_id"):
        return None
    start, end = _context_window()
    return get_research_event(asset["id"], headline["cluster_id"], start, end)


def _market_snapshot(asset: dict) -> dict | None:
    try:
        from ..services.market import market_service

        return market_service.snapshot(asset["stock_code"])
    except Exception:
        return None


def _background_evidence(asset_id: int) -> list[dict]:
    start, end = _context_window()
    return [
        evidence
        for event in build_research_events(asset_id, start, end)
        for evidence in event.get("evidence", [])
    ]


def _resolve_route_selection(
    asset: dict,
    *,
    cluster_id: str | None = None,
    dynamic_id: int | None = None,
    event_id: str | None = None,
) -> tuple[dict, dict | None]:
    daily_brief = build_research_brief(asset, hours=24)
    selected_event = _selected_event(
        asset,
        daily_brief,
        cluster_id=cluster_id,
        dynamic_id=dynamic_id,
        event_id=event_id,
    )
    return daily_brief, selected_event


def _select_route_context(
    asset: dict,
    question: str,
    daily_brief: dict,
    selected_event: dict | None,
    recent_messages: list[dict] | None = None,
) -> dict:
    context = select_research_context(
        asset=asset,
        question=question,
        snapshot=_market_snapshot(asset),
        selected_event=selected_event,
        daily_brief=daily_brief,
        evidence_items=_background_evidence(asset["id"]),
        thesis=_current_thesis(asset["id"]),
        recent_messages=list(recent_messages or []),
    )
    if selected_event and selected_event.get("event_id"):
        context.setdefault("selected_event", {})["event_id"] = selected_event[
            "event_id"
        ]
    return context


def _build_route_context(
    asset: dict,
    question: str,
    *,
    cluster_id: str | None = None,
    dynamic_id: int | None = None,
    event_id: str | None = None,
    recent_messages: list[dict] | None = None,
) -> tuple[dict, dict, dict | None]:
    daily_brief, selected_event = _resolve_route_selection(
        asset,
        cluster_id=cluster_id,
        dynamic_id=dynamic_id,
        event_id=event_id,
    )
    context = _select_route_context(
        asset,
        question,
        daily_brief,
        selected_event,
        recent_messages,
    )
    return context, daily_brief, selected_event


@router.post("/research/stream")
def research_stream(
    payload: ResearchRequest,
    config: Annotated[VisitorAIConfig, Depends(visitor_ai_config)],
) -> StreamingResponse:
    asset = dict(_asset_row(payload.asset_id))
    daily_brief, selected_event = _resolve_route_selection(
        asset,
        cluster_id=payload.cluster_id,
        dynamic_id=payload.dynamic_id,
        event_id=payload.event_id,
    )
    title = selected_event["title"] if selected_event else "今日研究简报"
    question = f"请分析事件「{title}」对当前行情和用户判断的意义。"
    context = _select_route_context(
        asset,
        question,
        daily_brief,
        selected_event,
    )
    conflict_status = str((selected_event or {}).get("conflict_status") or "none")

    generator = run_grounded_stream(
        config=config,
        mode="research",
        context=context,
        conflict_status=conflict_status,
    )
    return _sse_response(generator)
