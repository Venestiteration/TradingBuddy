"""资产管理、股票搜索、行情总览与投资判断接口。"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import database as db
from ..config import settings
from ..services.ai import IMPACT_LABELS
from ..services.events import collect_events
from ..services.market import MarketDataError, market_service, normalize_code

router = APIRouter(prefix="/api")


class AssetCreate(BaseModel):
    stock_code: str
    asset_type: str = Field(default="watchlist", pattern="^(watchlist|holding)$")
    quantity: Optional[float] = None
    cost_price: Optional[float] = None


class AssetUpdate(BaseModel):
    asset_type: Optional[str] = Field(default=None, pattern="^(watchlist|holding)$")
    quantity: Optional[float] = None
    cost_price: Optional[float] = None
    notifications_enabled: Optional[bool] = None


class ThesisCreate(BaseModel):
    core_thesis: str = Field(min_length=1, max_length=2000)
    watch_variables: str = Field(default="", max_length=2000)
    invalid_conditions: str = Field(default="", max_length=2000)


def _asset_row(asset_id: int) -> dict:
    asset = db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return asset


def _current_thesis(asset_id: int) -> dict | None:
    row = db.query_one(
        "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC LIMIT 1",
        (asset_id,),
    )
    return row


@router.get("/health")
def health() -> dict:
    configured = bool(settings.openai_api_key and settings.openai_model)
    return {
        "status": "ok",
        "app": "AI 投研助手 MVP",
        "openai_configured": configured,
        "openai_model": settings.openai_model or None,
        "openai_base_url": settings.openai_base_url or None,
        "database": str(settings.db_file),
        "time": db.utcnow(),
    }


@router.get("/stocks/search")
def search_stocks(q: str = "", limit: int = 10) -> dict:
    try:
        results = market_service.search(q, limit=max(1, min(limit, 20)))
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"results": results, "fetched_at": db.utcnow()}


@router.get("/assets")
def list_assets() -> dict:
    assets = db.query(
        "SELECT a.id, a.stock_code, a.stock_name, a.asset_type, a.quantity, a.cost_price, "
        "a.notifications_enabled, a.created_at, a.updated_at, "
        "t.version AS thesis_version, t.status AS thesis_status "
        "FROM assets a LEFT JOIN theses t "
        "ON t.asset_id = a.id AND t.version = "
        "(SELECT MAX(version) FROM theses WHERE asset_id = a.id) "
        "ORDER BY a.created_at"
    )
    return {"assets": assets, "fetched_at": db.utcnow()}


@router.post("/assets", status_code=201)
def create_asset(payload: AssetCreate) -> dict:
    try:
        code = normalize_code(payload.stock_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    existing = db.query_one("SELECT * FROM assets WHERE stock_code = ?", (code,))
    if existing:
        raise HTTPException(status_code=409, detail="该标的已在列表中")
    name = market_service.stock_name(code)
    now = db.utcnow()
    asset_id = db.execute(
        "INSERT INTO assets (stock_code, stock_name, asset_type, quantity, cost_price, "
        "notifications_enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (code, name, payload.asset_type, payload.quantity, payload.cost_price, now, now),
    )
    return db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: int, payload: AssetUpdate) -> dict:
    asset = _asset_row(asset_id)
    fields = {
        "asset_type": payload.asset_type,
        "quantity": payload.quantity,
        "cost_price": payload.cost_price,
        "notifications_enabled": (
            int(payload.notifications_enabled)
            if payload.notifications_enabled is not None
            else None
        ),
    }
    updates = {key: value for key, value in fields.items() if value is not None}
    if updates:
        updates["updated_at"] = db.utcnow()
        sets = ", ".join(f"{key} = ?" for key in updates)
        db.execute(
            f"UPDATE assets SET {sets} WHERE id = ?",
            (*updates.values(), asset_id),
        )
    return db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,)) or asset


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int) -> dict:
    _asset_row(asset_id)
    db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    return {"deleted": asset_id}


def _parse_analyses(rows: list[dict]) -> list[dict]:
    parsed = []
    for row in rows:
        try:
            result = json.loads(row["result"])
        except json.JSONDecodeError:
            continue
        parsed.append({
            **row,
            "result": result,
            "impact_label": IMPACT_LABELS.get(result.get("impact_state"), "信息不足"),
        })
    return parsed


def build_overview(asset: dict, use_cache: bool = True) -> dict:
    """组装单标的全量视图：行情、事件、判断、最近分析与对话。"""
    asset = dict(asset)
    code = asset["stock_code"]
    name = asset["stock_name"]
    errors: dict[str, str] = {}

    snapshot = None
    try:
        snapshot = market_service.snapshot(code, use_cache=use_cache)
        if snapshot.get("name") and snapshot["name"] != code:
            asset["stock_name"] = snapshot["name"]
            db.execute(
                "UPDATE assets SET stock_name = ?, updated_at = ? WHERE id = ?",
                (snapshot["name"], db.utcnow(), asset["id"]),
            )
            name = snapshot["name"]
    except MarketDataError as exc:
        errors["snapshot"] = str(exc)

    history = None
    try:
        history = market_service.history(code, use_cache=use_cache)
    except MarketDataError as exc:
        errors["history"] = str(exc)

    events_payload = {"events": [], "errors": [], "fetched_at": None}
    if snapshot is not None or history is not None:
        try:
            events_payload = collect_events(
                code, name, snapshot or {}, history or {"rows": []}, use_cache=use_cache
            )
        except Exception as exc:
            errors["events"] = f"事件获取失败: {exc.__class__.__name__}"
    else:
        errors["events"] = "行情不可用，事件未抓取"

    thesis = _current_thesis(asset["id"])
    analyses = _parse_analyses(db.query(
        "SELECT id, event_id, evidence_fingerprint, thesis_version, mode, model, "
        "validation, created_at, result FROM analyses "
        "WHERE asset_id = ? ORDER BY created_at DESC LIMIT 10",
        (asset["id"],),
    ))
    messages = db.query(
        "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
        "WHERE asset_id = ? ORDER BY created_at DESC LIMIT 50",
        (asset["id"],),
    )
    messages.reverse()

    return {
        "asset": asset,
        "snapshot": snapshot,
        "history": history,
        "events": events_payload.get("events", []),
        "event_errors": events_payload.get("errors", []),
        "latest_analysis": analyses[0] if analyses else None,
        "analyses": analyses,
        "thesis": thesis,
        "messages": messages,
        "errors": errors,
        "data_time": (history or {}).get("data_time"),
        "fetched_at": db.utcnow(),
        "stale": bool((snapshot or {}).get("stale") or (history or {}).get("stale")),
    }


@router.get("/assets/{asset_id}/overview")
def get_overview(asset_id: int) -> dict:
    asset = _asset_row(asset_id)
    return build_overview(asset)


@router.post("/assets/{asset_id}/refresh")
def refresh_overview(asset_id: int) -> dict:
    asset = _asset_row(asset_id)
    from ..services.market import _memory_cache  # 清空该标的的进程内缓存

    code = asset["stock_code"]
    for key in [k for k in list(_memory_cache) if code in k]:
        _memory_cache.pop(key, None)
    return build_overview(asset, use_cache=False)


@router.get("/assets/{asset_id}/theses")
def list_theses(asset_id: int) -> dict:
    _asset_row(asset_id)
    return {
        "current": _current_thesis(asset_id),
        "history": db.query(
            "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC",
            (asset_id,),
        ),
    }


@router.post("/assets/{asset_id}/theses", status_code=201)
def create_thesis(asset_id: int, payload: ThesisCreate) -> dict:
    _asset_row(asset_id)
    current = _current_thesis(asset_id)
    version = (current or {}).get("version", 0) + 1
    thesis_id = db.execute(
        "INSERT INTO theses (asset_id, version, core_thesis, watch_variables, "
        "invalid_conditions, status, created_at) VALUES (?, ?, ?, ?, ?, '已由你确认', ?)",
        (asset_id, version, payload.core_thesis.strip(),
         payload.watch_variables.strip(), payload.invalid_conditions.strip(), db.utcnow()),
    )
    return db.query_one("SELECT * FROM theses WHERE id = ?", (thesis_id,))
