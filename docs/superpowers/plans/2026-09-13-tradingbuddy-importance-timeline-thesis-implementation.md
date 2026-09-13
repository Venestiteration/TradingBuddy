# TradingBuddy Importance Timeline and Thesis Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuous, explainable daily importance timeline and turn selected user/AI conversations into user-confirmed, dated thesis versions.

**Architecture:** Keep the current local FastAPI + SQLite + native JavaScript application. Implement deterministic scoring in pure Python, adapt existing market/evidence records into scored signals, persist formula-versioned daily snapshots, and expose drill-down APIs. Reuse the existing right-side sheet for timeline details and a separately persisted AI-assisted thesis draft workflow; only an explicit user confirmation creates a new immutable thesis version.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLite, NumPy/Pandas already present in the repository, OpenAI-compatible SDK with Zhipu Chat Completions compatibility, browser-native ES modules, SVG, CSS, Python `unittest`, Node `node:test`.

## Global Constraints

- Keep the application local, single-process, and single-user; do not add a frontend build system, task queue, login system, broker connection, or new runtime dependency.
- `importance-v1` scores attention importance only; never present the score as price direction, expected return, target price, or a buy/sell instruction.
- Every stored factor, signal, category score, and daily score records `formula_version = "importance-v1"`.
- Every category factor is normalized to 0–100; stored calculations keep one decimal place and the UI displays rounded integers.
- Daily composite score is the arithmetic mean of four displayed category scores with fixed equal weights.
- Public, upstream, and cross-asset scores decay on 3, 10, and 5 trading-day half-lives; market is recomputed for every trading day.
- A non-market category with no prior valid signal uses `raw_score = 0`, `display_score = 5`, and `source_status = "baseline"`; it never creates invented evidence.
- If market data is unavailable and no valid market cache exists, return `status = "incomplete"` and render a chart gap.
- AI may create and update a draft but may never overwrite a confirmed thesis. Only `POST /api/assets/{asset_id}/thesis-drafts/{draft_id}/confirm` creates the next immutable version.
- Default thesis context starts after the latest confirmed thesis; without a thesis it uses the latest 20 messages. Hard limits are 50 messages and 30 evidence records.
- Preserve current uncommitted frontend work. Modify files in place and stage only files named by the active task.
- Keep verification narrow: deterministic scoring, migration, thesis version transaction, required browser structure, and one manual end-to-end path.

## Scope decomposition

This plan contains two independently reviewable phases in one document because both features share the same asset context, API client, right-side sheet, evidence links, and release verification:

- Phase A, Tasks 1–5: schema, scoring, signal timeline, API, chart, and drill-down.
- Phase B, Tasks 6–8: reusable structured AI call, thesis draft backend, and thesis draft frontend.
- Task 9: integrated execution check and documentation.

---

### Task 1: Add backward-compatible persistence for importance scores and thesis drafts

**Files:**
- Modify: `app/database.py`
- Create: `tests/test_database_schema.py`

**Interfaces:**
- Consumes: existing `database.get_conn()`, `database.query()`, `database.query_one()`, and `database.execute()`.
- Produces: `database.ensure_schema(conn: sqlite3.Connection) -> None`; new tables `importance_signals`, `importance_signal_evidence`, `importance_daily`, `thesis_drafts`; new metadata columns on `theses`.

- [ ] **Step 1: Write the migration regression test**

Create `tests/test_database_schema.py`:

