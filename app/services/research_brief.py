from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .research_events import build_research_events


_PUBLIC_SOURCE_FIELDS = (
    "evidence_id",
    "title",
    "excerpt",
    "source_level",
    "source_type",
    "content_status",
    "published_at",
    "source_url",
)

_CATEGORY_RULES = {
    "定期报告与业绩": {
        "why": "业绩披露可用于检验收入、利润与现金流趋势。",
        "impact": "若关键指标偏离预期，市场可能重新评估盈利质量与估值。",
        "watch": "跟踪后续定期报告、业绩说明会与审计意见。",
    },
    "日常经营与重大合同": {
        "why": "重大合同可能影响未来收入可见度，但不等同于已确认收入。",
        "impact": "合同履约、毛利率与回款进度将决定其对盈利和现金流的实际影响。",
        "watch": "跟踪合同金额占比、履约进度、收入确认与回款。",
    },
    "分红、回购及股东变动": {
        "why": "分红、回购和股东变动可能改变股东回报与流通供给预期。",
        "impact": "实际实施规模和节奏可能影响每股指标、资金余额与市场情绪。",
        "watch": "跟踪实施进度、价格区间、资金来源与持股变动。",
    },
    "融资、并购与资产重组": {
        "why": "融资或资产交易可能改变资本结构、业务边界与每股权益。",
        "impact": "交易完成条件、定价与后续整合效果将决定增厚或摊薄方向。",
        "watch": "跟踪审批进展、交割条件、融资成本与整合指标。",
    },
    "公司治理与人员变化": {
        "why": "治理或核心人员变化可能影响决策连续性与执行节奏。",
        "impact": "影响取决于职责重要性、交接安排与后续战略调整。",
        "watch": "跟踪继任安排、治理结构与后续经营计划。",
    },
    "监管问询、处罚与风险提示": {
        "why": "监管事项可能带来合规成本、业务限制或声誉风险。",
        "impact": "后续认定、整改要求与处罚结果将决定对经营和财务的影响。",
        "watch": "跟踪公司回复、监管结论、整改时限与潜在损失。",
    },
    "更正、澄清与补充公告": {
        "why": "更正或澄清会改变先前信息的可用性与解读边界。",
        "impact": "若修正涉及关键事实或数据，相关判断需要按最新口径重新评估。",
        "watch": "跟踪更正范围、最新口径与后续补充披露。",
    },
}


def _normalized_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _public_sources(events: list[dict]) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    for event in events:
        for evidence in event.get("evidence", []):
            identity = evidence.get("evidence_id") or "|".join(
                str(evidence.get(field) or "")
                for field in ("source_url", "title", "published_at")
            )
            if identity in seen:
                continue
            seen.add(identity)
            sources.append(
                {
                    field: evidence.get(field)
                    for field in _PUBLIC_SOURCE_FIELDS
                    if field in evidence
                }
            )
    return sources


def _public_events(events: list[dict]) -> list[dict]:
    public_events = []
    for event in events:
        public_event = dict(event)
        public_event["evidence"] = [
            {
                field: evidence.get(field)
                for field in _PUBLIC_SOURCE_FIELDS
                if field in evidence
            }
            for evidence in event.get("evidence", [])
        ]
        public_events.append(public_event)
    return public_events


def _known_facts(events: list[dict]) -> list[dict]:
    facts = []
    for event in events:
        evidence_ids = [
            evidence["evidence_id"]
            for evidence in event.get("evidence", [])
            if evidence.get("evidence_id")
        ]
        facts.append(
            {
                "claim": event.get("summary") or event.get("title") or "",
                "evidence_ids": evidence_ids,
                "basis": "evidence",
            }
        )
    return facts


def _rule_items(events: list[dict], key: str) -> list[dict]:
    items = []
    seen_categories = set()
    for event in events:
        if event.get("content_status") == "title_only":
            continue
        category = event.get("category")
        rule = _CATEGORY_RULES.get(category)
        if not rule or category in seen_categories:
            continue
        seen_categories.add(category)
        items.append({"text": rule[key], "category": category, "basis": "rule"})
    return items


def _unknowns(events: list[dict]) -> list[str]:
    unknowns = []
    if any(event.get("content_status") == "title_only" for event in events):
        unknowns.append("当前仅有标题，缺少可核验的正文与细节。")
    if any(event.get("conflict_status") == "possible" for event in events):
        unknowns.append("现有证据存在冲突，需以后续权威披露核实。")
    if not unknowns:
        unknowns.append("后续进展及其对经营与财务的实际影响尚待披露。")
    return unknowns


def _watch_signals(events: list[dict]) -> list[dict]:
    signals = []
    seen_categories = set()
    for event in events:
        category = event.get("category")
        rule = _CATEGORY_RULES.get(category)
        if rule and category not in seen_categories:
            seen_categories.add(category)
            signals.append(
                {"text": rule["watch"], "category": category, "basis": "rule"}
            )
    return signals


def _empty_brief(start: datetime, end: datetime, hours: int) -> dict:
    return {
        "status": "empty",
        "window": {"hours": hours, "start": start.isoformat(), "end": end.isoformat()},
        "headline": None,
        "core_conclusion": "该时间窗口内暂无可用的公开研究事件。",
        "known_facts": [],
        "why_it_matters": [],
        "impact_paths": [],
        "inferences": [],
        "unknowns": [],
        "watch_signals": [],
        "sources": [],
        "coverage": {"event_count": 0, "source_count": 0},
        "conflict_status": "none",
        "events": [],
    }


def build_research_brief(
    asset: dict, hours: int = 24, now: datetime | None = None
) -> dict:
    """Build a deterministic, evidence-bounded research brief for one asset."""
    end = _normalized_now(now)
    start = end - timedelta(hours=hours)
    events = build_research_events(asset["id"], start, end)
    if not events:
        return _empty_brief(start, end, hours)

    headline = max(
        events,
        key=lambda event: (
            float(event.get("attention_score") or 0.0),
            event.get("published_at") or "",
        ),
    )
    has_conflict = any(
        event.get("conflict_status") == "possible" for event in events
    )
    return {
        "status": "degraded" if has_conflict else "ready",
        "window": {"hours": hours, "start": start.isoformat(), "end": end.isoformat()},
        "headline": {
            "cluster_id": headline["cluster_id"],
            "title": headline["title"],
        },
        "core_conclusion": headline.get("summary") or headline["title"],
        "known_facts": _known_facts(events),
        "why_it_matters": _rule_items(events, "why"),
        "impact_paths": _rule_items(events, "impact"),
        "inferences": [],
        "unknowns": _unknowns(events),
        "watch_signals": _watch_signals(events),
        "sources": _public_sources(events),
        "coverage": {
            "event_count": len(events),
            "source_count": sum(
                int(event.get("source_count") or 0) for event in events
            ),
        },
        "conflict_status": "possible" if has_conflict else "none",
        "events": _public_events(events),
    }
