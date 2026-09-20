from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query

from .. import database as db
from ..services.document_text import DocumentRejected, extract_dynamic_document
from ..services.public_dynamics import (
    get_public_dynamic,
    list_public_dynamics,
    source_status,
)
from .assets import _asset_row

router = APIRouter(prefix="/api")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/assets/{asset_id}/public-dynamics")
def public_dynamics_feed(
    asset_id: int,
    hours: int = Query(24, ge=24, le=24),
    kind: Literal["all", "official", "media"] = "all",
) -> dict:
    _asset_row(asset_id)
    end = utcnow()
    start = end - timedelta(hours=hours)
    all_items = list_public_dynamics(asset_id, start, end, kind="all")
    official = [item for item in all_items if item["kind"] == "announcement"]
    media = [item for item in all_items if item["kind"] == "news"]
    selected = all_items if kind == "all" else official if kind == "official" else media
    return {
        "window_start": start.astimezone().isoformat(timespec="seconds"),
        "window_end": end.astimezone().isoformat(timespec="seconds"),
        "counts": {"all": len(all_items), "official": len(official), "media": len(media)},
        "items": selected,
        "source_status": source_status(asset_id),
    }


@router.get("/assets/{asset_id}/public-dynamics/source-status")
def public_dynamics_source_status(asset_id: int) -> dict:
    _asset_row(asset_id)
    return source_status(asset_id)


@router.get("/public-dynamics/{dynamic_id}")
def public_dynamic_detail(dynamic_id: int) -> dict:
    item = get_public_dynamic(dynamic_id)
    if not item:
        raise HTTPException(status_code=404, detail="公开动态不存在")
    return {"dynamic": item, "fetched_at": db.utcnow()}


@router.post("/public-dynamics/{dynamic_id}/extract")
def extract_public_dynamic(dynamic_id: int) -> dict:
    if not get_public_dynamic(dynamic_id):
        raise HTTPException(status_code=404, detail="公开动态不存在")
    try:
        return extract_dynamic_document(dynamic_id)
    except DocumentRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="公告正文暂时无法获取") from exc