```python
import sqlite3
import unittest

from app import database


class DatabaseSchemaTest(unittest.TestCase):
    def test_existing_theses_table_is_extended_without_losing_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE assets (id INTEGER PRIMARY KEY, stock_code TEXT, stock_name TEXT, "
            "asset_type TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "CREATE TABLE theses (id INTEGER PRIMARY KEY, asset_id INTEGER, version INTEGER, "
            "core_thesis TEXT, watch_variables TEXT, invalid_conditions TEXT, status TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO theses VALUES (1, 7, 1, '原判断', '收入', '需求下降', '已由你确认', '2026-09-01')"
        )

        database.ensure_schema(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(theses)")}
        self.assertTrue({
            "change_summary_json", "source_message_ids_json", "source_evidence_ids_json",
            "creation_method", "base_version",
        }.issubset(columns))
        self.assertEqual(conn.execute("SELECT core_thesis FROM theses").fetchone()[0], "原判断")
        self.assertIsNotNone(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='importance_daily'"
        ).fetchone())
        self.assertIsNotNone(conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='thesis_drafts'"
        ).fetchone())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the missing migration API**

Run:

```bash
python -m unittest tests.test_database_schema -v
```

Expected: `ERROR` with `AttributeError: module 'app.database' has no attribute 'ensure_schema'`.

- [ ] **Step 3: Add schema definitions and idempotent column migration**

Extend `SCHEMA` in `app/database.py` with the following tables and indexes:

```sql
CREATE TABLE IF NOT EXISTS importance_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    signal_date TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('public', 'upstream', 'market', 'cross_asset')),
    direction TEXT NOT NULL DEFAULT 'unknown'
        CHECK (direction IN ('positive', 'negative', 'mixed', 'neutral', 'unknown')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    factor_scores_json TEXT NOT NULL DEFAULT '{}',
    raw_score REAL NOT NULL,
    score REAL NOT NULL,
    calibrated_confidence REAL,
    formula_version TEXT NOT NULL DEFAULT 'importance-v1',
    source_status TEXT NOT NULL DEFAULT 'fresh'
        CHECK (source_status IN ('fresh', 'cached', 'decayed', 'baseline')),
    origin_signal_id INTEGER REFERENCES importance_signals(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS importance_signal_evidence (
    signal_id INTEGER NOT NULL REFERENCES importance_signals(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    PRIMARY KEY (signal_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS importance_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    score_date TEXT NOT NULL,
    public_score REAL NOT NULL,
    upstream_score REAL NOT NULL,
    market_score REAL,
    cross_asset_score REAL NOT NULL,
    composite_score REAL,
    dominant_category TEXT,
    status TEXT NOT NULL CHECK (status IN ('complete', 'incomplete', 'cached')),
    formula_version TEXT NOT NULL DEFAULT 'importance-v1',
    details_json TEXT NOT NULL DEFAULT '{}',
    calculated_at TEXT NOT NULL,
    UNIQUE (asset_id, score_date, formula_version)
);

CREATE TABLE IF NOT EXISTS thesis_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL DEFAULT 0,
    selected_message_ids_json TEXT NOT NULL DEFAULT '[]',
    selected_evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    ai_suggestion_json TEXT NOT NULL DEFAULT '{}',
    user_content_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'confirmed', 'discarded')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_thesis_id INTEGER REFERENCES theses(id)
);

CREATE INDEX IF NOT EXISTS idx_importance_signal_asset_date
    ON importance_signals(asset_id, signal_date, category);
CREATE INDEX IF NOT EXISTS idx_importance_daily_asset_date
    ON importance_daily(asset_id, score_date);
CREATE INDEX IF NOT EXISTS idx_thesis_draft_asset_status
    ON thesis_drafts(asset_id, status, updated_at);
```

Add and use an idempotent migration function:

```python
THESIS_COLUMNS = {
    "change_summary_json": "TEXT NOT NULL DEFAULT '{}'",
    "source_message_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "source_evidence_ids_json": "TEXT NOT NULL DEFAULT '[]'",
    "creation_method": "TEXT NOT NULL DEFAULT 'manual'",
    "base_version": "INTEGER",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(theses)")}
    for column, definition in THESIS_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE theses ADD COLUMN {column} {definition}")


def init_db() -> None:
    settings.prepare()
    with get_conn() as conn:
        ensure_schema(conn)
```

Inside `get_conn()`, replace the first-run `conn.executescript(SCHEMA)` call with `ensure_schema(conn)` so a fresh database and an existing database follow the same path.

- [ ] **Step 4: Run the schema test and current compatibility tests**

Run:

```bash
python -m unittest tests.test_database_schema tests.test_zhipu_compat -v
```

Expected: all tests report `ok`.

- [ ] **Step 5: Commit the persistence layer**

```bash
git add app/database.py tests/test_database_schema.py
git commit -m "feat: add importance and thesis draft storage"
```

---

### Task 2: Implement deterministic `importance-v1` scoring

**Files:**
- Create: `app/services/importance.py`
- Create: `tests/test_importance.py`

**Interfaces:**
- Consumes: normalized 0–100 factor dictionaries and trading-day distances.
- Produces: `freshness_score(age_hours, half_life_hours) -> float`; `score_signal(category, factors) -> dict`; `decay_score(raw_score, trading_days, category) -> float`; `daily_scores(raw_scores, cached=False) -> dict`; constants `FORMULA_VERSION`, `CATEGORIES`, `FACTOR_WEIGHTS`, `DECAY_HALF_LIVES`.

- [ ] **Step 1: Write focused formula tests**

Create `tests/test_importance.py`:

```python
import unittest

from app.services.importance import daily_scores, decay_score, freshness_score, score_signal


class ImportanceScoreTest(unittest.TestCase):
    def test_public_formula_and_contributions(self):
        result = score_signal("public", {"R": 80, "M": 70, "C": 90, "L": 60})
        self.assertEqual(result["score"], 75.5)
        self.assertEqual(result["contributions"], {"R": 20.0, "M": 21.0, "C": 22.5, "L": 12.0})

    def test_missing_factors_require_sixty_percent_weight(self):
        result = score_signal("public", {"R": 80, "M": 70, "C": None, "L": 60})
        self.assertEqual(result["score"], 70.7)
        with self.assertRaisesRegex(ValueError, "有效因子权重不足"):
            score_signal("upstream", {"R": None, "M": 70, "C": None, "T": 80})

    def test_freshness_decay_and_daily_baseline(self):
        self.assertEqual(freshness_score(48, 48), 50.0)
        self.assertEqual(decay_score(80, 3, "public"), 40.0)
        summary = daily_scores({"public": 80, "upstream": None, "market": 20, "cross_asset": None})
        self.assertEqual(summary["category_scores"], {
            "public": 80.0, "upstream": 5.0, "market": 20.0, "cross_asset": 5.0,
        })
        self.assertEqual(summary["composite_score"], 27.5)
        self.assertEqual(summary["dominant_category"], "public")
        self.assertEqual(summary["status"], "complete")

    def test_missing_market_creates_incomplete_preview(self):
        summary = daily_scores({"public": 40, "upstream": None, "market": None, "cross_asset": None})
        self.assertIsNone(summary["composite_score"])
        self.assertEqual(summary["preview_score"], 16.7)
        self.assertEqual(summary["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the module is absent**

Run:

```bash
python -m unittest tests.test_importance -v
```

Expected: import failure for `app.services.importance`.

- [ ] **Step 3: Implement the pure scoring module**

Create `app/services/importance.py`:

```python
from __future__ import annotations

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
    return _round(100 * 2 ** (-max(0.0, age_hours) / half_life_hours))


def score_signal(category: str, factors: dict[str, float | None]) -> dict:
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
    return _round(raw_score * 2 ** (-max(0, trading_days) / half_life))


def daily_scores(raw_scores: dict[str, float | None], cached: bool = False) -> dict:
    displayed = {
        category: (None if raw_scores.get(category) is None and category == "market"
                   else _round(max(5.0, raw_scores.get(category) or 0.0)))
        for category in CATEGORIES
    }
    available = [value for value in displayed.values() if value is not None]
    if displayed["market"] is None:
        return {
            "category_scores": displayed,
            "composite_score": None,
            "preview_score": _round(sum(available) / len(available)),
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
```

- [ ] **Step 4: Run the formula tests**

Run:

```bash
python -m unittest tests.test_importance -v
```

Expected: four tests pass.

- [ ] **Step 5: Commit the scoring unit**

```bash
git add app/services/importance.py tests/test_importance.py
git commit -m "feat: add explainable importance scoring"
```

---

### Task 3: Convert market rows and saved evidence into four-category signals

**Files:**
- Create: `app/services/signals.py`
- Modify: `tests/test_importance.py`

**Interfaces:**
- Consumes: market rows with `date`, `close`, `volume`, optional `MA5`, `MA20`; evidence rows from the existing `evidence` table; `importance.score_signal()`.
- Produces: `build_market_signals(rows: list[dict]) -> list[dict]`; `build_evidence_signals(evidence_rows: list[dict], stock_code: str, stock_name: str, now: datetime | None = None) -> list[dict]`; each signal has `signal_date`, `category`, `direction`, `title`, `summary`, `factor_scores`, `raw_score`, `score`, `source_status`, `evidence_ids`.

- [ ] **Step 1: Add deterministic signal tests**

Append to `tests/test_importance.py`:

```python
from datetime import datetime, timezone

from app.services.signals import build_evidence_signals, build_market_signals


class SignalBuilderTest(unittest.TestCase):
    def test_market_builder_emits_one_signal_per_row_after_warmup(self):
        rows = []
        for day in range(1, 23):
            rows.append({
                "date": f"2026-08-{day:02d}",
                "close": 100 + day * 0.2,
                "volume": 1_000_000 + day * 10_000,
                "MA5": 100 + day * 0.15,
                "MA20": 100 + day * 0.08,
            })
        signals = build_market_signals(rows)
        self.assertEqual(signals[-1]["signal_date"], "2026-08-22")
        self.assertEqual(signals[-1]["category"], "market")
        self.assertEqual(signals[-1]["factor_scores"]["R"], 100.0)
        self.assertTrue(0 <= signals[-1]["score"] <= 100)

    def test_evidence_can_create_public_and_upstream_signals(self):
        evidence = [{
            "evidence_id": "ev-1",
            "stock_code": "600000",
            "source_type": "announcement",
            "source_level": "primary",
            "title": "公司与核心供应商签订原材料长期采购合同",
            "excerpt": "合同将影响未来两个季度的原材料成本。",
            "published_at": "2026-09-13 08:00:00",
            "fetched_at": "2026-09-13T09:00:00+08:00",
            "content_status": "full",
            "raw": {},
        }]
        signals = build_evidence_signals(
            evidence, "600000", "浦发银行",
            now=datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual({item["category"] for item in signals}, {"public", "upstream"})
        self.assertEqual(signals[0]["evidence_ids"], ["ev-1"])
```

- [ ] **Step 2: Run the new tests and verify the signal module is absent**

Run:

```bash
python -m unittest tests.test_importance.SignalBuilderTest -v
```

Expected: import failure for `app.services.signals`.

- [ ] **Step 3: Implement market factor normalization**

Create `app/services/signals.py` with these exact normalization rules:

```python
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .importance import FORMULA_VERSION, freshness_score, score_signal

UPSTREAM_WORDS = ("供应商", "客户", "订单", "原材料", "产能", "库存", "渠道", "采购", "需求")
CROSS_ASSET_WORDS = ("汇率", "人民币", "美元", "利率", "国债", "原油", "黄金", "铜", "指数", "港股", "美股")
HIGH_MATERIALITY_WORDS = ("财报", "业绩", "监管", "处罚", "重大合同", "重组", "并购", "停产", "风险提示")


def _clip(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _direction(change: float) -> str:
    return "positive" if change > 0 else "negative" if change < 0 else "neutral"


def build_market_signals(rows: list[dict]) -> list[dict]:
    clean = [row for row in rows if row.get("date") and row.get("close") is not None]
    signals: list[dict] = []
    returns: list[float] = []
    for index, row in enumerate(clean):
        close = float(row["close"])
        previous = float(clean[index - 1]["close"]) if index else close
        daily_return = close / previous - 1 if previous else 0.0
        if index:
            returns.append(daily_return)
        prior_returns = returns[max(0, len(returns) - 20):-1]
        volatility = statistics.pstdev(prior_returns) if len(prior_returns) >= 2 else 0.005
        anomaly = _clip(abs(daily_return) / max(volatility, 0.005) * 25)
        streak = 0
        sign = 1 if daily_return > 0 else -1 if daily_return < 0 else 0
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
        signals.append({
            "signal_date": str(row["date"])[:10],
            "category": "market",
            "direction": _direction(daily_return),
            "title": f"{str(row['date'])[:10]} 行情重要性",
            "summary": f"当日涨跌 {daily_return * 100:+.2f}%，成交参与度 {participation:.0f}。",
            "factor_scores": scored,
            "raw_score": scored["score"],
            "score": max(5.0, scored["score"]),
            "source_status": "fresh",
            "evidence_ids": [],
            "formula_version": FORMULA_VERSION,
        })
    return signals
```

- [ ] **Step 4: Implement evidence classification and scoring**

Add to `app/services/signals.py`:

```python
def _parse_time(value: str | None, fallback: str | None) -> datetime:
    text = value or fallback
    if not text:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
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
                factors = {"R": freshness_score(age_hours, 48), "M": materiality,
                           "C": confidence, "L": relevance}
            elif category == "upstream":
                factors = {"R": freshness_score(age_hours, 96), "M": materiality,
                           "C": confidence, "T": 80.0}
            else:
                factors = {"C": confidence, "G": 80.0, "T": 70.0,
                           "M": materiality * 2 ** (-age_hours / 48)}
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
```

- [ ] **Step 5: Run signal and score tests, then commit**

Run:

```bash
python -m unittest tests.test_importance -v
```

Expected: all importance and signal tests pass.

Commit:

```bash
git add app/services/signals.py tests/test_importance.py
git commit -m "feat: derive importance signals from market and evidence"
```

---

### Task 4: Build and expose cached daily timeline data

**Files:**
- Create: `app/routers/importance.py`
- Modify: `app/main.py`
- Create: `tests/test_importance_timeline.py`

**Interfaces:**
- Consumes: `build_market_signals()`, `build_evidence_signals()`, `daily_scores()`, existing asset/history/evidence queries.
- Produces: `build_timeline(asset: dict, days: int, force: bool = False) -> list[dict]`; `GET /api/assets/{asset_id}/importance`; `GET /api/assets/{asset_id}/importance/{score_date}`; `GET /api/assets/{asset_id}/importance/{score_date}/{category}`; `POST /api/assets/{asset_id}/importance/recalculate`.

- [ ] **Step 1: Write timeline assembly tests with no network dependency**

Create `tests/test_importance_timeline.py`:

```python
import unittest

from app.routers.importance import assemble_daily_rows


class ImportanceTimelineTest(unittest.TestCase):
    def test_non_market_signals_decay_and_baseline_keeps_line_complete(self):
        trading_dates = ["2026-09-10", "2026-09-11", "2026-09-12"]
        signals = [{
            "signal_date": "2026-09-10", "category": "public", "raw_score": 80.0,
            "score": 80.0, "summary": "公告", "title": "公告", "source_status": "fresh",
        }]
        signals.extend({
            "signal_date": date, "category": "market", "raw_score": 20.0,
            "score": 20.0, "summary": "行情", "title": "行情", "source_status": "fresh",
        } for date in trading_dates)
        rows = assemble_daily_rows(trading_dates, signals)
        self.assertEqual([row["status"] for row in rows], ["complete", "complete", "complete"])
        self.assertEqual(rows[0]["category_scores"]["upstream"], 5.0)
        self.assertLess(rows[2]["raw_category_scores"]["public"], 80.0)
        self.assertEqual(rows[2]["category_status"]["cross_asset"], "baseline")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify the router is absent**

Run:

```bash
python -m unittest tests.test_importance_timeline -v
```

Expected: import failure for `app.routers.importance`.

- [ ] **Step 3: Implement daily assembly and persistence helpers**

Create `app/routers/importance.py`. Define these Pydantic/path constraints and helpers exactly:

```python
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .. import database as db
from ..services.evidence import get_evidence, public_evidence
from ..services.importance import CATEGORIES, FORMULA_VERSION, daily_scores, decay_score
from ..services.market import MarketDataError, market_service
from ..services.signals import build_evidence_signals, build_market_signals
from .assets import _asset_row

router = APIRouter(prefix="/api")


def assemble_daily_rows(trading_dates: list[str], signals: list[dict]) -> list[dict]:
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
        summary = daily_scores(raw)
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
```

Add `_source_rows(stock_code, first_date)`, `_persist_signals(asset_id, signals)`, `_persist_daily(asset_id, rows)`, `_load_cached(asset_id, days)`, and `build_timeline(asset, days, force=False)` in the same file. Their required behavior is:

```python
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
    signals.extend(build_evidence_signals(
        evidence_rows, asset["stock_code"], asset["stock_name"]
    ))
    _persist_signals(asset["id"], signals)
    daily = assemble_daily_rows([str(row["date"])[:10] for row in trading_rows], signals)
    _persist_daily(asset["id"], daily)
    return daily[-days:]
```

Implement persistence with exact asset, formula, and date bounds. `_persist_signals()` mutates each in-memory signal to add its database `id`, allowing the daily snapshot to retain the selected signal IDs:

```python
def _source_rows(stock_code: str, first_date: str) -> list[dict]:
    rows = db.query(
        "SELECT * FROM evidence WHERE stock_code = ? AND "
        "substr(COALESCE(published_at, fetched_at), 1, 10) >= ? ORDER BY published_at",
        (stock_code, first_date),
    )
    for row in rows:
        row["raw"] = json.loads(row.get("raw") or "{}")
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
            "category_scores": {"public": row["public_score"], "upstream": row["upstream_score"],
                                "market": row["market_score"], "cross_asset": row["cross_asset_score"]},
            "raw_category_scores": details.get("raw_category_scores", {}),
            "category_status": details.get("category_status", {}),
            "composite_score": row["composite_score"],
            "preview_score": details.get("preview_score"),
            "dominant_category": row["dominant_category"], "status": row["status"],
            "summary": details.get("summary", "暂无新信息"), "formula_version": row["formula_version"],
        })
    return output
```

Never delete another asset or another formula version.

- [ ] **Step 4: Add the four endpoints and register the router**

Implement endpoint contracts:

```python
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
```

For `GET /importance/{score_date}`, validate `date.fromisoformat(score_date)`, read the stored daily row and its `details_json`, and return four category cards plus signals sorted by `score DESC`. For `GET /importance/{score_date}/{category}`, reject categories outside `CATEGORIES`, return the selected category score/status, formula weights, factor details, origin date for decayed data, and `public_evidence()` values for linked evidence. Return 404 for absent dates.

Modify `app/main.py`:

```python
from .routers import assets, chat, importance, research

# inside create_app(), before static file mounting
app.include_router(importance.router)
```

- [ ] **Step 5: Run backend tests and smoke-import the app**

Run:

```bash
python -m unittest tests.test_importance tests.test_importance_timeline tests.test_database_schema -v
python -c "from app.main import app; print(app.title)"
```

Expected: all tests pass and the second command prints `AI 投研助手 MVP`.

- [ ] **Step 6: Commit the timeline API**

```bash
git add app/routers/importance.py app/main.py tests/test_importance_timeline.py
git commit -m "feat: expose daily importance timeline"
```

---

### Task 5: Render the single-line timeline and three-level drill-down

**Files:**
- Create: `frontend/api.js`
- Create: `frontend/importance-chart.js`
- Create: `frontend/importance-detail.js`
- Modify: `frontend/app.js`
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: `GET /assets/{id}/importance`, daily detail, category detail, and existing evidence endpoint.
- Produces: `api(path, options)`, `streamPost(path, payload, handlers)`; `renderImportanceChart(rows, options) -> string`; `bindImportanceChart(container, handlers) -> () => void`; `dailyImportanceSheet(data, helpers) -> string`; `categoryImportanceSheet(data, helpers) -> string`.

- [ ] **Step 1: Extend the structural frontend test**

Update `tests/frontend_prototype.test.mjs` to read the three new modules and assert these markers:

```javascript
const apiModule = readFileSync(path.join(root, "frontend/api.js"), "utf8");
const importanceChart = readFileSync(path.join(root, "frontend/importance-chart.js"), "utf8");
const importanceDetail = readFileSync(path.join(root, "frontend/importance-detail.js"), "utf8");

test("importance timeline is keyboard accessible and drillable", () => {
  assert.ok(index.includes('type="module"'));
  assert.ok(app.includes('importanceRows'));
  assert.ok(app.includes('data-importance-day'));
  assert.ok(importanceChart.includes('role="button"'));
  assert.ok(importanceChart.includes('tabindex="0"'));
  assert.ok(importanceChart.includes('aria-label'));
  assert.ok(importanceChart.includes('data-importance-days'));
  assert.ok(importanceDetail.includes('data-importance-category'));
  assert.ok(importanceDetail.includes('data-source-id'));
  assert.ok(importanceDetail.includes('data-add-day-to-thesis'));
  assert.ok(apiModule.includes('export async function api'));
  assert.ok(styles.includes('.importance-timeline'));
  assert.ok(styles.includes('@media (prefers-reduced-motion: reduce)'));
});
```

- [ ] **Step 2: Run the frontend test and verify missing modules**

Run:

```bash
node --test tests/frontend_prototype.test.mjs
```

Expected: failure opening `frontend/api.js`.

- [ ] **Step 3: Extract the API client without changing behavior**

Create `frontend/api.js`:

```javascript
const API_ROOT = document.body.dataset.apiRoot || "/api";

export async function api(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text }; }
  if (!response.ok) {
    const error = new Error(body.detail || body.message || `请求失败（${response.status}）`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

export async function streamPost(path, payload, onEvent, signal) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败（${response.status}）`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((item) => item.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}
```

At the top of `frontend/app.js`, replace the local API constant/function with:

```javascript
import { api, streamPost } from "./api.js";
import { bindImportanceChart, renderImportanceChart } from "./importance-chart.js";
import { categoryImportanceSheet, dailyImportanceSheet } from "./importance-detail.js";
```

Change `frontend/index.html` to:

```html
<script type="module" src="/app.js"></script>
```

Refactor the existing SSE call sites to use `streamPost()` while preserving current pending, abort, completion, and error behavior.

- [ ] **Step 4: Implement the SVG timeline module**

Create `frontend/importance-chart.js` with fixed colors and an SVG view box of `0 0 760 230`. Use `x = 42 + index * (690 / max(rows.length - 1, 1))` and `y = 190 - score * 1.5`. Return a chart gap for `status === "incomplete"`; create one focusable `<circle>` per complete day:

```javascript
const COLORS = {
  public: "#0071e3",
  upstream: "#ff9f0a",
  market: "#af52de",
  cross_asset: "#00a6a6",
};

const LABELS = {
  public: "公开动态",
  upstream: "上下游",
  market: "行情",
  cross_asset: "跨资产",
};

export function renderImportanceChart(rows, { escapeHtml }) {
  if (!rows.length) return '<div class="importance-empty">暂时没有可计算的时间线。</div>';
  const xAt = (index) => 42 + index * (690 / Math.max(rows.length - 1, 1));
  const yAt = (score) => 190 - Number(score) * 1.5;
  const segments = [];
  let segment = [];
  rows.forEach((row, index) => {
    if (row.status === "incomplete" || row.composite_score == null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else {
      segment.push(`${xAt(index)},${yAt(row.composite_score)}`);
    }
  });
  if (segment.length) segments.push(segment);
  const paths = segments.map((points) =>
    `<polyline class="importance-line" points="${points.join(" ")}" />`
  ).join("");
  const nodes = rows.map((row, index) => {
    if (row.status === "incomplete" || row.composite_score == null) return "";
    const label = `${row.date}，综合重要性 ${Math.round(row.composite_score)}，主导类别 ${LABELS[row.dominant_category]}`;
    return `<circle class="importance-node ${row.status === "cached" ? "is-cached" : ""}"
      cx="${xAt(index)}" cy="${yAt(row.composite_score)}" r="5"
      fill="${COLORS[row.dominant_category]}" role="button" tabindex="0"
      aria-label="${escapeHtml(label)}" data-importance-day="${escapeHtml(row.date)}" />`;
  }).join("");
  return `<section class="importance-timeline" aria-label="研究重要性时间线">
    <div class="importance-heading"><div><span>研究重要性</span><strong>最近 ${rows.length} 个交易日</strong></div>
      <div class="period-control"><button type="button" data-importance-days="30">30 日</button>
        <button type="button" data-importance-days="90">90 日</button></div>
      <div class="importance-legend">${Object.entries(LABELS).map(([key, label]) =>
        `<span><i style="background:${COLORS[key]}"></i>${label}</span>`).join("")}</div></div>
    <div class="importance-chart-wrap"><svg viewBox="0 0 760 230" role="img">
      <line class="importance-grid" x1="42" y1="40" x2="732" y2="40" />
      <line class="importance-grid" x1="42" y1="115" x2="732" y2="115" />
      <line class="importance-grid" x1="42" y1="190" x2="732" y2="190" />
      ${paths}${nodes}</svg><div class="importance-tooltip" hidden></div></div>
  </section>`;
}

export function bindImportanceChart(container, { rows, onOpen, onRange, escapeHtml }) {
  const tooltip = container.querySelector(".importance-tooltip");
  const show = (node) => {
    const row = rows.find((item) => item.date === node.dataset.importanceDay);
    if (!row || !tooltip) return;
    tooltip.innerHTML = `<strong>${escapeHtml(row.date)} · ${Math.round(row.composite_score)}</strong>
      <span>${escapeHtml(row.summary)}</span>
      <small>${Object.entries(row.category_scores).map(([key, value]) =>
        `${LABELS[key]} ${Math.round(value)}`).join(" · ")}</small>`;
    tooltip.hidden = false;
  };
  const hide = () => { if (tooltip) tooltip.hidden = true; };
  const click = (event) => {
    const range = event.target.closest("[data-importance-days]");
    if (range) {
      onRange(Number(range.dataset.importanceDays));
      return;
    }
    const node = event.target.closest("[data-importance-day]");
    if (node) onOpen(node.dataset.importanceDay, node);
  };
  const keydown = (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-importance-day]")) {
      event.preventDefault();
      onOpen(event.target.dataset.importanceDay, event.target);
    }
  };
  container.addEventListener("mouseover", (event) => {
    const node = event.target.closest("[data-importance-day]");
    if (node) show(node);
  });
  container.addEventListener("focusin", (event) => {
    const node = event.target.closest("[data-importance-day]");
    if (node) show(node);
  });
  container.addEventListener("mouseleave", hide);
  container.addEventListener("focusout", hide);
  container.addEventListener("click", click);
  container.addEventListener("keydown", keydown);
  return () => {
    container.removeEventListener("click", click);
    container.removeEventListener("keydown", keydown);
  };
}
```

- [ ] **Step 5: Add timeline state and loading to `app.js`**

Add to `state`:

```javascript
importanceRows: [],
importanceDays: 30,
importanceError: "",
```

After an asset overview loads, request `/assets/${state.assetId}/importance?days=${state.importanceDays}`. Do not fail the existing overview when this request fails:

```javascript
const importance = await api(`/assets/${state.assetId}/importance?days=${state.importanceDays}`)
  .catch((error) => ({ rows: [], error: error.message }));
state.importanceRows = importance.rows || [];
state.importanceError = importance.error || "";
```

In `renderConversation()`, insert `renderImportanceChart(state.importanceRows, { escapeHtml })` immediately after `renderContextLine()`. After assigning `els.conversation.innerHTML`, call `bindImportanceChart()` with these handlers:

```javascript
bindImportanceChart(els.conversation, {
  rows: state.importanceRows,
  escapeHtml,
  onOpen: (date, trigger) => openSheet("importanceDay", trigger, { date }),
  onRange: async (days) => {
    if (days === state.importanceDays) return;
    state.importanceDays = days;
    const payload = await api(`/assets/${state.assetId}/importance?days=${days}`);
    state.importanceRows = payload.rows || [];
    renderConversation();
  },
});
```

- [ ] **Step 6: Implement daily and category sheet markup**

Create `frontend/importance-detail.js`:

```javascript
const LABELS = { public: "公开动态", upstream: "上下游", market: "行情", cross_asset: "跨资产" };

export function dailyImportanceSheet(data, { sheetHeader, escapeHtml }) {
  const cards = data.categories.map((item) => `
    <button class="importance-category-card pressable" type="button"
      data-importance-category="${escapeHtml(item.category)}">
      <span>${LABELS[item.category]}</span><strong>${Math.round(item.score)}</strong>
      <small>${escapeHtml(item.summary || "暂无新信息")}</small>
    </button>`).join("");
  return `${sheetHeader("研究重要性", `${data.date} · ${Math.round(data.composite_score)}`, true)}
    <div class="sheet-body"><div class="importance-category-grid">${cards}</div>
    <section class="detail-section"><span class="detail-eyebrow">当日关键内容</span>
      ${(data.signals || []).map((signal) => `<button class="importance-signal-row" type="button"
        data-importance-category="${escapeHtml(signal.category)}"><strong>${escapeHtml(signal.title)}</strong>
        <span>${escapeHtml(signal.summary)}</span></button>`).join("") || '<p class="muted">暂无新内容，分数来自行情或历史衰减。</p>'}
    </section><button class="secondary-button" type="button" data-add-day-to-thesis="${escapeHtml(data.date)}">用于判断草稿</button></div>`;
}

export function categoryImportanceSheet(data, { sheetHeader, escapeHtml }) {
  const factors = Object.entries(data.factors || {}).map(([name, item]) => `
    <div class="importance-factor"><span>${escapeHtml(name)}</span><strong>${Math.round(item.score)}</strong>
      <small>权重 ${Math.round(item.weight * 100)}% · 贡献 ${item.contribution.toFixed(1)}</small></div>`).join("");
  const evidence = (data.evidence || []).map((item) => `
    <button class="importance-evidence-row" type="button" data-source-id="${escapeHtml(item.evidence_id)}">
      <strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.excerpt || "当前仅有标题")}</span></button>`).join("");
  return `${sheetHeader(LABELS[data.category], `${data.date} · ${Math.round(data.score)}`, true)}
    <div class="sheet-body"><div class="importance-formula">${escapeHtml(data.formula_version)}</div>
      <div class="importance-factor-list">${factors}</div>
      <section class="detail-section"><span class="detail-eyebrow">内容与证据</span>${evidence || '<p class="muted">暂无新证据；这是基线或衰减值。</p>'}</section></div>`;
}
```

Extend `renderSheet()` in `frontend/app.js` with `importanceDay` and `importanceCategory`. Fetch daily detail when opening the first, push sheet history when opening a category, and preserve the existing source-sheet path for evidence clicks.

- [ ] **Step 7: Add restrained chart and detail styles**

Append focused rules to `frontend/styles.css`:

```css
.importance-timeline { margin: 24px 0 32px; padding: 22px; border: 1px solid var(--line); border-radius: 24px; background: rgba(255,255,255,.72); }
.importance-heading { display: flex; justify-content: space-between; gap: 20px; align-items: end; }
.importance-heading strong { display: block; margin-top: 4px; font-size: 20px; }
.importance-legend { display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); font-size: 12px; }
.importance-legend span { display: inline-flex; align-items: center; gap: 5px; }
.importance-legend i { width: 7px; height: 7px; border-radius: 50%; }
.importance-chart-wrap { position: relative; overflow-x: auto; }
.importance-chart-wrap svg { display: block; min-width: 620px; width: 100%; }
.importance-grid { stroke: rgba(60,60,67,.12); stroke-width: 1; }
.importance-line { fill: none; stroke: #1d1d1f; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 1100; animation: importance-draw 280ms ease-out both; }
.importance-node { cursor: pointer; stroke: #fff; stroke-width: 2; transition: r 150ms ease, filter 150ms ease; }
.importance-node:hover, .importance-node:focus-visible { r: 8; filter: drop-shadow(0 3px 7px rgba(0,0,0,.18)); outline: none; }
.importance-node.is-cached { fill-opacity: .45; stroke: currentColor; }
.importance-tooltip { position: absolute; z-index: 2; left: 24px; top: 18px; max-width: 360px; padding: 12px 14px; border-radius: 14px; background: rgba(29,29,31,.92); color: white; box-shadow: 0 10px 35px rgba(0,0,0,.16); }
.importance-tooltip span, .importance-tooltip small { display: block; margin-top: 4px; }
.importance-category-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.importance-category-card, .importance-signal-row, .importance-evidence-row { width: 100%; border: 1px solid var(--line); border-radius: 16px; background: var(--paper); padding: 16px; text-align: left; }
.importance-category-card strong { display: block; margin: 8px 0; font-size: 30px; }
.importance-category-card small, .importance-signal-row span, .importance-evidence-row span { display: block; margin-top: 6px; color: var(--muted); }
.importance-factor { display: grid; grid-template-columns: 1fr auto; gap: 4px 16px; padding: 13px 0; border-bottom: 1px solid var(--line); }
.importance-factor small { grid-column: 1 / -1; color: var(--muted); }
@keyframes importance-draw { from { stroke-dashoffset: 1100; } to { stroke-dashoffset: 0; } }
@media (prefers-reduced-motion: reduce) { .importance-line { animation: none; stroke-dasharray: none; } .importance-node { transition: none; } }
```

- [ ] **Step 8: Run frontend checks and commit**

Run:

```bash
node --input-type=module --check < frontend/app.js
node --input-type=module --check < frontend/api.js
node --input-type=module --check < frontend/importance-chart.js
node --input-type=module --check < frontend/importance-detail.js
node --test tests/frontend_prototype.test.mjs
```

Expected: syntax checks exit 0 and all Node tests pass.

Commit only the timeline frontend files and the intentional edits to existing frontend files:

```bash
git add frontend/api.js frontend/importance-chart.js frontend/importance-detail.js frontend/app.js frontend/index.html frontend/styles.css tests/frontend_prototype.test.mjs
git commit -m "feat: add importance timeline drill-down"
```

---

### Task 6: Generalize structured AI calls for thesis drafts

**Files:**
- Modify: `app/services/ai.py`
- Modify: `tests/test_zhipu_compat.py`

**Interfaces:**
- Consumes: existing OpenAI/Zhipu client selection and JSON parsing.
- Produces: `call_structured_model(instructions: str, context: dict, schema: dict, schema_name: str, max_tokens: int = 2400) -> dict`; existing `_call_model()` remains as a compatibility wrapper.

- [ ] **Step 1: Add a schema-forwarding compatibility test**

Append to `ZhipuCompatibilityTest`:

```python
    def test_structured_call_uses_supplied_schema(self):
        original_client = ai._client
        original_base_url = ai.settings.openai_base_url
        original_model = ai.settings.openai_model
        try:
            fake = FakeClient()
            fake.chat.completions.create = lambda **kwargs: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"已整理"}'))]
            )
            ai._client = lambda: fake
            ai.settings.openai_base_url = "https://open.bigmodel.cn/api/paas/v4/"
            ai.settings.openai_model = "glm-5.3"
            result = ai.call_structured_model(
                "整理判断", {"messages": []},
                {"type": "object", "properties": {"summary": {"type": "string"}},
                 "required": ["summary"], "additionalProperties": False},
                "thesis_draft",
            )
            self.assertEqual(result, {"summary": "已整理"})
        finally:
            ai._client = original_client
            ai.settings.openai_base_url = original_base_url
            ai.settings.openai_model = original_model
```

- [ ] **Step 2: Refactor `_call_model` into a schema-parameterized function**

Implement:

```python
def call_structured_model(
    instructions: str,
    context: dict,
    schema: dict,
    schema_name: str,
    max_tokens: int = 2400,
) -> dict:
    client = _client()
    if _uses_zhipu_chat_api():
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": (
                    f"{instructions}\n\n请严格返回 JSON，不要输出 Markdown。"
                    f"JSON 结构如下：{json.dumps(schema, ensure_ascii=False)}"
                )},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
            ],
            response_format={"type": "json_object"},
            extra_body=_zhipu_extra_body(),
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return _parse_json_response(response.choices[0].message.content)
    response = client.responses.create(
        model=settings.openai_model,
        instructions=instructions,
        input=json.dumps(context, ensure_ascii=False, default=str),
        text={"format": {"type": "json_schema", "name": schema_name,
                         "strict": True, "schema": schema}},
        temperature=0.2,
        max_output_tokens=max_tokens,
    )
    raw = getattr(response, "output_text", None)
    if not raw:
        raw = "".join(
            getattr(part, "text", "")
            for item in getattr(response, "output", []) or []
            for part in getattr(item, "content", []) or []
            if getattr(part, "type", "") in ("output_text", "text")
        )
    return _parse_json_response(raw)


def _call_model(instructions: str, context: dict) -> dict:
    return call_structured_model(instructions, context, ANALYSIS_SCHEMA, "grounded_analysis")
```

Retain the current exception-to-`AIError` mapping around both provider branches. Do not alter `run_grounded_stream()` or the validated analysis output contract.

- [ ] **Step 3: Run compatibility tests and commit**

Run:

```bash
python -m unittest tests.test_zhipu_compat -v
```

Expected: three tests pass.

Commit:

```bash
git add app/services/ai.py tests/test_zhipu_compat.py
git commit -m "refactor: support reusable structured AI output"
```

---

### Task 7: Implement thesis context, draft persistence, and atomic confirmation

**Files:**
- Create: `app/services/thesis_draft.py`
- Create: `app/routers/theses.py`
- Modify: `app/routers/assets.py`
- Modify: `app/main.py`
- Create: `tests/test_thesis_drafts.py`

**Interfaces:**
- Consumes: `call_structured_model()`, current `messages`, `analyses`, `evidence`, `theses`, and `thesis_drafts` tables.
- Produces: `default_context(asset_id) -> dict`; `validate_selection(asset_id, message_ids, evidence_ids) -> dict`; `generate_suggestion(base_version, thesis, messages, evidence) -> dict`; `confirm_draft(conn, asset_id, draft_id) -> dict`; five API endpoints from the design.

- [ ] **Step 1: Write the immutable version and idempotency test**

Create `tests/test_thesis_drafts.py` using a temporary SQLite file and patching `database.settings.db_file`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from app import database as db
from app.services.thesis_draft import confirm_draft


class ThesisDraftTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = db.settings.db_file
        self.original_ready = db._schema_ready
        db.settings.db_file = Path(self.tempdir.name) / "test.db"
        db._schema_ready = False
        db.init_db()
        now = db.utcnow()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)", (now, now),
        )
        db.execute(
            "INSERT INTO theses (asset_id, version, core_thesis, watch_variables, invalid_conditions, status, created_at) "
            "VALUES (?, 1, '原判断', '收入', '需求下降', '已由你确认', ?)", (self.asset_id, now),
        )
        self.draft_id = db.execute(
            "INSERT INTO thesis_drafts (asset_id, base_version, user_content_json, status, created_at, updated_at) "
            "VALUES (?, 1, ?, 'draft', ?, ?)",
            (self.asset_id, json.dumps({
                "core_thesis": "新判断", "watch_variables": "毛利率", "invalid_conditions": "销量下降",
                "change_summary": {"core_thesis": "modified"}, "creation_method": "ai_assisted",
            }, ensure_ascii=False), now, now),
        )

    def tearDown(self):
        db.settings.db_file = self.original_db
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def test_confirm_creates_one_new_version_and_is_idempotent(self):
        with db.get_conn() as conn:
            first = confirm_draft(conn, self.asset_id, self.draft_id)
        with db.get_conn() as conn:
            second = confirm_draft(conn, self.asset_id, self.draft_id)
        self.assertEqual(first["id"], second["id"])
        history = db.query("SELECT version, core_thesis FROM theses WHERE asset_id = ? ORDER BY version", (self.asset_id,))
        self.assertEqual(history, [
            {"version": 1, "core_thesis": "原判断"},
            {"version": 2, "core_thesis": "新判断"},
        ])
