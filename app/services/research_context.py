from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


MAX_EVIDENCE = 12
MAX_MESSAGES = 6
MAX_MESSAGE_CHARS = 2000
LOOKBACK_DAYS = 90

PRODUCT_BOUNDARY = (
    "仅使用本次上下文做可核验的研究信息整理；"
    "不构成交易指令，不提供买卖、仓位、目标价或交易时点建议；"
    "不推断用户持仓、成本或风险偏好；"
    "不触发新的外部数据收集或写入。"
)

_ASSET_FIELDS = ("stock_code", "stock_name")
_SNAPSHOT_FIELDS = (
    "code",
    "name",
    "market",
    "price",
    "prev_close",
    "open",
    "high",
    "low",
    "change_pct",
    "volume",
    "amount",
    "pe_dynamic",
    "pb",
    "market_cap",
    "price_time",
    "fetched_at",
    "source",
    "stale",
)
_EVIDENCE_FIELDS = (
    "evidence_id",
    "source_type",
    "source_level",
    "title",
    "excerpt",
    "published_at",
    "source_url",
    "content_status",
)
_EVENT_FIELDS = (
    "cluster_id",
    "title",
    "summary",
    "published_at",
    "category",
    "conflict_status",
    "conflicts",
)
_THESIS_FIELDS = (
    "version",
    "core_thesis",
    "watch_variables",
    "invalid_conditions",
)
_DAILY_BRIEF_FIELDS = (
    "status",
    "window",
    "headline",
    "core_conclusion",
    "known_facts",
    "why_it_matters",
    "impact_paths",
    "inferences",
    "unknowns",
    "watch_signals",
    "coverage",
    "conflict_status",
)

_ORIGINAL_SOURCE_TYPES = {"market", "announcement", "news"}
_CONFIRMED_STATUSES = {"已由你确认", "已确认", "confirmed"}
_NORMALIZED_CONFIRMED_STATUSES = {value.lower() for value in _CONFIRMED_STATUSES}
_EMBEDDED_EVIDENCE_KEYS = {"evidence", "raw", "sources", "events"}

_TRADING_TERMS = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "止损",
    "止盈",
    "目标价",
    "仓位",
    "买点",
    "卖点",
    "交易计划",
    "操作计划",
    "该不该买",
    "要不要卖",
)
_EMOTION_TERMS = (
    "恐慌",
    "焦虑",
    "害怕",
    "心慌",
    "后悔",
    "难受",
    "睡不着",
    "不知所措",
)
_CONCEPT_TERMS = (
    "什么意思",
    "是什么",
    "怎么理解",
    "概念",
    "市盈率",
    "市净率",
    "股息率",
    "毛利率",
)
_ANALYSIS_TERMS = (
    "公司",
    "影响",
    "利润",
    "盈利",
    "营收",
    "业绩",
    "现金流",
    "基本面",
    "估值",
    "合同",
    "回款",
    "竞争",
    "风险",
)
_TOKEN_STOPWORDS = {
    "这个",
    "那个",
    "什么",
    "怎么",
    "如何",
    "现在",
    "是否",
    "可以",
    "事情",
    "事件",
}


def classify_question_focus(question: str) -> str:
    """Return a presentation hint; callers must not treat it as user state."""
    text = str(question or "").strip().lower()
    if any(term in text for term in _TRADING_TERMS):
        return "trading_plan"
    if any(term in text for term in _EMOTION_TERMS):
        return "emotion"
    if any(term in text for term in _CONCEPT_TERMS):
        return "concept"
    if any(term in text for term in _ANALYSIS_TERMS):
        return "asset_analysis"
    return "information"


def _pick(source: dict | None, fields: tuple[str, ...]) -> dict:
    if not isinstance(source, dict):
        return {}
    return {field: deepcopy(source[field]) for field in fields if field in source}


def _without_embedded_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_embedded_evidence(child)
            for key, child in value.items()
            if key not in _EMBEDDED_EVIDENCE_KEYS
        }
    if isinstance(value, list):
        return [_without_embedded_evidence(child) for child in value]
    return deepcopy(value)


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens - _TOKEN_STOPWORDS


def _evidence_tokens(item: dict) -> set[str]:
    return _tokens(f"{item.get('title') or ''} {item.get('excerpt') or ''}")


def _valid_evidence(item: Any) -> bool:
    if not isinstance(item, dict) or not str(item.get("evidence_id") or "").strip():
        return False
    source_type = str(item.get("source_type") or "").strip().lower()
    return source_type in _ORIGINAL_SOURCE_TYPES


def _main_daily_evidence(daily_brief: dict) -> list[dict]:
    headline = daily_brief.get("headline") if isinstance(daily_brief, dict) else None
    if not isinstance(headline, dict):
        return []
    if isinstance(headline.get("evidence"), list):
        return headline["evidence"]
    cluster_id = headline.get("cluster_id")
    for event in daily_brief.get("events", []):
        if isinstance(event, dict) and event.get("cluster_id") == cluster_id:
            return event.get("evidence", []) if isinstance(event.get("evidence"), list) else []
    return []


