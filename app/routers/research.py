"""首轮研究分析：对选中事件生成结构化分析（SSE）。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import database as db
from ..config import settings
from ..services.ai import run_grounded_stream
from ..services.evidence import get_evidence
from .assets import _asset_row, _current_thesis

router = APIRouter(prefix="/api")


class ResearchRequest(BaseModel):
    asset_id: int
    event_id: str = Field(min_length=1)


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
def research_stream(payload: ResearchRequest) -> StreamingResponse:
    asset = _asset_row(payload.asset_id)
    event_evidence = get_evidence(payload.event_id)
    if not event_evidence or event_evidence["stock_code"] != asset["stock_code"]:
        raise HTTPException(status_code=404, detail="事件不存在或不属于当前标的")

    thesis = _current_thesis(asset["id"])
    recent = db.query(
        "SELECT role, content FROM messages WHERE asset_id = ? ORDER BY created_at DESC LIMIT 6",
        (asset["id"],),
    )
    recent.reverse()

    # 行情上下文：允许失败（AI 仍可基于事件证据分析）
    snapshot = None
    try:
        from ..services.market import market_service

        snapshot = market_service.snapshot(asset["stock_code"])
    except Exception:
        pass

    def save_result(result: dict, fingerprint: str) -> int:
        return db.execute(
            "INSERT INTO analyses (asset_id, event_id, evidence_fingerprint, thesis_version, "
            "mode, model, result, validation, created_at) VALUES (?, ?, ?, ?, 'research', ?, ?, ?, ?)",
            (
                asset["id"], payload.event_id, fingerprint,
                (thesis or {}).get("version"), settings.openai_model, json.dumps(result, ensure_ascii=False),
                "passed", db.utcnow(),
            ),
        )

    generator = run_grounded_stream(
        mode="research",
        asset=dict(asset),
        question=f"请分析事件「{event_evidence['title']}」对当前行情和用户判断的意义。",
        event={
            "event_id": event_evidence["evidence_id"],
            "title": event_evidence["title"],
            "published_at": event_evidence["published_at"],
            "source_type": event_evidence["source_type"],
        },
        evidence_items=[event_evidence],
        thesis=thesis,
        recent_messages=recent,
        snapshot=snapshot,
        save_result=save_result,
    )
    return _sse_response(generator)