```

- [ ] **Step 2: Define and validate the AI thesis schema**

Create `app/services/thesis_draft.py` with this exact schema and the validation guards below:

```python
from __future__ import annotations

import json

from .. import database as db
from .ai import call_structured_model

ALLOWED_CHANGE_TYPES = {"added", "modified", "removed", "unchanged"}

REFERENCE_PROPERTIES = {
    "change_type": {"type": "string", "enum": sorted(ALLOWED_CHANGE_TYPES)},
    "message_ids": {"type": "array", "items": {"type": "integer"}},
    "evidence_ids": {"type": "array", "items": {"type": "string"}},
}

THESIS_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "base_version": {"type": "integer"},
        "core_thesis": {
            "type": "object",
            "properties": {
                **REFERENCE_PROPERTIES,
                "suggested_text": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["change_type", "suggested_text", "message_ids", "evidence_ids", "reason"],
            "additionalProperties": False,
        },
        "watch_variables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {**REFERENCE_PROPERTIES, "text": {"type": "string"}},
                "required": ["change_type", "text", "message_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "invalid_conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {**REFERENCE_PROPERTIES, "text": {"type": "string"}},
                "required": ["change_type", "text", "message_ids", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["base_version", "core_thesis", "watch_variables", "invalid_conditions", "summary"],
    "additionalProperties": False,
}


def validate_suggestion(result: dict, message_ids: set[int], evidence_ids: set[str]) -> dict:
    result["core_thesis"]["message_ids"] = [
        value for value in result["core_thesis"].get("message_ids", []) if value in message_ids
    ]
    result["core_thesis"]["evidence_ids"] = [
        value for value in result["core_thesis"].get("evidence_ids", []) if value in evidence_ids
    ]
    for field in ("watch_variables", "invalid_conditions"):
        cleaned = []
        for item in result.get(field, []):
            if item.get("change_type") not in ALLOWED_CHANGE_TYPES:
                continue
            item["message_ids"] = [value for value in item.get("message_ids", []) if value in message_ids]
            item["evidence_ids"] = [value for value in item.get("evidence_ids", []) if value in evidence_ids]
            item["insufficient_basis"] = not item["message_ids"] and not item["evidence_ids"]
            cleaned.append(item)
        result[field] = cleaned
    core = result["core_thesis"]
    core["insufficient_basis"] = not core["message_ids"] and not core["evidence_ids"]
    return result
```

`generate_suggestion()` must call:

```python
def generate_suggestion(
    base_version: int, thesis: dict | None, messages: list[dict], evidence: list[dict]
) -> dict:
    result = call_structured_model(
        instructions=(
            "比较用户已确认判断与所选对话、证据，只整理对判断的新增、修改、删除或不变建议。"
            "不要提供买卖、仓位、目标价或交易时点建议。每项建议必须引用输入中的消息或证据编号。"
        ),
        context={"base_version": base_version, "current_thesis": thesis,
                 "messages": messages, "evidence": evidence},
        schema=THESIS_DRAFT_SCHEMA,
        schema_name="thesis_draft",
        max_tokens=2200,
    )
    if int(result.get("base_version", -1)) != base_version:
        raise ValueError("AI 返回的判断基础版本不一致")
    core = result.get("core_thesis") or {}
    if core.get("change_type") not in ALLOWED_CHANGE_TYPES:
        raise ValueError("AI 返回了无效的判断变更类型")
    return validate_suggestion(
        result,
        {int(item["id"]) for item in messages},
        {str(item["evidence_id"]) for item in evidence},
    )
```

- [ ] **Step 3: Implement context selection and limits**

Implement default selection and ownership checks with these functions:

```python
def _rows_for_ids(table: str, id_column: str, ids: list, where: str, params: tuple) -> list[dict]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    return db.query(
        f"SELECT * FROM {table} WHERE {id_column} IN ({marks}) AND {where}",
        (*ids, *params),
    )


def default_context(asset_id: int) -> dict:
    asset = db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise LookupError("资产不存在")
    thesis = db.query_one(
        "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC LIMIT 1", (asset_id,)
    )
    if thesis:
        default_messages = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? AND created_at > ? ORDER BY created_at LIMIT 50",
            (asset_id, thesis["created_at"]),
        )
        remaining = max(0, 50 - len(default_messages))
        older = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? AND created_at <= ? ORDER BY created_at DESC LIMIT ?",
            (asset_id, thesis["created_at"], remaining),
        )
        older.reverse()
        messages = older + default_messages
    else:
        messages = db.query(
            "SELECT id, role, content, event_id, analysis_id, created_at FROM messages "
            "WHERE asset_id = ? ORDER BY created_at DESC LIMIT 50", (asset_id,),
        )
        messages.reverse()
        default_messages = messages[-20:]
    evidence_ids = {row["event_id"] for row in default_messages if row.get("event_id")}
    analysis_ids = [row["analysis_id"] for row in default_messages if row.get("analysis_id")]
    if analysis_ids:
        marks = ",".join("?" for _ in analysis_ids)
        analyses = db.query(
            f"SELECT event_id FROM analyses WHERE asset_id = ? AND id IN ({marks})",
            (asset_id, *analysis_ids),
        )
        evidence_ids.update(row["event_id"] for row in analyses if row.get("event_id"))
    evidence = db.query(
        "SELECT * FROM evidence WHERE stock_code = ? "
        "ORDER BY CASE source_level WHEN 'primary' THEN 0 ELSE 1 END, "
        "COALESCE(published_at, fetched_at) DESC LIMIT 30",
        (asset["stock_code"],),
    )
    draft = db.query_one(
        "SELECT * FROM thesis_drafts WHERE asset_id = ? AND status = 'draft' "
        "ORDER BY updated_at DESC LIMIT 1", (asset_id,),
    )
    if draft:
        defaults = {
            "selected_message_ids_json": [], "selected_evidence_ids_json": [],
            "ai_suggestion_json": {}, "user_content_json": {},
        }
        for field, default in defaults.items():
            draft[field.removesuffix("_json")] = json.loads(draft.get(field) or json.dumps(default))
    default_message_ids = [row["id"] for row in default_messages]
    available_evidence_ids = {row["evidence_id"] for row in evidence}
    default_evidence_ids = [value for value in evidence_ids if value in available_evidence_ids][:30]
    return {
        "current_thesis": thesis,
        "base_version": int((thesis or {}).get("version", 0)),
        "messages": messages,
        "evidence": evidence[:30],
        "selected_message_ids": (draft or {}).get("selected_message_ids", default_message_ids),
        "selected_evidence_ids": (draft or {}).get("selected_evidence_ids", default_evidence_ids),
        "draft": draft,
    }


