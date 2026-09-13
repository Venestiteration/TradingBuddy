"""研究重要性时间线与可解释详情接口。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from .. import database as db
from ..services.importance import CATEGORIES, FACTOR_WEIGHTS, FORMULA_VERSION, daily_scores, decay_score
from ..services.market import MarketDataError, market_service
from ..services.signals import build_evidence_signals, build_market_signals
from .assets import _asset_row

router = APIRouter(prefix="/api")


def assemble_daily_rows(
    trading_dates: list[str], signals: list[dict], cached: bool = False
) -> list[dict]:
    by_date: dict[str, dict[str, list[dict]]] = {}
    for signal in signals:
        by_date.setdefault(signal["signal_date"], {}).setdefault(signal["category"], []).append(signal)
    last_valid: dict[str, tuple[int, dict] | None] = {
        "public": None, "upstream": None, "cross_asset": None,
    }
    rows: list[dict] = []
    for index, score_date in enumerate(trading_dates):
        raw: dict[str, float | None] = {}
        category_status: dict[str, str] = {}
        category_signal: dict[str, dict | None] = {}
        for category in CATEGORIES:
            candidates = by_date.get(score_date, {}).get(category, [])
            selected = max(candidates, key=lambda item: item["raw_score"]) if candidates else None
            if selected:
                raw[category] = float(selected["raw_score"])
                category_status[category] = selected.get("source_status", "fresh")
                category_signal[category] = selected
                if category != "market":
                    last_valid[category] = (index, selected)
            elif category == "market":
                raw[category] = None
                category_status[category] = "missing"
                category_signal[category] = None
            elif last_valid[category]:
                origin_index, origin = last_valid[category]
                raw[category] = decay_score(float(origin["raw_score"]), index - origin_index, category)
                category_status[category] = "decayed"
                category_signal[category] = origin
            else:
                raw[category] = 0.0
                category_status[category] = "baseline"
                category_signal[category] = None
        summary = daily_scores(raw, cached=cached)
        dominant = summary["dominant_category"]
        lead = category_signal.get(dominant) if dominant else None
        rows.append({
            "date": score_date,
            "raw_category_scores": raw,
            "category_scores": summary["category_scores"],
            "category_status": category_status,
            "category_signal": category_signal,
            "composite_score": summary["composite_score"],
            "preview_score": summary["preview_score"],
            "dominant_category": dominant,
            "status": summary["status"],
            "summary": (lead or {}).get("summary") or "暂无新信息",
            "formula_version": FORMULA_VERSION,
        })
    return rows


def _source_rows(stock_code: str, first_date: str) -> list[dict]:
    rows = db.query(
        "SELECT * FROM evidence WHERE stock_code = ? AND "
        "substr(COALESCE(published_at, fetched_at), 1, 10) >= ? ORDER BY published_at",
        (stock_code, first_date),
    )
    for row in rows:
        try:
            row["raw"] = json.loads(row.get("raw") or "{}")
        except json.JSONDecodeError:
            row["raw"] = {}
    return rows


def _persist_signals(asset_id: int, signals: list[dict]) -> None:
    if not signals:
        return
    first_date = min(item["signal_date"] for item in signals)
    with db.get_conn() as conn:
        conn.execute(
            "DELETE FROM importance_signals WHERE asset_id = ? AND formula_version = ? AND signal_date >= ?",
            (asset_id, FORMULA_VERSION, first_date),
        )
        for signal in signals:
            cursor = conn.execute(
                "INSERT INTO importance_signals (asset_id, signal_date, category, direction, title, summary, "
                "factor_scores_json, raw_score, score, formula_version, source_status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (asset_id, signal["signal_date"], signal["category"], signal["direction"],
                 signal["title"], signal["summary"],
                 json.dumps(signal["factor_scores"], ensure_ascii=False), signal["raw_score"],
                 signal["score"], FORMULA_VERSION, signal["source_status"], db.utcnow()),
            )
            signal["id"] = cursor.lastrowid
            for evidence_id in signal.get("evidence_ids", []):
                conn.execute(
                    "INSERT OR IGNORE INTO importance_signal_evidence (signal_id, evidence_id) VALUES (?, ?)",
                    (cursor.lastrowid, evidence_id),
                )


def _persist_daily(asset_id: int, rows: list[dict]) -> None:
    with db.get_conn() as conn:
        for row in rows:
            scores = row["category_scores"]
            details = {
                "raw_category_scores": row["raw_category_scores"],
                "category_status": row["category_status"],
                "category_signal_ids": {
                    key: (value or {}).get("id") for key, value in row["category_signal"].items()
                },
                "summary": row["summary"],
                "preview_score": row["preview_score"],
            }
            conn.execute(
                "INSERT INTO importance_daily (asset_id, score_date, public_score, upstream_score, "
                "market_score, cross_asset_score, composite_score, dominant_category, status, "
                "formula_version, details_json, calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(asset_id, score_date, formula_version) DO UPDATE SET "
                "public_score=excluded.public_score, upstream_score=excluded.upstream_score, "
                "market_score=excluded.market_score, cross_asset_score=excluded.cross_asset_score, "
                "composite_score=excluded.composite_score, dominant_category=excluded.dominant_category, "
                "status=excluded.status, details_json=excluded.details_json, calculated_at=excluded.calculated_at",
                (asset_id, row["date"], scores["public"], scores["upstream"], scores["market"],
                 scores["cross_asset"], row["composite_score"], row["dominant_category"], row["status"],
                 FORMULA_VERSION, json.dumps(details, ensure_ascii=False), db.utcnow()),
            )


def _load_cached(asset_id: int, days: int) -> list[dict]:
    rows = db.query(
        "SELECT * FROM importance_daily WHERE asset_id = ? AND formula_version = ? "
        "ORDER BY score_date DESC LIMIT ?", (asset_id, FORMULA_VERSION, days),
    )
    output = []
    for row in reversed(rows):
        details = json.loads(row["details_json"] or "{}")
        output.append({
            "date": row["score_date"],
            "category_scores": {
                "public": row["public_score"], "upstream": row["upstream_score"],
                "market": row["market_score"], "cross_asset": row["cross_asset_score"],
            },
            "raw_category_scores": details.get("raw_category_scores", {}),
            "category_status": details.get("category_status", {}),
            "composite_score": row["composite_score"],
            "preview_score": details.get("preview_score"),
            "dominant_category": row["dominant_category"],
            "status": row["status"],
            "summary": details.get("summary", "暂无新信息"),
            "formula_version": row["formula_version"],
        })
    return output


def build_timeline(asset: dict, days: int, force: bool = False) -> list[dict]:
    if not force:
        cached = _load_cached(asset["id"], days)
        if len(cached) >= days:
            return cached[-days:]
    history = market_service.history(asset["stock_code"], use_cache=not force)
    rows = history.get("rows") or []
    trading_rows = rows[-max(days, 22):]
    if not trading_rows:
        raise MarketDataError("没有可用于重要性时间线的行情数据")
    first_date = str(trading_rows[0]["date"])[:10]
    evidence_rows = _source_rows(asset["stock_code"], first_date)
    signals = build_market_signals(trading_rows)
    if history.get("stale"):
        for signal in signals:
            signal["source_status"] = "cached"
    signals.extend(build_evidence_signals(
        evidence_rows, asset["stock_code"], asset["stock_name"]
    ))
    _persist_signals(asset["id"], signals)
    daily = assemble_daily_rows(
        [str(row["date"])[:10] for row in trading_rows], signals, cached=bool(history.get("stale"))
    )
    _persist_daily(asset["id"], daily)
    return daily[-days:]


def _daily_row(asset_id: int, score_date: str) -> tuple[dict, dict]:
    row = db.query_one(
        "SELECT * FROM importance_daily WHERE asset_id = ? AND score_date = ? "
        "AND formula_version = ?", (asset_id, score_date, FORMULA_VERSION),
    )
    if not row:
        raise HTTPException(status_code=404, detail="该日期没有重要性数据")
    try:
        details = json.loads(row["details_json"] or "{}")
    except json.JSONDecodeError:
        details = {}
    return row, details


def _signal_payload(signal: dict) -> dict:
    try:
        factor_scores = json.loads(signal.get("factor_scores_json") or "{}")
    except json.JSONDecodeError:
        factor_scores = {}
    evidence = db.query(
        "SELECT e.* FROM evidence e JOIN importance_signal_evidence link "
        "ON link.evidence_id = e.evidence_id WHERE link.signal_id = ? ORDER BY e.published_at DESC",
        (signal["id"],),
    )
    for item in evidence:
        try:
            item["raw"] = json.loads(item.get("raw") or "{}")
        except json.JSONDecodeError:
            item["raw"] = {}
    return {
        "id": signal["id"], "signal_date": signal["signal_date"],
        "category": signal["category"], "direction": signal["direction"],
        "title": signal["title"], "summary": signal["summary"],
        "raw_score": signal["raw_score"], "score": signal["score"],
        "source_status": signal["source_status"],
        "formula_version": signal["formula_version"],
        "factor_scores": factor_scores, "evidence": evidence,
    }


@router.get("/assets/{asset_id}/importance")
def importance_timeline(asset_id: int, days: int = Query(30, ge=1, le=90)) -> dict:
    asset = _asset_row(asset_id)
    try:
        rows = build_timeline(asset, days)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"rows": rows, "formula_version": FORMULA_VERSION, "fetched_at": db.utcnow()}


@router.post("/assets/{asset_id}/importance/recalculate")
def recalculate_importance(asset_id: int, days: int = Query(30, ge=1, le=90)) -> dict:
    asset = _asset_row(asset_id)
    try:
        rows = build_timeline(asset, days, force=True)
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"rows": rows, "formula_version": FORMULA_VERSION, "fetched_at": db.utcnow()}


@router.get("/assets/{asset_id}/importance/{score_date}")
def daily_importance(asset_id: int, score_date: str) -> dict:
    _asset_row(asset_id)
    row, details = _daily_row(asset_id, score_date)
    signal_ids = [value for value in details.get("category_signal_ids", {}).values() if value]
    signals = []
    if signal_ids:
        marks = ",".join("?" for _ in signal_ids)
        signals = db.query(
            f"SELECT * FROM importance_signals WHERE id IN ({marks}) ORDER BY score DESC",
            tuple(signal_ids),
        )
    categories = []
    for category in CATEGORIES:
        signal = next((item for item in signals if item["category"] == category), None)
        categories.append({
            "category": category,
            "score": row[f"{category}_score"],
            "status": details.get("category_status", {}).get(category, "baseline"),
            "summary": (signal or {}).get("summary") or "暂无新信息",
            "signal_id": (signal or {}).get("id"),
        })
    return {
        "date": row["score_date"], "composite_score": row["composite_score"],
        "status": row["status"], "dominant_category": row["dominant_category"],
        "categories": categories,
        "signals": [_signal_payload(signal) for signal in signals],
        "formula_version": row["formula_version"],
    }


@router.get("/assets/{asset_id}/importance/{score_date}/{category}")
def category_importance(asset_id: int, score_date: str, category: str) -> dict:
    _asset_row(asset_id)
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="不支持的评分类别")
    row, details = _daily_row(asset_id, score_date)
    signal_id = details.get("category_signal_ids", {}).get(category)
    signal = db.query_one("SELECT * FROM importance_signals WHERE id = ?", (signal_id,)) if signal_id else None
    payload = _signal_payload(signal) if signal else None
    factor_scores = (payload or {}).get("factor_scores", {})
    factors = {}
    for name, weight in FACTOR_WEIGHTS[category].items():
        score = factor_scores.get("factors", {}).get(name)
        contribution = factor_scores.get("contributions", {}).get(name, 0.0)
        factors[name] = {
            "score": score, "weight": weight, "contribution": contribution,
        }
    evidence = (payload or {}).get("evidence", [])
    return {
        "date": row["score_date"], "category": category,
        "score": row[f"{category}_score"],
        "status": details.get("category_status", {}).get(category, "baseline"),
        "formula_version": row["formula_version"], "factors": factors,
        "signal": payload, "evidence": evidence,
        "origin_date": (payload or {}).get("signal_date"),
    }