def _reference_time(
    selected_event: dict | None, daily_brief: dict, evidence_items: list[dict]
) -> datetime:
    candidates: list[datetime] = []
    window = daily_brief.get("window") if isinstance(daily_brief, dict) else None
    if isinstance(window, dict):
        parsed = _parse_time(window.get("end"))
        if parsed:
            candidates.append(parsed)
    if isinstance(selected_event, dict):
        parsed = _parse_time(selected_event.get("published_at"))
        if parsed:
            candidates.append(parsed)
    for item in evidence_items:
        if isinstance(item, dict):
            parsed = _parse_time(item.get("published_at"))
            if parsed:
                candidates.append(parsed)
    return max(candidates) if candidates else datetime.now(timezone.utc)


def _selected_evidence(
    question: str,
    selected_event: dict | None,
    daily_brief: dict,
    evidence_items: list[dict],
) -> list[dict]:
    ordered: list[dict] = []
    seen: set[str] = set()

    def add(items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not _valid_evidence(item):
                continue
            evidence_id = str(item["evidence_id"])
            if evidence_id in seen or len(ordered) >= MAX_EVIDENCE:
                continue
            seen.add(evidence_id)
            ordered.append(_pick(item, _EVIDENCE_FIELDS))

    add((selected_event or {}).get("evidence", []))
    add(_main_daily_evidence(daily_brief))

    cutoff = _reference_time(selected_event, daily_brief, evidence_items) - timedelta(
        days=LOOKBACK_DAYS
    )
    question_tokens = _tokens(question)
    ranked: list[tuple[int, datetime, int, dict]] = []
    for position, item in enumerate(evidence_items):
        if not _valid_evidence(item) or str(item["evidence_id"]) in seen:
            continue
        published_at = _parse_time(item.get("published_at"))
        if published_at is None or published_at < cutoff:
            continue
        overlap = len(question_tokens & _evidence_tokens(item))
        if overlap:
            ranked.append((overlap, published_at, -position, item))
    ranked.sort(key=lambda value: (value[0], value[1], value[2]), reverse=True)
    add([value[3] for value in ranked])
    return ordered


def _relevant_messages(
    question: str, selected_event: dict | None, recent_messages: list[dict]
) -> list[dict]:
    relevance_tokens = _tokens(question)
    if isinstance(selected_event, dict):
        relevance_tokens |= _tokens(selected_event.get("title"))
        relevance_tokens |= _tokens(selected_event.get("summary"))
        for item in selected_event.get("evidence", []):
            if isinstance(item, dict):
                relevance_tokens |= _evidence_tokens(item)

    relevant: list[dict] = []
    for message in recent_messages:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "")
        if not content.strip() or not (_tokens(content) & relevance_tokens):
            continue
        normalized = {
            "context_type": "conversation",
            "role": str(message.get("role") or "user"),
            "content": content[:MAX_MESSAGE_CHARS],
        }
        if "id" in message:
            normalized["message_id"] = message["id"]
        if "created_at" in message:
            normalized["created_at"] = message["created_at"]
        relevant.append(normalized)
    return relevant[-MAX_MESSAGES:]


def _confirmed_thesis(thesis: dict | None) -> dict | None:
    if not isinstance(thesis, dict):
        return None
    status = thesis.get("status")
    confirmed = thesis.get("confirmed")
    status_is_confirmed = (
        status is not None
        and str(status).strip().lower() in _NORMALIZED_CONFIRMED_STATUSES
    )
    if confirmed is False or not (confirmed is True or status_is_confirmed):
        return None
    selected = _pick(thesis, _THESIS_FIELDS)
    return selected or None


def select_research_context(
    asset: dict,
    question: str,
    snapshot: dict | None,
    selected_event: dict | None,
    daily_brief: dict,
    evidence_items: list[dict],
    thesis: dict | None,
    recent_messages: list[dict],
) -> dict:
    """Build a read-only, evidence-bounded context for one research request."""
    context = {
        "asset": _pick(asset, _ASSET_FIELDS),
        "question": str(question or "").strip(),
        "question_focus": classify_question_focus(question),
        "product_boundary": PRODUCT_BOUNDARY,
        "daily_brief": _without_embedded_evidence(
            _pick(daily_brief, _DAILY_BRIEF_FIELDS)
        ),
        "evidence": _selected_evidence(
            question, selected_event, daily_brief, evidence_items
        ),
        "recent_messages": _relevant_messages(
            question, selected_event, recent_messages
        ),
    }
    if snapshot:
        context["market_snapshot"] = _pick(snapshot, _SNAPSHOT_FIELDS)
    if selected_event:
        context["selected_event"] = _pick(selected_event, _EVENT_FIELDS)
    confirmed_thesis = _confirmed_thesis(thesis)
    if confirmed_thesis:
        context["confirmed_thesis"] = confirmed_thesis
    return context