def validate_selection(asset_id: int, message_ids: list[int], evidence_ids: list[str]) -> dict:
    if len(message_ids) > 50 or len(evidence_ids) > 30:
        raise ValueError("最多选择 50 条消息和 30 条证据")
    asset = db.query_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    if not asset:
        raise LookupError("资产不存在")
    messages = _rows_for_ids("messages", "id", message_ids, "asset_id = ?", (asset_id,))
    evidence = _rows_for_ids(
        "evidence", "evidence_id", evidence_ids, "stock_code = ?", (asset["stock_code"],)
    )
    if {row["id"] for row in messages} != set(message_ids):
        raise LookupError("所选消息不属于当前标的")
    if {row["evidence_id"] for row in evidence} != set(evidence_ids):
        raise LookupError("所选证据不属于当前标的")
    messages.sort(key=lambda row: row["created_at"])
    return {"messages": messages, "evidence": evidence}
```

The router maps `ValueError` to HTTP 400 and `LookupError` to HTTP 404.

- [ ] **Step 4: Implement atomic confirmation**

In `confirm_draft(conn, asset_id, draft_id)`, perform all reads and writes using the supplied connection:

```python
def confirm_draft(conn, asset_id: int, draft_id: int) -> dict:
    draft = conn.execute(
        "SELECT * FROM thesis_drafts WHERE id = ? AND asset_id = ?", (draft_id, asset_id)
    ).fetchone()
    if not draft:
        raise ValueError("判断草稿不存在")
    draft = dict(draft)
    if draft["status"] == "confirmed" and draft["confirmed_thesis_id"]:
        return dict(conn.execute("SELECT * FROM theses WHERE id = ?", (draft["confirmed_thesis_id"],)).fetchone())
    latest = conn.execute(
        "SELECT * FROM theses WHERE asset_id = ? ORDER BY version DESC LIMIT 1", (asset_id,)
    ).fetchone()
    latest_version = int(latest["version"]) if latest else 0
    if latest_version != int(draft["base_version"]):
        raise RuntimeError("判断版本已更新，请基于最新版重新整理")
    content = json.loads(draft["user_content_json"] or "{}")
    core = str(content.get("core_thesis") or "").strip()
    if not core:
        raise ValueError("核心判断不能为空")
    cursor = conn.execute(
        "INSERT INTO theses (asset_id, version, core_thesis, watch_variables, invalid_conditions, "
        "status, created_at, change_summary_json, source_message_ids_json, source_evidence_ids_json, "
        "creation_method, base_version) VALUES (?, ?, ?, ?, ?, '已由你确认', ?, ?, ?, ?, ?, ?)",
        (asset_id, latest_version + 1, core, str(content.get("watch_variables") or "").strip(),
         str(content.get("invalid_conditions") or "").strip(), db.utcnow(),
         json.dumps(content.get("change_summary") or {}, ensure_ascii=False),
         draft["selected_message_ids_json"], draft["selected_evidence_ids_json"],
         content.get("creation_method") or "ai_assisted", latest_version),
    )
    conn.execute(
        "UPDATE thesis_drafts SET status = 'confirmed', confirmed_thesis_id = ?, updated_at = ? WHERE id = ?",
        (cursor.lastrowid, db.utcnow(), draft_id),
    )
    return dict(conn.execute("SELECT * FROM theses WHERE id = ?", (cursor.lastrowid,)).fetchone())
