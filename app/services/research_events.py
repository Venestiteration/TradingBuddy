from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .public_dynamics import dynamic_evidence, list_public_dynamics


ATTENTION_WEIGHTS = {
    "relevance": 0.30,
    "materiality": 0.25,
    "freshness": 0.20,
    "evidence_quality": 0.15,
    "independent_corroboration": 0.10,
}

_CONTENT_RANK = {"title_only": 0, "excerpt": 1, "full": 2}
_NEGATIONS = ("未", "不", "无", "否认", "取消", "终止", "停止", "失败")
_EVENT_TERMS = {
    "contract": ("合同", "订单", "供货", "签约", "签订", "签署"),
    "bid": ("中标", "招标"),
    "earnings": ("业绩", "营收", "净利润", "亏损"),
    "buyback": ("回购", "增持", "减持"),
    "dividend": ("分红", "派息"),
    "financing": ("融资", "定增", "配股"),
    "transaction": ("并购", "收购", "重组"),
    "regulatory": ("监管", "问询", "处罚", "立案"),
    "personnel": ("任职", "辞职"),
}
_SYNONYMS = (
    ("签署", "签订"),
    ("签约", "签订"),
    ("获得", "获取"),
    ("中得", "获取"),
)


def _parse_time(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalized_title(title: str, *, mask_numbers: bool = False) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", title).lower()
    for source, replacement in _SYNONYMS:
        normalized = normalized.replace(source, replacement)
    if mask_numbers:
        normalized = re.sub(r"\d+(?:\.\d+)?", "0", normalized)
    return normalized


def _bigrams(value: str) -> set[str]:
    if len(value) < 2:
        return {value} if value else set()
    return {value[index : index + 2] for index in range(len(value) - 1)}


def _title_similarity(left: str, right: str) -> float:
    left_pairs = _bigrams(_normalized_title(left, mask_numbers=True))
    right_pairs = _bigrams(_normalized_title(right, mask_numbers=True))
    union = left_pairs | right_pairs
    return len(left_pairs & right_pairs) / len(union) if union else 0.0


def _event_terms(title: str) -> set[str]:
    return {
        canonical
        for canonical, variants in _EVENT_TERMS.items()
        if any(term in title for term in variants)
    }


def _subject_terms(title: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,20}(?:公司|集团|银行)", title))
    terms.update(term for term in ("公司", "本公司", "集团", "银行") if term in title)
    return terms


def _can_merge(left: dict, right: dict) -> bool:
    if left["asset_id"] != right["asset_id"]:
        return False
    hours = abs(
        (
            _parse_time(left["published_at"])
            - _parse_time(right["published_at"])
        ).total_seconds()
    ) / 3600
    kinds = {left["kind"], right["kind"]}
    if kinds == {"news"}:
        return hours <= 36 and _title_similarity(
            left["canonical_title"], right["canonical_title"]
        ) >= 0.72
    if kinds == {"announcement", "news"}:
        return (
            hours <= 72
            and left.get("category") == right.get("category")
            and bool(
                _subject_terms(left["canonical_title"])
                & _subject_terms(right["canonical_title"])
            )
            and bool(
                _event_terms(left["canonical_title"])
                & _event_terms(right["canonical_title"])
            )
        )
    return False


def _evidence_rank(item: dict) -> tuple[int, int]:
    return (
        1 if item.get("source_level") == "primary" else 0,
        _CONTENT_RANK.get(item.get("content_status", "title_only"), 0),
    )


def _deduplicated_evidence(members: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    without_id: list[dict] = []
    for member in members:
        for item in member.get("evidence", []):
            evidence_id = item.get("evidence_id")
            if not evidence_id:
                without_id.append(item)
                continue
            current = by_id.get(evidence_id)
            if current is None or _evidence_rank(item) > _evidence_rank(current):
                by_id[evidence_id] = item
    return sorted(
        [*by_id.values(), *without_id],
        key=lambda item: (_evidence_rank(item), item.get("published_at", "")),
        reverse=True,
    )


def _source_identity(item: dict) -> str:
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    provider = raw.get("provider")
    if provider:
        return f"provider:{provider}"
    source_url = item.get("source_url") or ""
    hostname = urlparse(source_url).hostname
    if hostname:
        return f"host:{hostname.lower()}"
    return f"evidence:{item.get('evidence_id', '')}"


def _has_conflict(members: list[dict]) -> bool:
    titles = [member["canonical_title"] for member in members]
    number_sets = [tuple(re.findall(r"\d+(?:\.\d+)?", title)) for title in titles]
    populated_numbers = {numbers for numbers in number_sets if numbers}
    negated = {any(term in title for term in _NEGATIONS) for title in titles}
    return (
        any(member.get("conflict_status") == "possible" for member in members)
        or len(populated_numbers) > 1
        or len(negated) > 1
    )


def _attention_factors(
    members: list[dict], evidence: list[dict], now: datetime
) -> dict[str, dict[str, float]]:
    latest = max(_parse_time(member["published_at"]) for member in members)
    age_hours = max(0.0, (now - latest).total_seconds() / 3600)
    materiality = max(
        float(member.get("importance_score") or 0.0) for member in members
    )
    if evidence:
        best_evidence = max(evidence, key=_evidence_rank)
        primary, content_rank = _evidence_rank(best_evidence)
        quality = (70.0 if primary else 40.0) + (content_rank * 15.0)
        source_count = len({_source_identity(item) for item in evidence})
    else:
        quality = (
            25.0
            if any(
                member.get("content_status") != "title_only" for member in members
            )
            else 15.0
        )
        source_count = 0
    scores = {
        "relevance": 100.0,
        "materiality": min(100.0, max(0.0, materiality)),
        "freshness": max(0.0, 100.0 - age_hours * (100.0 / 72.0)),
        "evidence_quality": min(100.0, quality),
        "independent_corroboration": min(100.0, source_count * 50.0),
    }
    return {
        name: {
            "score": round(score, 1),
            "weight": ATTENTION_WEIGHTS[name],
            "contribution": round(score * ATTENTION_WEIGHTS[name], 1),
        }
        for name, score in scores.items()
    }


def _build_event(members: list[dict], now: datetime) -> dict:
    members = sorted(members, key=lambda member: member["id"])
    evidence = _deduplicated_evidence(members)
    best_evidence = max(evidence, key=_evidence_rank, default=None)
    lead = max(
        members,
        key=lambda member: (
            max(
                (
                    _evidence_rank(item)
                    for item in member.get("evidence", [])
                ),
                default=(0, -1),
            ),
            _CONTENT_RANK.get(member.get("content_status", "title_only"), 0),
            float(member.get("importance_score") or 0.0),
            -member["id"],
        ),
    )
    title = (
        best_evidence.get("title")
        if best_evidence and best_evidence.get("title")
        else lead["canonical_title"]
    )
    summaries = [member.get("summary") or "" for member in members]
    summary = lead.get("summary") or max(summaries, key=len, default="")
    conflict = _has_conflict(members)
    factors = _attention_factors(members, evidence, now)
    source_count = len({_source_identity(item) for item in evidence})
    dynamic_ids = [member["id"] for member in members]
    return {
        "cluster_id": f"{lead['asset_id']}:{min(dynamic_ids)}",
        "asset_id": lead["asset_id"],
        "dynamic_ids": dynamic_ids,
        "title": title,
        "summary": summary,
        "published_at": max(
            members, key=lambda member: _parse_time(member["published_at"])
        )["published_at"],
        "category": lead["category"],
        "kinds": sorted({member["kind"] for member in members}),
        "content_status": max(
            (member.get("content_status", "title_only") for member in members),
            key=lambda status: _CONTENT_RANK.get(status, 0),
        ),
        "conflict_status": "possible" if conflict else "none",
        "conflicts": [
            {
                "dynamic_id": member["id"],
                "title": member["canonical_title"],
                "summary": member.get("summary") or "",
                "published_at": member["published_at"],
                "evidence_ids": [
                    item["evidence_id"]
                    for item in member.get("evidence", [])
                    if item.get("evidence_id")
                ],
            }
            for member in members
        ]
        if conflict
        else [],
        "attention_score": round(
            sum(item["contribution"] for item in factors.values()), 1
        ),
        "attention_factors": factors,
        "source_count": source_count,
        "evidence": evidence,
    }


def cluster_dynamic_rows(rows: list[dict], now: datetime | None = None) -> list[dict]:
    """Return conservative event clusters sorted by attention score descending.

    Similar media titles within 36 hours may merge when their normalized Chinese
    bigram Jaccard score is at least 0.72. Announcements may link to media within
    72 hours only when subject terms, event terms, and category agree. A numeric
    or negation mismatch sets conflict_status=possible and retains every claim.
    """
    if not rows:
        return []
    current_time = _parse_time(now or datetime.now(timezone.utc))
    groups: list[list[dict]] = []
    for candidate in sorted(rows, key=lambda row: row["id"]):
        group = next(
            (
                existing
                for existing in groups
                if any(_can_merge(member, candidate) for member in existing)
            ),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    events = [_build_event(group, current_time) for group in groups]
    return sorted(
        events,
        key=lambda event: (-event["attention_score"], min(event["dynamic_ids"])),
    )


def build_research_events(asset_id: int, start: datetime, end: datetime) -> list[dict]:
    rows = list_public_dynamics(asset_id, start, end, kind="all")
    for row in rows:
        row["evidence"] = dynamic_evidence(row["id"], asset_id=asset_id)
    return cluster_dynamic_rows(rows)


def get_research_event(
    asset_id: int, cluster_id: str, start: datetime, end: datetime
) -> dict | None:
    return next(
        (
            event
            for event in build_research_events(asset_id, start, end)
            if event["cluster_id"] == cluster_id
        ),
        None,
    )
