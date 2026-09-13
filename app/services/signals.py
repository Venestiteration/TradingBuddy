"""把行情与已有证据转换为重要性评分所需的统一信号。"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .importance import FORMULA_VERSION, freshness_score, score_signal

UPSTREAM_WORDS = ("供应商", "客户", "订单", "原材料", "产能", "库存", "渠道", "采购", "需求")
CROSS_ASSET_WORDS = ("汇率", "人民币", "美元", "利率", "国债", "原油", "黄金", "铜", "指数", "港股", "美股")
HIGH_MATERIALITY_WORDS = ("财报", "业绩", "监管", "处罚", "重大合同", "重组", "并购", "停产", "风险提示")


def _clip(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def _direction(change: float) -> str:
    return "positive" if change > 0 else "negative" if change < 0 else "neutral"


def build_market_signals(rows: list[dict]) -> list[dict]:
    """每天从历史行情生成一个行情信号；不把上涨方向当成重要性。"""
    clean = sorted(
        (row for row in rows if row.get("date") and row.get("close") is not None),
        key=lambda row: str(row["date"]),
    )
    signals: list[dict] = []
    returns: list[float] = []
    for index, row in enumerate(clean):
        close = float(row["close"])
        previous = float(clean[index - 1]["close"]) if index else close
        daily_return = close / previous - 1 if previous else 0.0
        prior_returns = returns[-20:]
        volatility = statistics.pstdev(prior_returns) if len(prior_returns) >= 2 else 0.005
        anomaly = _clip(abs(daily_return) / max(volatility, 0.005) * 25)

        sign = 1 if daily_return > 0 else -1 if daily_return < 0 else 0
        streak = 1 if sign else 0
        for prior in reversed(returns):
            if sign and (prior > 0) == (sign > 0):
                streak += 1
            else:
                break
        ma5 = float(row.get("MA5") or close)
        ma20 = float(row.get("MA20") or close)
        persistence = _clip(
            0.4 * min(streak / 5 * 100, 100)
            + 0.3 * min(abs(close / ma5 - 1) / 0.05 * 100, 100)
            + 0.3 * min(abs(close / ma20 - 1) / 0.10 * 100, 100)
        )
        volumes = [float(item.get("volume") or 0) for item in clean[max(0, index - 20):index]]
        median_volume = statistics.median(volumes) if volumes else float(row.get("volume") or 0)
        volume_ratio = float(row.get("volume") or 0) / median_volume if median_volume else 0
        participation = _clip(volume_ratio / 3 * 100)
        scored = score_signal("market", {"R": 100, "A": anomaly, "S": persistence, "V": participation})
        signal_date = str(row["date"])[:10]
        signals.append({
            "signal_date": signal_date,
            "category": "market",
            "direction": _direction(daily_return),
            "title": f"{signal_date} 行情重要性",
            "summary": f"当日涨跌 {daily_return * 100:+.2f}%，成交参与度 {participation:.0f}。",
            "factor_scores": scored,
            "raw_score": scored["score"],
            "score": max(5.0, scored["score"]),
            "source_status": "fresh",
            "evidence_ids": [],
            "formula_version": FORMULA_VERSION,
        })
        returns.append(daily_return)
    return signals


def _parse_time(value: str | None, fallback: str | None) -> datetime:
    text = value or fallback
    if not text:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _confidence(item: dict) -> float:
    base = 90 if item.get("source_level") == "primary" else 70
    if item.get("content_status") == "title_only":
        base = min(base, 50)
    if not item.get("published_at"):
        base = min(base, 60)
    return float(base)


def _materiality(text: str, source_type: str) -> float:
    if any(word in text for word in HIGH_MATERIALITY_WORDS):
        return 85.0
    return 65.0 if source_type == "announcement" else 50.0


def build_evidence_signals(
    evidence_rows: list[dict], stock_code: str, stock_name: str,
    now: datetime | None = None,
) -> list[dict]:
    current = now or datetime.now(timezone.utc)
    output: list[dict] = []
    for item in evidence_rows:
        if item.get("source_type") == "market":
            continue
        text = f"{item.get('title', '')} {item.get('excerpt', '')}"
        published = _parse_time(item.get("published_at"), item.get("fetched_at"))
        age_hours = max(0.0, (current - published.astimezone(timezone.utc)).total_seconds() / 3600)
        confidence = _confidence(item)
        materiality = _materiality(text, str(item.get("source_type") or ""))
        relevance = 90.0 if stock_code in text or stock_name in text else 70.0
        categories = ["public"]
        if any(word in text for word in UPSTREAM_WORDS):
            categories.append("upstream")
        if any(word in text for word in CROSS_ASSET_WORDS):
            categories.append("cross_asset")
        for category in categories:
            if category == "public":
                factors = {
                    "R": freshness_score(age_hours, 48), "M": materiality,
                    "C": confidence, "L": relevance,
                }
            elif category == "upstream":
                factors = {
                    "R": freshness_score(age_hours, 96), "M": materiality,
                    "C": confidence, "T": 80.0,
                }
            else:
                factors = {
                    "C": confidence, "G": 80.0, "T": 70.0,
                    "M": materiality * 2 ** (-age_hours / 48),
                }
            scored = score_signal(category, factors)
            output.append({
                "signal_date": published.date().isoformat(),
                "category": category,
                "direction": "unknown",
                "title": str(item.get("title") or "公开信息"),
                "summary": str(item.get("excerpt") or item.get("title") or "")[:120],
                "factor_scores": scored,
                "raw_score": scored["score"],
                "score": max(5.0, scored["score"]),
                "source_status": "fresh",
                "evidence_ids": [str(item["evidence_id"])],
                "formula_version": FORMULA_VERSION,
            })
    return output