```

Map `RuntimeError` to HTTP 409 and `ValueError` to HTTP 400 in the router.

- [ ] **Step 5: Add thesis draft routes and keep manual thesis compatibility**

Create `app/routers/theses.py` with:

```python
router = APIRouter(prefix="/api/assets/{asset_id}")

class DraftGenerateRequest(BaseModel):
    message_ids: list[int] = Field(max_length=50)
    evidence_ids: list[str] = Field(max_length=30)

class DraftUpdateRequest(BaseModel):
    message_ids: list[int] = Field(max_length=50)
    evidence_ids: list[str] = Field(max_length=30)
    user_content: dict

@router.get("/thesis-draft/context")
def thesis_context(asset_id: int) -> dict:
    _asset_row(asset_id)
    return default_context(asset_id)

@router.post("/thesis-drafts/{draft_id}/confirm")
def confirm_thesis_draft(asset_id: int, draft_id: int) -> dict:
    _asset_row(asset_id)
    try:
        with db.get_conn() as conn:
            thesis = confirm_draft(conn, asset_id, draft_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"thesis": thesis}
```

Add the generator and update handlers. Import `AIError`, `_current_thesis`, `_sse_response`, `generate_suggestion`, and `validate_selection` at the top of the router:

```python
def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/thesis-drafts/generate")
def generate_thesis_draft(asset_id: int, payload: DraftGenerateRequest):
    _asset_row(asset_id)
    try:
        selected = validate_selection(asset_id, payload.message_ids, payload.evidence_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    thesis = _current_thesis(asset_id)
    base_version = int((thesis or {}).get("version", 0))

    def events():
        yield _sse_event({"status": "context_ready"})
        try:
            yield _sse_event({"status": "model_running"})
            suggestion = generate_suggestion(
                base_version, thesis, selected["messages"], selected["evidence"]
            )
            yield _sse_event({"status": "validating"})
            current_content = {
                "core_thesis": (thesis or {}).get("core_thesis", ""),
                "watch_variables": (thesis or {}).get("watch_variables", ""),
                "invalid_conditions": (thesis or {}).get("invalid_conditions", ""),
                "change_summary": {},
                "creation_method": "ai_assisted",
            }
            now = db.utcnow()
            existing = db.query_one(
                "SELECT id FROM thesis_drafts WHERE asset_id = ? AND status = 'draft' "
                "ORDER BY updated_at DESC LIMIT 1", (asset_id,),
            )
            values = (
                base_version, json.dumps(payload.message_ids), json.dumps(payload.evidence_ids),
                json.dumps(suggestion, ensure_ascii=False),
                json.dumps(current_content, ensure_ascii=False), now,
            )
            if existing:
                db.execute(
                    "UPDATE thesis_drafts SET base_version = ?, selected_message_ids_json = ?, "
                    "selected_evidence_ids_json = ?, ai_suggestion_json = ?, user_content_json = ?, "
                    "updated_at = ? WHERE id = ?",
                    (*values, existing["id"]),
                )
                draft_id = existing["id"]
            else:
                draft_id = db.execute(
                    "INSERT INTO thesis_drafts (asset_id, base_version, selected_message_ids_json, "
                    "selected_evidence_ids_json, ai_suggestion_json, user_content_json, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
                    (asset_id, base_version, json.dumps(payload.message_ids),
                     json.dumps(payload.evidence_ids), json.dumps(suggestion, ensure_ascii=False),
                     json.dumps(current_content, ensure_ascii=False), now, now),
                )
            draft = db.query_one("SELECT * FROM thesis_drafts WHERE id = ?", (draft_id,))
            draft["selected_message_ids"] = json.loads(draft["selected_message_ids_json"])
            draft["selected_evidence_ids"] = json.loads(draft["selected_evidence_ids_json"])
            draft["ai_suggestion"] = json.loads(draft["ai_suggestion_json"])
            draft["user_content"] = json.loads(draft["user_content_json"])
            yield _sse_event({"status": "completed", "draft": draft})
        except AIError as exc:
            yield _sse_event({"status": "failed", "category": exc.category, "message": str(exc)})
        except Exception as exc:
            yield _sse_event({"status": "failed", "category": "unknown", "message": str(exc)})

    return _sse_response(events())


@router.put("/thesis-drafts/{draft_id}")
def update_thesis_draft(asset_id: int, draft_id: int, payload: DraftUpdateRequest) -> dict:
    _asset_row(asset_id)
    try:
        validate_selection(asset_id, payload.message_ids, payload.evidence_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    draft = db.query_one(
        "SELECT * FROM thesis_drafts WHERE id = ? AND asset_id = ?", (draft_id, asset_id)
    )
    if not draft:
        raise HTTPException(status_code=404, detail="判断草稿不存在")
    if draft["status"] != "draft":
        raise HTTPException(status_code=409, detail="该判断草稿已经结束")
    core = str(payload.user_content.get("core_thesis") or "").strip()
    if len(core) > 2000:
        raise HTTPException(status_code=400, detail="核心判断不能超过 2000 字")
    db.execute(
        "UPDATE thesis_drafts SET selected_message_ids_json = ?, selected_evidence_ids_json = ?, "
        "user_content_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(payload.message_ids), json.dumps(payload.evidence_ids),
         json.dumps(payload.user_content, ensure_ascii=False), db.utcnow(), draft_id),
    )
    return {"draft": db.query_one("SELECT * FROM thesis_drafts WHERE id = ?", (draft_id,))}
```

Modify the existing manual `create_thesis()` insert in `app/routers/assets.py` to set `creation_method = 'manual'` and `base_version = current.version or 0`. Extend `list_theses()` to JSON-decode the three metadata fields before returning them.

Register the new router in `app/main.py`:

```python
from .routers import assets, chat, importance, research, theses

app.include_router(theses.router)
```

- [ ] **Step 6: Run thesis and compatibility tests**

Run:

```bash
python -m unittest tests.test_thesis_drafts tests.test_zhipu_compat tests.test_database_schema -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit the thesis backend**

```bash
git add app/services/thesis_draft.py app/routers/theses.py app/routers/assets.py app/main.py tests/test_thesis_drafts.py
git commit -m "feat: add AI-assisted thesis version workflow"
```

---

### Task 8: Build the conversation-to-thesis review interface

**Files:**
- Create: `frontend/thesis-workflow.js`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: thesis context, generate SSE, draft update, confirmation, and thesis history endpoints.
- Produces: `thesisContextSheet(model, helpers) -> string`; `thesisReviewSheet(model, helpers) -> string`; `thesisHistorySheet(history, helpers) -> string`; `collectThesisForm(root) -> object`; `suggestionValue(draft, field) -> string`.

- [ ] **Step 1: Add workflow markers to the frontend test**

Append:

```javascript
const thesisWorkflow = readFileSync(path.join(root, "frontend/thesis-workflow.js"), "utf8");

test("conversation conclusions require user confirmation before versioning", () => {
  assert.ok(app.includes("data-build-thesis-draft"));
  assert.ok(app.includes("thesisDraft"));
  assert.ok(thesisWorkflow.includes("data-thesis-message"));
  assert.ok(thesisWorkflow.includes("data-thesis-evidence"));
  assert.ok(thesisWorkflow.includes("data-accept-thesis-field"));
  assert.ok(thesisWorkflow.includes("data-confirm-thesis-version"));
  assert.ok(thesisWorkflow.includes("历史记录"));
  assert.ok(styles.includes(".thesis-draft-banner"));
});
```

- [ ] **Step 2: Run the test and verify the module is absent**

Run:

```bash
node --test tests/frontend_prototype.test.mjs
```

Expected: failure opening `frontend/thesis-workflow.js`.

- [ ] **Step 3: Implement scope, review, and history renderers**

Create `frontend/thesis-workflow.js` with escaped text supplied by `helpers.escapeHtml`. The context screen must render every message and evidence as a checked checkbox using these attributes:

```javascript
export function thesisContextSheet(model, { sheetHeader, escapeHtml }) {
  const messages = model.messages.map((item) => `
    <label class="thesis-scope-row"><input type="checkbox" data-thesis-message value="${item.id}"
      ${model.selected_message_ids.includes(item.id) ? "checked" : ""}>
      <span><strong>${item.role === "user" ? "我" : "AI"}</strong>${escapeHtml(item.content)}</span></label>`).join("");
  const evidence = model.evidence.map((item) => `
    <label class="thesis-scope-row"><input type="checkbox" data-thesis-evidence
      value="${escapeHtml(item.evidence_id)}" ${model.selected_evidence_ids.includes(item.evidence_id) ? "checked" : ""}>
      <span><strong>证据</strong>${escapeHtml(item.title)}</span></label>`).join("");
  return `${sheetHeader("维护我的判断", `基于 v${model.base_version}`, true)}<div class="sheet-body">
    <div class="thesis-scope-summary">已选择 ${model.selected_message_ids.length} 条对话 · ${model.selected_evidence_ids.length} 条证据</div>
    <section class="detail-section"><span class="detail-eyebrow">对话范围</span>${messages}</section>
    <section class="detail-section"><span class="detail-eyebrow">证据范围</span>${evidence || '<p class="muted">所选对话没有关联证据。</p>'}</section>
    <button class="primary-button" type="button" data-generate-thesis-draft>生成判断草稿</button></div>`;
}

export function thesisReviewSheet(model, { sheetHeader, escapeHtml }) {
  const value = (field) => escapeHtml(model.user_content[field] || "");
  return `${sheetHeader("维护我的判断", "AI 整理的修改建议", true)}<div class="sheet-body">
    <div class="archive-tabs"><button class="archive-tab" aria-selected="true">待确认草稿</button>
      <button class="archive-tab" type="button" data-thesis-history>历史记录</button></div>
    <form id="thesis-draft-form" class="sheet-form">
      <label>核心判断<textarea name="core_thesis" required>${value("core_thesis")}</textarea>
        <button type="button" class="text-button" data-accept-thesis-field="core_thesis">采纳修改</button></label>
      <label>重点观察<textarea name="watch_variables">${value("watch_variables")}</textarea>
        <button type="button" class="text-button" data-accept-thesis-field="watch_variables">采纳修改</button></label>
      <label>判断失效条件<textarea name="invalid_conditions">${value("invalid_conditions")}</textarea>
        <button type="button" class="text-button" data-accept-thesis-field="invalid_conditions">采纳修改</button></label>
      <button class="primary-button" type="submit" data-confirm-thesis-version>确认并保存为 v${model.base_version + 1}</button>
    </form></div>`;
}

export function thesisHistorySheet(history, { sheetHeader, escapeHtml }) {
  return `${sheetHeader("判断历史", "结构化版本", true)}<div class="sheet-body history-list">
    ${history.map((item) => `<article class="history-item"><strong>v${item.version} · ${escapeHtml(item.created_at.slice(0, 10))}</strong>
      <p>${escapeHtml(item.core_thesis)}</p><small>${item.creation_method === "ai_assisted" ? "AI 辅助整理" : "手动编辑"}</small>
    </article>`).join("")}</div>`;
}

export function collectThesisForm(root) {
  const form = new FormData(root);
  return {
    core_thesis: String(form.get("core_thesis") || "").trim(),
    watch_variables: String(form.get("watch_variables") || "").trim(),
    invalid_conditions: String(form.get("invalid_conditions") || "").trim(),
  };
}

export function suggestionValue(draft, field) {
  const suggestion = draft.ai_suggestion || {};
  if (field === "core_thesis") return suggestion.core_thesis?.suggested_text || "";
  return (suggestion[field] || [])
    .filter((item) => item.change_type !== "removed" && !item.insufficient_basis)
    .map((item) => item.text)
    .join("\n");
}
```

The renderer may add source-count buttons beside each field, but every such button must open only IDs returned by the backend; it may not synthesize source references in the browser.

- [ ] **Step 4: Add workflow state and the conversation banner**

Import the module and add state:

```javascript
import {
  collectThesisForm, suggestionValue, thesisContextSheet, thesisHistorySheet, thesisReviewSheet,
} from "./thesis-workflow.js";

// state fields
thesisContext: null,
thesisDraft: null,
thesisDraftPending: false,
thesisSelectedEvidence: new Set(),
thesisAcceptedChanges: {},
```

Count assistant messages created after the current thesis `created_at`. When at least one exists, append this immediately before the composer region in the conversation content:

```javascript
function renderThesisDraftBanner() {
  const thesisDate = state.overview?.thesis?.created_at || "";
  const eligible = (state.overview?.messages || []).filter(
    (message) => message.role === "assistant" && (!thesisDate || message.created_at > thesisDate)
  );
  if (!eligible.length) return "";
  return `<aside class="thesis-draft-banner"><div><strong>本轮对话形成了 ${eligible.length} 个可沉淀观点</strong>
    <span>整理前可增删对话与证据范围</span></div>
    <button class="secondary-button" type="button" data-build-thesis-draft>整理为判断草稿</button></aside>`;
}
```

The banner opens `sheetView = { type: "thesisContext" }`, loads `/assets/${assetId}/thesis-draft/context`, then renders. Existing “编辑我的判断” continues to open the manual form.

- [ ] **Step 5: Wire generation, autosave, acceptance, confirmation, and history**

Required transitions in `frontend/app.js`:

```javascript
async function openThesisContext(trigger) {
  state.thesisContext = await api(`/assets/${state.assetId}/thesis-draft/context`);
  openSheet("thesisContext", trigger);
}

async function addImportanceDayToThesis(date, trigger) {
  const [context, day] = await Promise.all([
    api(`/assets/${state.assetId}/thesis-draft/context`),
    api(`/assets/${state.assetId}/importance/${date}`),
  ]);
  const added = (day.signals || []).flatMap((signal) => signal.evidence_ids || []);
  context.selected_evidence_ids = [...new Set([
    ...(context.selected_evidence_ids || []), ...added,
  ])].slice(0, 30);
  state.thesisContext = context;
  openSheet("thesisContext", trigger);
}

async function generateThesisDraft() {
  const messageIds = [...els.sheet.querySelectorAll("[data-thesis-message]:checked")].map((item) => Number(item.value));
  const evidenceIds = [...els.sheet.querySelectorAll("[data-thesis-evidence]:checked")].map((item) => item.value);
  state.thesisDraftPending = true;
  await streamPost(`/assets/${state.assetId}/thesis-drafts/generate`, {
    message_ids: messageIds, evidence_ids: evidenceIds,
  }, (event) => {
    if (event.status === "completed") {
      state.thesisDraft = event.draft;
      state.sheetView = { type: "thesisReview" };
      renderSheet();
    }
    if (event.status === "failed") throw new Error(event.message || "判断草稿生成失败");
  });
  state.thesisDraftPending = false;
}
```

In the existing delegated sheet click handler, route `[data-add-day-to-thesis]` to `addImportanceDayToThesis(button.dataset.addDayToThesis, button)`. This only updates the selection shown in the draft context; the user must still click “生成判断草稿” and later confirm a version.

When accepting a field, run this handler; it copies only the backend suggestion, records the accepted change type, and does not save a confirmed thesis:

```javascript
function acceptThesisField(button) {
  const field = button.dataset.acceptThesisField;
  const textarea = els.sheet.querySelector(`[name="${field}"]`);
  if (!textarea || !state.thesisDraft) return;
  textarea.value = suggestionValue(state.thesisDraft, field);
  const suggestion = state.thesisDraft.ai_suggestion || {};
  state.thesisAcceptedChanges[field] = field === "core_thesis"
    ? suggestion.core_thesis?.change_type || "unchanged"
    : (suggestion[field] || []).map((item) => item.change_type);
  button.textContent = "已采纳 ✓";
}
```

On input blur and before closing the sheet, `PUT` the current selected IDs and `user_content`. On form submit:

```javascript
const content = collectThesisForm(event.currentTarget);
if (!content.core_thesis) {
  showToast("请先填写核心判断", "error");
  return;
}
content.change_summary = state.thesisAcceptedChanges;
content.creation_method = "ai_assisted";
await api(`/assets/${state.assetId}/thesis-drafts/${state.thesisDraft.id}`, {
  method: "PUT",
  body: JSON.stringify({
    message_ids: state.thesisDraft.selected_message_ids,
    evidence_ids: state.thesisDraft.selected_evidence_ids,
    user_content: content,
  }),
});
await api(`/assets/${state.assetId}/thesis-drafts/${state.thesisDraft.id}/confirm`, { method: "POST" });
await loadOverview();
state.sheetView = { type: "thesisHistory" };
renderSheet();
showToast("已保存新的判断版本", "success");
```

If confirmation returns 409, keep the draft open and show the backend message. Do not retry confirmation automatically.

- [ ] **Step 6: Add workflow styles and responsive scrolling**

Append:

```css
.thesis-draft-banner { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin: 28px 0 8px; padding: 16px 18px; border-radius: 18px; background: rgba(0,113,227,.07); }
.thesis-draft-banner span { display: block; margin-top: 4px; color: var(--muted); font-size: 13px; }
.thesis-scope-summary { position: sticky; top: 0; z-index: 2; padding: 10px 12px; border-radius: 12px; background: var(--paper); color: var(--muted); }
.thesis-scope-row { display: grid; grid-template-columns: auto 1fr; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.thesis-scope-row input { margin-top: 3px; }
.thesis-scope-row strong { display: block; margin-bottom: 4px; }
.history-item small { color: var(--muted); }
@media (max-width: 720px) { .thesis-draft-banner { align-items: stretch; flex-direction: column; } }
```

Keep `.sheet-body { overflow-y: auto; min-height: 0; }` and the previously fixed `.conversation-scroll` behavior intact.

- [ ] **Step 7: Run frontend checks and commit**

Run:

```bash
node --input-type=module --check < frontend/app.js
node --input-type=module --check < frontend/thesis-workflow.js
node --test tests/frontend_prototype.test.mjs
```

Expected: syntax checks exit 0 and all Node tests pass.

Commit:

```bash
git add frontend/thesis-workflow.js frontend/app.js frontend/styles.css tests/frontend_prototype.test.mjs
git commit -m "feat: turn conversations into thesis versions"
```

---

### Task 9: Run the executable MVP path and update handoff documentation

**Files:**
- Modify: `README.md`
- Modify only if integration reveals a blocker: files created or modified in Tasks 1–8

**Interfaces:**
- Consumes: all timeline and thesis APIs/UI.
- Produces: a developer can pull, configure `.env`, start the app, inspect the timeline, and save a new thesis version.

- [ ] **Step 1: Run the narrow automated verification set**

Run:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall -q app
node --input-type=module --check < frontend/app.js
node --input-type=module --check < frontend/api.js
node --input-type=module --check < frontend/importance-chart.js
node --input-type=module --check < frontend/importance-detail.js
node --input-type=module --check < frontend/thesis-workflow.js
node --test tests/frontend_prototype.test.mjs
```

Expected: Python and Node tests pass; syntax and compile commands exit 0.

- [ ] **Step 2: Start on a non-conflicting port**

Run:

```bash
PORT=8010 ./start.sh
```

If `start.sh` does not honor `PORT`, update it to use `${PORT:-8000}` and rerun. Expected terminal output includes `Uvicorn running on http://127.0.0.1:8010`.

- [ ] **Step 3: Verify the backend path with one existing asset**

Open `http://127.0.0.1:8010/api/assets`. Take the first asset ID and request:

```text
GET /api/assets/{asset_id}/importance?days=30
GET /api/assets/{asset_id}/importance/{latest_date}
GET /api/assets/{asset_id}/importance/{latest_date}/market
GET /api/assets/{asset_id}/thesis-draft/context
```

Expected:

- Timeline has one row per available trading date and complete rows have four category scores.
- Daily detail has four clickable category payloads.
- Market detail has factor scores and `formula_version = "importance-v1"`.
- Thesis context returns current version and selected message/evidence IDs without exposing another asset.

- [ ] **Step 4: Verify the browser interaction path**

Open `http://127.0.0.1:8010/` and perform exactly this path:

```text
选择标的
→ 查看 30 日单折线
→ 悬停一个节点并看到四类分数
→ 点击节点
→ 依次打开公开动态、上下游、行情、跨资产四类卡片
→ 从有证据的类别打开一条原始来源
→ 返回主页面发送一个问题
→ 点击“整理为判断草稿”
→ 取消一条消息后生成草稿
→ 编辑核心判断
→ 确认保存
→ 在历史记录中看到日期和递增版本号
```

Expected: no blocked scrolling, no automatic thesis overwrite, and no console error that prevents the path.

- [ ] **Step 5: Update README with the two new capabilities**

Add a “下一阶段 MVP 能力” section documenting:

```markdown
## 下一阶段 MVP 能力

- 研究重要性时间线：按交易日汇总公开动态、上下游、行情和跨资产四类重要性。折线高度表示等权综合分，节点颜色表示当日主导类别。分数代表研究注意力，不代表涨跌或买卖建议。
- 判断沉淀：可将上次确认版本之后的对话与证据整理为草稿。AI 只提出字段级建议，用户确认后才创建带日期的新版本，历史版本不会被覆盖。

时间线首次打开会基于本地已有行情和证据生成最近 30 个交易日数据。若 8000 端口已被占用，可运行 `PORT=8010 ./start.sh`。
```

- [ ] **Step 6: Commit final integration fixes and documentation**

Stage only README and files intentionally changed to resolve blockers found in Steps 1–4:

```bash
git add README.md
git commit -m "docs: document importance timeline and thesis workflow"
```

Do not push until the user explicitly asks to push.

## Final acceptance checklist

- [ ] A trading day with valid market data produces a continuous line point and four displayed category scores.
- [ ] Public, upstream, and cross-asset missing history shows baseline 5 with “暂无新信息,” not invented content.
- [ ] Hover/focus shows the composite, four scores, and one summary.
- [ ] Every category card is clickable and exposes factors, weights, contributions, content, and real evidence where present.
- [ ] A score can be traced from composite to category to factor to evidence.
- [ ] Draft defaults to messages after the latest confirmed thesis and lets the user adjust the range.
- [ ] Invalid AI JSON or out-of-range citations does not create a confirmed thesis.
- [ ] Confirmation creates exactly one higher version and keeps all prior versions.
- [ ] Main conversation and right sheet remain scrollable.
- [ ] The documented startup command works on a free local port.
