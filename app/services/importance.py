"""研究重要性评分：纯计算，不访问数据库或外部接口。"""
from __future__ import annotations

import math

FORMULA_VERSION = "importance-v1"
CATEGORIES = ("public", "upstream", "market", "cross_asset")
FACTOR_WEIGHTS = {
    "public": {"R": 0.25, "M": 0.30, "C": 0.25, "L": 0.20},
    "upstream": {"R": 0.20, "M": 0.25, "C": 0.25, "T": 0.30},
    "market": {"R": 0.20, "A": 0.35, "S": 0.25, "V": 0.20},
    "cross_asset": {"C": 0.20, "G": 0.25, "T": 0.30, "M": 0.25},
}
DECAY_HALF_LIVES = {"public": 3, "upstream": 10, "cross_asset": 5}


def _round(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def freshness_score(age_hours: float, half_life_hours: float) -> float:
    if half_life_hours <= 0:
        raise ValueError("时效性半衰期必须大于零")
    return _round(100 * math.pow(2, -max(0.0, age_hours) / half_life_hours))


def score_signal(category: str, factors: dict[str, float | None]) -> dict:
    if category not in FACTOR_WEIGHTS:
        raise ValueError(f"不支持的评分类别：{category}")
    weights = FACTOR_WEIGHTS[category]
    valid = {name: float(factors[name]) for name in weights if factors.get(name) is not None}
    valid_weight = sum(weights[name] for name in valid)
    if valid_weight < 0.60:
        raise ValueError("有效因子权重不足 60%")
    contributions = {
        name: _round(valid[name] * weights[name] / valid_weight)
        for name in valid
    }
    return {
        "score": _round(sum(contributions.values())),
        "factors": {name: _round(value) for name, value in valid.items()},
        "weights": {name: weights[name] for name in valid},
        "contributions": contributions,
        "missing_factors": [name for name in weights if name not in valid],
        "formula_version": FORMULA_VERSION,
    }


def decay_score(raw_score: float, trading_days: int, category: str) -> float:
    if category not in DECAY_HALF_LIVES:
        raise ValueError("行情类别不能使用历史衰减")
    half_life = DECAY_HALF_LIVES[category]
    return _round(raw_score * math.pow(2, -max(0, trading_days) / half_life))


def daily_scores(raw_scores: dict[str, float | None], cached: bool = False) -> dict:
    displayed = {
        category: (
            None
            if raw_scores.get(category) is None and category == "market"
            else _round(max(5.0, raw_scores.get(category) or 0.0))
        )
        for category in CATEGORIES
    }
    available = [value for value in displayed.values() if value is not None]
    if displayed["market"] is None:
        preview = _round(sum(available) / len(available)) if available else None
        return {
            "category_scores": displayed,
            "composite_score": None,
            "preview_score": preview,
            "dominant_category": None,
            "status": "incomplete",
            "formula_version": FORMULA_VERSION,
        }
    composite = _round(sum(displayed.values()) / 4)
    dominant = max(CATEGORIES, key=lambda item: displayed[item])
    return {
        "category_scores": displayed,
        "composite_score": composite,
        "preview_score": composite,
        "dominant_category": dominant,
        "status": "cached" if cached else "complete",
        "formula_version": FORMULA_VERSION,
    }
