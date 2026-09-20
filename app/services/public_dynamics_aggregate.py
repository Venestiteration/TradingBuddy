from __future__ import annotations

import hashlib
import re
from datetime import datetime

from .public_dynamics_types import DynamicCluster, RawDynamic


CATEGORY_RULES = (
    ("定期报告与业绩", ("年报", "半年报", "季报", "业绩", "财务报告")),
    ("日常经营与重大合同", ("经营", "订单", "中标", "合同", "销售")),
    ("分红、回购及股东变动", ("分红", "派息", "回购", "增持", "减持", "股东")),
    ("融资、并购与资产重组", ("融资", "定增", "配股", "并购", "收购", "重组")),
    ("公司治理与人员变化", ("董事会", "监事会", "股东大会", "任职", "辞职")),
    ("监管问询、处罚与风险提示", ("监管", "问询", "处罚", "立案", "风险提示", "退市")),
    ("更正、澄清与补充公告", ("更正", "澄清", "补充", "致歉")),
)


def normalize_title(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", title).lower()


def classify_announcement(title: str, source_category: str) -> str:
    text = f"{source_category} {title}"
    for label, words in CATEGORY_RULES:
        if any(word in text for word in words):
            return label
    return "其他公告"


def evidence_identity(item: RawDynamic) -> str:
    raw = f"{item.provider}|{item.provider_item_id}|{item.source_url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _numbers(title: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:\.\d+)?", title))


def _tokens(title: str) -> set[str]:
    normalized = normalize_title(title)
    return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}


def _similar(left: RawDynamic, right: RawDynamic) -> bool:
    if left.stock_code != right.stock_code or left.kind != right.kind:
        return False
    if _numbers(left.title) != _numbers(right.title):
        return False

    left_time = datetime.fromisoformat(left.published_at)
    right_time = datetime.fromisoformat(right.published_at)
    if left.kind == "announcement":
        return (
            left_time.date() == right_time.date()
            and normalize_title(left.title) == normalize_title(right.title)
        )

    if abs((left_time - right_time).total_seconds()) > 6 * 3600:
        return False
    left_tokens, right_tokens = _tokens(left.title), _tokens(right.title)
    union = left_tokens | right_tokens
    return bool(union) and len(left_tokens & right_tokens) / len(union) >= 0.82


def _factor_scores(members: list[RawDynamic]) -> dict[str, float]:
    primary = any(item.source_level == "primary" for item in members)
    full = any(item.content_status == "full" for item in members)
    excerpt = any(item.content_status == "excerpt" for item in members)
    title = members[0].title
    category = (
        classify_announcement(title, members[0].category)
        if members[0].kind == "announcement"
        else "媒体报道"
    )
    materiality = (
        90.0
        if category == "监管问询、处罚与风险提示"
        else 75.0 if category != "其他公告" else 45.0
    )
    return {
        "authority": 95.0 if primary else 65.0,
        "materiality": materiality,
        "relevance": 100.0,
        "completeness": 90.0 if full else 70.0 if excerpt else 45.0,
    }


def aggregate_raw_dynamics(items: list[RawDynamic]) -> list[DynamicCluster]:
    groups: list[list[RawDynamic]] = []
    for candidate in sorted(items, key=lambda item: item.published_at, reverse=True):
        group = next((group for group in groups if _similar(group[0], candidate)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    clusters = []
    for members in groups:
        lead = max(
            members,
            key=lambda item: (item.source_level == "primary", len(item.excerpt)),
        )
        factors = _factor_scores(members)
        score = round(
            factors["authority"] * 0.30
            + factors["materiality"] * 0.30
            + factors["relevance"] * 0.20
            + factors["completeness"] * 0.20,
            1,
        )
        key_seed = (
            f"{lead.stock_code}|{lead.kind}|{normalize_title(lead.title)}|"
            f"{lead.published_at[:10]}"
        )
        clusters.append(
            DynamicCluster(
                canonical_key=hashlib.sha1(key_seed.encode("utf-8")).hexdigest(),
                kind=lead.kind,
                category=(
                    classify_announcement(lead.title, lead.category)
                    if lead.kind == "announcement"
                    else "媒体报道"
                ),
                title=lead.title,
                summary=max((item.excerpt for item in members), key=len, default=""),
                published_at=max(item.published_at for item in members),
                importance_score=score,
                importance_factors=factors,
                content_status=(
                    "full"
                    if any(item.content_status == "full" for item in members)
                    else "excerpt"
                    if any(item.content_status == "excerpt" for item in members)
                    else "title_only"
                ),
                conflict_status="none",
                members=tuple(members),
            )
        )
    return sorted(clusters, key=lambda cluster: cluster.published_at, reverse=True)
