from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from .. import database as db
from ..services.research_brief import build_research_brief
from ..services.research_events import get_research_event
from .assets import _asset_row


router = APIRouter(prefix="/api")


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
