# TradingBuddy Public Dynamics Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a source-aware local public-dynamics pipeline that preserves TradingBuddy's current main view while exposing every collected official announcement and media event from the latest rolling 24 hours.

**Architecture:** Three isolated source adapters emit one normalized `RawDynamic` contract. A synchronization service applies 90-day initial backfill, 24-hour overlap, conservative aggregation, source-health tracking, and transactional persistence into SQLite; API and UI layers read only the canonical dynamics model. Announcement text extraction is a separate on-demand service with domain, size, redirect, and PDF validation.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Pydantic 2, httpx, AKShare, PyMuPDF, native HTML/CSS/JavaScript, `unittest`, Node test runner.

## Global Constraints

- Personal local single-user deployment only.
- Initial sync covers the latest 90 natural days; later syncs overlap the last successful source timestamp by 24 hours.
- Automatic refresh runs only when the selected asset has no complete sync or its last complete sync is older than 24 hours.
- A failed automatic attempt has a 30-minute retry cooldown; explicit manual refresh bypasses freshness and cooldown.
- Official completeness requires either CNInfo or Eastmoney Notices to succeed; media completeness requires Eastmoney News to succeed.
- The rolling feed window is exactly 24 hours and must not hide low-importance collected items.
- Collection, normalization, deduplication, scoring, and PDF extraction must not call an LLM.
- Media articles persist only title, source-provided excerpt, publisher, time, and original link.
- PDF extraction allows only configured hosts, rejects non-PDF and oversized responses, follows only validated redirects, and performs no OCR.
- Existing evidence rows remain the source-level audit record; canonical dynamics link to, rather than replace, `evidence`.
- Preserve the existing main-page interaction structure and current visual language.
- Preserve the current uncommitted visitor-AI work in `app/services/thesis_draft.py`, `frontend/app.js`, and `requirements.txt`; merge incrementally and never overwrite it.
- Before editing those three files, save their current diff for comparison. When a feature task touches `frontend/app.js` or `requirements.txt`, use interactive hunk staging (`git add -p`, splitting hunks when needed) and inspect `git diff --cached` so the feature commit contains only public-dynamics changes. Never stage `app/services/thesis_draft.py`.
- Do not stage or commit `.superpowers/`, `deploy/`, or `docs/superpowers/plans/2026-09-13-tradingbuddy-multi-terminal-agent-development.md` as part of this feature.

---

## File Structure

### New backend files

- `app/services/public_dynamics_types.py`: source-neutral dataclasses and constants only.
- `app/services/public_dynamics_sources.py`: CNInfo, Eastmoney Notices, and Eastmoney News adapters; no database access.
- `app/services/public_dynamics_aggregate.py`: pure normalization, classification, deduplication, clustering, and importance functions.
- `app/services/public_dynamics.py`: sync decisions, concurrent adapter execution, transactional persistence, queries, and source-health summaries.
- `app/services/document_text.py`: allowlisted PDF download and PyMuPDF extraction.
- `app/routers/public_dynamics.py`: 24-hour feed, detail, extraction, and source-status endpoints.

### New frontend files

- `frontend/public-dynamics.js`: 24-hour feed and canonical dynamic detail markup.

### Modified files

- `app/database.py`: four canonical dynamics tables and indexes.
- `app/main.py`: include the new router.
- `app/routers/assets.py`: conditionally sync public dynamics and serialize the most important canonical dynamics into the existing overview shape.
- `app/routers/importance.py`: expose the latest 24-hour public count on the public category card.
- `app/routers/research.py`: analyze all evidence attached to a canonical dynamic while retaining legacy `event_id` support.
- `app/routers/chat.py`: accept optional canonical dynamic context for follow-up questions.
- `frontend/app.js`: load the new sheets, route public-category clicks, and start analysis with `dynamic_id`; preserve current request-generation guards.
- `frontend/importance-detail.js`: label the public category with the 24-hour item count.
- `frontend/styles.css`: public-dynamics list, status, filter, and detail styles.
- `requirements.txt`: add PyMuPDF without removing the current `httpx` dependency.
- `README.md`: document sources, completeness semantics, refresh windows, and PDF extraction limits.

### New tests and fixtures

- `tests/test_public_dynamics_schema.py`
- `tests/test_public_dynamics_sources.py`
- `tests/test_public_dynamics_aggregate.py`
- `tests/test_public_dynamics_sync.py`
- `tests/test_public_dynamics_api.py`
- `tests/test_document_text.py`
- `tests/test_public_dynamics_research.py`
- `tests/frontend_public_dynamics.test.mjs`
- `tests/fixtures/public_dynamics/cninfo_page.json`
- `tests/fixtures/public_dynamics/eastmoney_notices.json`
- `tests/fixtures/public_dynamics/eastmoney_news.json`
- `tests/fixtures/public_dynamics/searchable.pdf`

---

### Task 1: Canonical Types and SQLite Schema

**Files:**
- Create: `app/services/public_dynamics_types.py`
- Modify: `app/database.py:74-148`
- Create: `tests/test_public_dynamics_schema.py`
- Modify: `tests/test_database_schema.py`

**Interfaces:**
- Produces: `RawDynamic`, `ProviderResult`, `DynamicCluster`, `SyncDecision`, `PROVIDER_*`, `PUBLIC_DYNAMICS_FORMULA_VERSION`.
- Produces tables: `public_dynamics`, `public_dynamic_evidence`, `source_sync_state`, `public_dynamics_sync_state`, `document_cache`.
- Consumes: existing `assets(id)` and `evidence(evidence_id)` foreign keys.

- [ ] **Step 1: Add a failing schema test**

Create `tests/test_public_dynamics_schema.py`:

```python
import sqlite3
import unittest

from app import database


class PublicDynamicsSchemaTest(unittest.TestCase):
    def test_schema_creates_public_dynamics_tables_and_indexes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        database.ensure_schema(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({
            "public_dynamics",
            "public_dynamic_evidence",
            "source_sync_state",
            "public_dynamics_sync_state",
            "document_cache",
        }.issubset(tables))

        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(public_dynamics)")
        }
        self.assertTrue({
            "canonical_key",
            "importance_factors_json",
            "conflict_status",
        }.issubset(columns))

        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(public_dynamics)")
        }
        self.assertIn("idx_public_dynamics_asset_time", indexes)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the schema test and verify the missing-table failure**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_schema.py -v
```

Expected: FAIL because `public_dynamics` does not exist.

- [ ] **Step 3: Define the source-neutral types**

Create `app/services/public_dynamics_types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

PROVIDER_CNINFO = "cninfo"
PROVIDER_EASTMONEY_NOTICES = "eastmoney_notices"
PROVIDER_EASTMONEY_NEWS = "eastmoney_news"
OFFICIAL_PROVIDERS = frozenset({PROVIDER_CNINFO, PROVIDER_EASTMONEY_NOTICES})
MEDIA_PROVIDERS = frozenset({PROVIDER_EASTMONEY_NEWS})
PUBLIC_DYNAMICS_FORMULA_VERSION = "public-dynamics-v1"

ProviderStatus = Literal["success", "empty", "failed"]
DynamicKind = Literal["announcement", "news"]


@dataclass(frozen=True)
class RawDynamic:
    provider: str
    provider_item_id: str
    stock_code: str
    kind: DynamicKind
    category: str
    title: str
    excerpt: str
    published_at: str
    publisher: str
    source_url: str
    document_url: str | None = None
    source_level: Literal["primary", "secondary"] = "secondary"
    content_status: Literal["title_only", "excerpt", "full"] = "title_only"
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    status: ProviderStatus
    items: tuple[RawDynamic, ...]
    attempted_at: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DynamicCluster:
    canonical_key: str
    kind: DynamicKind
    category: str
    title: str
    summary: str
    published_at: str
    importance_score: float
    importance_factors: dict[str, float]
    content_status: str
    conflict_status: Literal["none", "possible"]
    members: tuple[RawDynamic, ...]


@dataclass(frozen=True)
class SyncDecision:
    should_sync: bool
    reason: str
```

- [ ] **Step 4: Add the canonical schema**

Insert these statements in `SCHEMA` in `app/database.py` after `thesis_drafts` and before `kv`:

```sql
CREATE TABLE IF NOT EXISTS public_dynamics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('announcement', 'news')),
    category TEXT NOT NULL,
    canonical_title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    importance_score REAL NOT NULL,
    importance_factors_json TEXT NOT NULL DEFAULT '{}',
    formula_version TEXT NOT NULL DEFAULT 'public-dynamics-v1',
    content_status TEXT NOT NULL DEFAULT 'title_only'
        CHECK (content_status IN ('title_only', 'excerpt', 'full')),
    conflict_status TEXT NOT NULL DEFAULT 'none'
        CHECK (conflict_status IN ('none', 'possible')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (asset_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS public_dynamic_evidence (
    dynamic_id INTEGER NOT NULL REFERENCES public_dynamics(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK (relation IN ('primary', 'corroborating', 'related')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (dynamic_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS source_sync_state (
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL,
    last_success_at TEXT,
    last_status TEXT NOT NULL CHECK (last_status IN ('success', 'empty', 'failed')),
    last_error_code TEXT,
    last_error_message TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (asset_id, provider)
);

CREATE TABLE IF NOT EXISTS public_dynamics_sync_state (
    asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    last_attempt_at TEXT NOT NULL,
    last_complete_at TEXT,
    last_status TEXT NOT NULL CHECK (last_status IN ('complete', 'partial', 'failed')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_cache (
    evidence_id TEXT PRIMARY KEY REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    document_url TEXT NOT NULL,
    document_hash TEXT,
    mime_type TEXT,
    byte_size INTEGER,
    extraction_status TEXT NOT NULL
        CHECK (extraction_status IN ('pending', 'extracted', 'unsupported', 'failed')),
    extracted_text TEXT NOT NULL DEFAULT '',
    extracted_at TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL
);
```

Add these indexes near the existing index block:

```sql
CREATE INDEX IF NOT EXISTS idx_public_dynamics_asset_time
    ON public_dynamics(asset_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_public_dynamic_evidence_evidence
    ON public_dynamic_evidence(evidence_id);
CREATE INDEX IF NOT EXISTS idx_source_sync_state_asset
    ON source_sync_state(asset_id, provider);
```

- [ ] **Step 5: Run schema and existing migration tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_schema.py tests/test_database_schema.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the schema boundary**

```bash
git add app/database.py app/services/public_dynamics_types.py tests/test_public_dynamics_schema.py tests/test_database_schema.py
git commit -m "feat: add public dynamics data model"
```

---

### Task 2: Source Adapters and Deterministic Fixtures

**Files:**
- Create: `app/services/public_dynamics_sources.py`
- Create: `tests/test_public_dynamics_sources.py`
- Create: `tests/fixtures/public_dynamics/cninfo_page.json`
- Create: `tests/fixtures/public_dynamics/eastmoney_notices.json`
- Create: `tests/fixtures/public_dynamics/eastmoney_news.json`

**Interfaces:**
- Consumes: `RawDynamic`, `ProviderResult`, provider constants from Task 1.
- Produces: `SourceAdapter.fetch(stock_code: str, start: datetime, end: datetime, attempted_at: str) -> ProviderResult`.
- Produces: `CninfoAnnouncementAdapter`, `EastmoneyNoticeAdapter`, `EastmoneyNewsAdapter`.
- No database or AI imports are permitted in this file.

- [ ] **Step 1: Add deterministic fixture payloads**

Create `tests/fixtures/public_dynamics/cninfo_page.json`:

```json
{
  "totalAnnouncement": 1,
  "announcements": [
    {
      "announcementId": "1212345678",
      "announcementTitle": "关于收到上海证券交易所监管工作函的公告",
      "announcementTime": 1789404060000,
      "adjunctUrl": "finalpage/2026-09-15/1212345678.PDF",
      "secCode": "600519",
      "secName": "贵州茅台",
      "orgId": "gssh0600519"
    }
  ]
}
```

Create `tests/fixtures/public_dynamics/eastmoney_notices.json`:

```json
[
  {
    "代码": "600519",
    "名称": "贵州茅台",
    "公告标题": "关于收到上海证券交易所监管工作函的公告",
    "公告类型": "风险提示",
    "公告日期": "2026-09-15",
    "网址": "https://data.eastmoney.com/notices/detail/600519/AN123.html"
  }
]
```

Create `tests/fixtures/public_dynamics/eastmoney_news.json`:

```json
[
  {
    "关键词": "贵州茅台",
    "新闻标题": "贵州茅台回应近期渠道政策调整",
    "新闻内容": "公司就近期渠道政策调整回应市场关注。",
    "发布时间": "2026-09-15 07:58:00",
    "文章来源": "证券时报",
    "新闻链接": "https://example.test/news/maotai-channel"
  }
]
```

- [ ] **Step 2: Write failing adapter tests with fake clients**

Create `tests/test_public_dynamics_sources.py`:

```python
import json
import unittest
from datetime import datetime
from pathlib import Path

from app.services.public_dynamics_sources import (
    CninfoAnnouncementAdapter,
    EastmoneyNewsAdapter,
    EastmoneyNoticeAdapter,
)

FIXTURES = Path(__file__).parent / "fixtures" / "public_dynamics"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, page):
        self.page = page

    def get(self, url, **kwargs):
        if url.endswith("szse_stock.json"):
            return FakeResponse({"stockList": [{"code": "600519", "orgId": "gssh0600519"}]})
        raise AssertionError(url)

    def post(self, url, **kwargs):
        return FakeResponse(self.page)


class FakeAk:
    def __init__(self, notices, news):
        self.notices = notices
        self.news = news

    def stock_individual_notice_report(self, **kwargs):
        import pandas as pd
        return pd.DataFrame(self.notices)

    def stock_news_em(self, **kwargs):
        import pandas as pd
        return pd.DataFrame(self.news)


class PublicDynamicsSourcesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cninfo = json.loads((FIXTURES / "cninfo_page.json").read_text())
        cls.notices = json.loads((FIXTURES / "eastmoney_notices.json").read_text())
        cls.news = json.loads((FIXTURES / "eastmoney_news.json").read_text())
        cls.start = datetime(2026, 6, 17)
        cls.end = datetime(2026, 9, 15, 9, 32)

    def test_cninfo_preserves_pdf_and_primary_source(self):
        result = CninfoAnnouncementAdapter(FakeHttpClient(self.cninfo)).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        self.assertEqual(result.status, "success")
        item = result.items[0]
        self.assertEqual(item.provider_item_id, "1212345678")
        self.assertEqual(item.source_level, "primary")
        self.assertEqual(
            item.document_url,
            "https://static.cninfo.com.cn/finalpage/2026-09-15/1212345678.PDF",
        )

    def test_eastmoney_adapters_preserve_category_and_original_publisher(self):
        fake = FakeAk(self.notices, self.news)
        notices = EastmoneyNoticeAdapter(fake).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        news = EastmoneyNewsAdapter(fake).fetch(
            "600519", self.start, self.end, "2026-09-15T09:32:00+08:00"
        )
        self.assertEqual(notices.items[0].category, "风险提示")
        self.assertEqual(news.items[0].publisher, "证券时报")
        self.assertEqual(news.items[0].kind, "news")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the adapter tests and verify the import failure**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_sources.py -v
```

Expected: FAIL because `public_dynamics_sources` does not exist.

- [ ] **Step 4: Implement adapters with dependency injection**

Create `app/services/public_dynamics_sources.py` with these public classes and helpers:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

import httpx

from .public_dynamics_types import (
    PROVIDER_CNINFO,
    PROVIDER_EASTMONEY_NEWS,
    PROVIDER_EASTMONEY_NOTICES,
    ProviderResult,
    RawDynamic,
)


class SourceAdapter(Protocol):
    provider: str

    def fetch(
        self, stock_code: str, start: datetime, end: datetime, attempted_at: str
    ) -> ProviderResult: ...


def _string(value) -> str:
    return "" if value is None else str(value).strip()


def _iso(value) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(_string(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc).astimezone()
    return parsed.isoformat(timespec="seconds")


def _failed(provider: str, attempted_at: str, exc: Exception) -> ProviderResult:
    return ProviderResult(
        provider=provider,
        status="failed",
        items=(),
        attempted_at=attempted_at,
        error_code=exc.__class__.__name__,
        error_message=str(exc)[:300],
    )


class CninfoAnnouncementAdapter:
    provider = PROVIDER_CNINFO

    def __init__(self, client: httpx.Client):
        self.client = client

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            stock_response = self.client.get(
                "https://www.cninfo.com.cn/new/data/szse_stock.json",
                timeout=12.0,
            )
            stock_response.raise_for_status()
            stock_map = {
                item["code"]: item["orgId"]
                for item in stock_response.json().get("stockList", [])
            }
            org_id = stock_map[stock_code]
            page_num = 1
            items = []
            while True:
                response = self.client.post(
                    "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                    data={
                        "pageNum": page_num,
                        "pageSize": 30,
                        "column": "szse",
                        "tabName": "fulltext",
                        "stock": f"{stock_code},{org_id}",
                        "seDate": f"{start:%Y-%m-%d}~{end:%Y-%m-%d}",
                        "isHLtitle": "true",
                    },
                    headers={"Referer": "https://www.cninfo.com.cn/"},
                    timeout=12.0,
                )
                response.raise_for_status()
                payload = response.json()
                announcements = payload.get("announcements") or []
                for row in announcements:
                    timestamp = datetime.fromtimestamp(
                        int(row["announcementTime"]) / 1000,
                        tz=timezone.utc,
                    ).astimezone()
                    adjunct = _string(row.get("adjunctUrl")).lstrip("/")
                    announcement_id = _string(row.get("announcementId"))
                    items.append(RawDynamic(
                        provider=self.provider,
                        provider_item_id=announcement_id,
                        stock_code=stock_code,
                        kind="announcement",
                        category="",
                        title=_string(row.get("announcementTitle")),
                        excerpt="",
                        published_at=timestamp.isoformat(timespec="seconds"),
                        publisher="巨潮资讯网",
                        source_url=(
                            "https://www.cninfo.com.cn/new/disclosure/detail?"
                            f"stockCode={stock_code}&announcementId={announcement_id}"
                            f"&orgId={org_id}&announcementTime={timestamp:%Y-%m-%d}"
                        ),
                        document_url=(
                            f"https://static.cninfo.com.cn/{adjunct}" if adjunct else None
                        ),
                        source_level="primary",
                        content_status="title_only",
                        raw_metadata={"org_id": org_id},
                    ))
                total = int(payload.get("totalAnnouncement") or 0)
                if page_num * 30 >= total:
                    break
                page_num += 1
            return ProviderResult(
                self.provider,
                "success" if items else "empty",
                tuple(items),
                attempted_at,
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)


class EastmoneyNoticeAdapter:
    provider = PROVIDER_EASTMONEY_NOTICES

    def __init__(self, ak_module):
        self.ak = ak_module

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            frame = self.ak.stock_individual_notice_report(
                security=stock_code,
                symbol="全部",
                begin_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
            items = tuple(RawDynamic(
                provider=self.provider,
                provider_item_id=_string(row.get("网址") or row.get("公告标题")),
                stock_code=stock_code,
                kind="announcement",
                category=_string(row.get("公告类型")),
                title=_string(row.get("公告标题")),
                excerpt="",
                published_at=_iso(row.get("公告日期")),
                publisher="东方财富公告",
                source_url=_string(row.get("网址")),
                source_level="primary",
                content_status="title_only",
            ) for _, row in frame.iterrows() if _string(row.get("公告标题")))
            return ProviderResult(
                self.provider, "success" if items else "empty", items, attempted_at
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)


class EastmoneyNewsAdapter:
    provider = PROVIDER_EASTMONEY_NEWS

    def __init__(self, ak_module):
        self.ak = ak_module

    def fetch(self, stock_code, start, end, attempted_at):
        try:
            frame = self.ak.stock_news_em(symbol=stock_code)
            items = []
            for _, row in frame.iterrows():
                published_at = _iso(row.get("发布时间"))
                published = datetime.fromisoformat(published_at)
                if not (start.astimezone(published.tzinfo) <= published <= end.astimezone(published.tzinfo)):
                    continue
                title = _string(row.get("新闻标题"))
                if not title:
                    continue
                excerpt = _string(row.get("新闻内容"))
                items.append(RawDynamic(
                    provider=self.provider,
                    provider_item_id=_string(row.get("新闻链接") or title),
                    stock_code=stock_code,
                    kind="news",
                    category="媒体报道",
                    title=title,
                    excerpt=excerpt,
                    published_at=published_at,
                    publisher=_string(row.get("文章来源")) or "来源信息不完整",
                    source_url=_string(row.get("新闻链接")),
                    source_level="secondary",
                    content_status="excerpt" if excerpt else "title_only",
                ))
            result_items = tuple(items)
            return ProviderResult(
                self.provider,
                "success" if result_items else "empty",
                result_items,
                attempted_at,
            )
        except Exception as exc:
            return _failed(self.provider, attempted_at, exc)
```

- [ ] **Step 5: Run adapters and full backend tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_sources.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: adapter tests PASS; existing tests remain PASS.

- [ ] **Step 6: Commit the source boundary**

```bash
git add app/services/public_dynamics_sources.py tests/test_public_dynamics_sources.py tests/fixtures/public_dynamics
git commit -m "feat: add public dynamics source adapters"
```

---

### Task 3: Pure Classification, Aggregation, and Importance

**Files:**
- Create: `app/services/public_dynamics_aggregate.py`
- Create: `tests/test_public_dynamics_aggregate.py`

**Interfaces:**
- Consumes: `RawDynamic` from Task 1.
- Produces: `classify_announcement(title: str, source_category: str) -> str`.
- Produces: `aggregate_raw_dynamics(items: list[RawDynamic]) -> list[DynamicCluster]`.
- Produces: `normalize_title`, `evidence_identity`, and deterministic factor scores.
- This file is pure: no network, database, filesystem, or AI imports.

- [ ] **Step 1: Write failing aggregation tests**

Create `tests/test_public_dynamics_aggregate.py`:

```python
import unittest

from app.services.public_dynamics_aggregate import aggregate_raw_dynamics
from app.services.public_dynamics_types import RawDynamic


def item(provider, item_id, title, published, kind="announcement", excerpt=""):
    return RawDynamic(
        provider=provider,
        provider_item_id=item_id,
        stock_code="600519",
        kind=kind,
        category="风险提示" if kind == "announcement" else "媒体报道",
        title=title,
        excerpt=excerpt,
        published_at=published,
        publisher="巨潮资讯网" if provider == "cninfo" else "证券时报",
        source_url=f"https://example.test/{item_id}",
        source_level="primary" if kind == "announcement" else "secondary",
        content_status="excerpt" if excerpt else "title_only",
    )


class PublicDynamicsAggregateTest(unittest.TestCase):
    def test_same_announcement_across_sources_merges_and_preserves_members(self):
        rows = [
            item("cninfo", "1", "关于收到监管工作函的公告", "2026-09-15T08:41:00+08:00"),
            item("eastmoney_notices", "2", "关于收到监管工作函的公告", "2026-09-15T00:00:00+08:00"),
        ]
        clusters = aggregate_raw_dynamics(rows)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0].members), 2)
        self.assertEqual(clusters[0].category, "监管问询、处罚与风险提示")

    def test_different_numbers_do_not_merge(self):
        rows = [
            item("eastmoney_news", "1", "公司签订10亿元合同", "2026-09-15T08:00:00+08:00", "news"),
            item("eastmoney_news", "2", "公司签订12亿元合同", "2026-09-15T08:05:00+08:00", "news"),
        ]
        self.assertEqual(len(aggregate_raw_dynamics(rows)), 2)

    def test_low_importance_items_are_returned(self):
        rows = [item("cninfo", "1", "董事会会议决议公告", "2026-09-15T08:00:00+08:00")]
        cluster = aggregate_raw_dynamics(rows)[0]
        self.assertGreaterEqual(cluster.importance_score, 0)
        self.assertLessEqual(cluster.importance_score, 100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run and verify the missing-module failure**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_aggregate.py -v
```

Expected: FAIL because `public_dynamics_aggregate` does not exist.

- [ ] **Step 3: Implement conservative pure aggregation**

Create `app/services/public_dynamics_aggregate.py` with these exact public functions and rules:

```python
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime

from .public_dynamics_types import (
    DynamicCluster,
    RawDynamic,
)

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
    return {normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))}


def _similar(left: RawDynamic, right: RawDynamic) -> bool:
    if left.stock_code != right.stock_code or left.kind != right.kind:
        return False
    if _numbers(left.title) != _numbers(right.title):
        return False
    left_time = datetime.fromisoformat(left.published_at)
    right_time = datetime.fromisoformat(right.published_at)
    if left.kind == "announcement":
        return left_time.date() == right_time.date() and normalize_title(left.title) == normalize_title(right.title)
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
    category = classify_announcement(title, members[0].category) if members[0].kind == "announcement" else "媒体报道"
    materiality = 90.0 if category == "监管问询、处罚与风险提示" else 75.0 if category != "其他公告" else 45.0
    return {
        "authority": 95.0 if primary else 65.0,
        "materiality": materiality,
        "relevance": 100.0,
        "completeness": 90.0 if full else 70.0 if excerpt else 45.0,
    }


def aggregate_raw_dynamics(items: list[RawDynamic]) -> list[DynamicCluster]:
    groups: list[list[RawDynamic]] = []
    for candidate in sorted(items, key=lambda item: item.published_at, reverse=True):
        group = next((row for row in groups if _similar(row[0], candidate)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    clusters = []
    for members in groups:
        lead = max(members, key=lambda item: (item.source_level == "primary", len(item.excerpt)))
        factors = _factor_scores(members)
        score = round(
            factors["authority"] * 0.30
            + factors["materiality"] * 0.30
            + factors["relevance"] * 0.20
            + factors["completeness"] * 0.20,
            1,
        )
        key_seed = f"{lead.stock_code}|{lead.kind}|{normalize_title(lead.title)}|{lead.published_at[:10]}"
        clusters.append(DynamicCluster(
            canonical_key=hashlib.sha1(key_seed.encode("utf-8")).hexdigest(),
            kind=lead.kind,
            category=(classify_announcement(lead.title, lead.category) if lead.kind == "announcement" else "媒体报道"),
            title=lead.title,
            summary=max((item.excerpt for item in members), key=len, default=""),
            published_at=max(item.published_at for item in members),
            importance_score=score,
            importance_factors=factors,
            content_status=("full" if any(item.content_status == "full" for item in members) else "excerpt" if any(item.content_status == "excerpt" for item in members) else "title_only"),
            conflict_status="none",
            members=tuple(members),
        ))
    return sorted(clusters, key=lambda cluster: cluster.published_at, reverse=True)
```

- [ ] **Step 4: Run aggregation tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_aggregate.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the pure domain logic**

```bash
git add app/services/public_dynamics_aggregate.py tests/test_public_dynamics_aggregate.py
git commit -m "feat: aggregate public dynamics conservatively"
```

---

### Task 4: Freshness Decisions, Concurrent Sync, and Transactional Persistence

**Files:**
- Create: `app/services/public_dynamics.py`
- Create: `tests/test_public_dynamics_sync.py`

**Interfaces:**
- Consumes: source adapters and `aggregate_raw_dynamics`.
- Produces: `decide_sync(state: dict | None, force: bool, now: datetime) -> SyncDecision`.
- Produces: `sync_public_dynamics(asset: dict, force: bool = False, now: datetime | None = None, adapters: tuple[SourceAdapter, ...] | None = None) -> dict`.
- Produces: `list_public_dynamics(asset_id: int, start: datetime, end: datetime, kind: str = "all", limit: int | None = None) -> list[dict]`, `get_public_dynamic`, `source_status`, `dynamic_evidence`.

- [ ] **Step 1: Write failing freshness and failure-isolation tests**

Create `tests/test_public_dynamics_sync.py` with a temporary database setup matching `tests/test_thesis_drafts.py`, then add:

```python
from datetime import datetime, timedelta, timezone

from app.services.public_dynamics import decide_sync, sync_public_dynamics
from app.services.public_dynamics_types import ProviderResult, RawDynamic


class FakeAdapter:
    def __init__(self, provider, result):
        self.provider = provider
        self.result = result
        self.calls = 0

    def fetch(self, stock_code, start, end, attempted_at):
        self.calls += 1
        return self.result


def test_decide_sync_obeys_24_hours_and_30_minute_failure_cooldown(self):
    now = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    fresh = {
        "last_complete_at": (now - timedelta(hours=23)).isoformat(),
        "last_attempt_at": (now - timedelta(hours=23)).isoformat(),
        "last_status": "complete",
    }
    assert decide_sync(fresh, False, now).should_sync is False
    stale = {**fresh, "last_complete_at": (now - timedelta(hours=25)).isoformat()}
    assert decide_sync(stale, False, now).should_sync is True
    failed = {
        **stale,
        "last_attempt_at": (now - timedelta(minutes=10)).isoformat(),
        "last_status": "failed",
    }
    assert decide_sync(failed, False, now).should_sync is False
    assert decide_sync(failed, True, now).should_sync is True
    partial = {**failed, "last_status": "partial"}
    assert decide_sync(partial, False, now).should_sync is False
```

Add a `unittest.TestCase` method that supplies a successful CNInfo result, a failed Eastmoney Notices result, and a successful Eastmoney News result; assert the returned status is `complete`, because one official provider plus media succeeded. Add a second method with both official providers failed and media successful; assert `partial`, media evidence persists, and `last_complete_at` remains null.

- [ ] **Step 2: Run and verify the missing-module failure**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_sync.py -v
```

Expected: FAIL because `public_dynamics` does not exist.

- [ ] **Step 3: Implement sync decisions and query boundaries**

Create `app/services/public_dynamics.py`. The freshness function must be exactly:

```python
def decide_sync(state: dict | None, force: bool, now: datetime) -> SyncDecision:
    if force:
        return SyncDecision(True, "manual")
    if not state or not state.get("last_complete_at"):
        if state and state.get("last_status") in {"partial", "failed"}:
            attempted = datetime.fromisoformat(state["last_attempt_at"])
            if now.astimezone(attempted.tzinfo) - attempted < timedelta(minutes=30):
                return SyncDecision(False, "failure_cooldown")
        return SyncDecision(True, "never_complete")
    completed = datetime.fromisoformat(state["last_complete_at"])
    if now.astimezone(completed.tzinfo) - completed <= timedelta(hours=24):
        return SyncDecision(False, "fresh")
    if state.get("last_status") in {"partial", "failed"}:
        attempted = datetime.fromisoformat(state["last_attempt_at"])
        if now.astimezone(attempted.tzinfo) - attempted < timedelta(minutes=30):
            return SyncDecision(False, "failure_cooldown")
    return SyncDecision(True, "stale")
```

Implement these private helpers in the same file:

```python
def _provider_start(asset_id: int, provider: str, now: datetime) -> datetime:
    row = db.query_one(
        "SELECT last_success_at FROM source_sync_state WHERE asset_id = ? AND provider = ?",
        (asset_id, provider),
    )
    if row and row.get("last_success_at"):
        return datetime.fromisoformat(row["last_success_at"]) - timedelta(hours=24)
    return now - timedelta(days=90)


def _channel_status(results: list[ProviderResult]) -> str:
    successful = {result.provider for result in results if result.status in {"success", "empty"}}
    official_ok = bool(successful & OFFICIAL_PROVIDERS)
    media_ok = MEDIA_PROVIDERS.issubset(successful)
    if official_ok and media_ok:
        return "complete"
    if successful:
        return "partial"
    return "failed"
```

Implement `sync_public_dynamics` with `ThreadPoolExecutor(max_workers=3)`. Each adapter receives its own `_provider_start`. Gather all `ProviderResult` values before opening a write transaction. In one `db.get_conn()` transaction:

1. Upsert source results into `source_sync_state`.
2. Save each `RawDynamic` through `make_evidence` and `save_evidence` semantics, but execute against the same connection so the full aggregation can roll back. Put `provider`, `provider_item_id`, `document_url`, and `raw_metadata` inside `evidence.raw`.
3. Run `aggregate_raw_dynamics` for all successful items.
4. Upsert `public_dynamics` by `(asset_id, canonical_key)`.
5. Add or update `public_dynamic_evidence` rows for every cluster member; mark the first primary source as `primary`, other same-event evidence as `corroborating`. Membership updates are additive during incremental and partial syncs: never delete an existing evidence link merely because one provider failed or omitted an older item from the current response.
6. Upsert `public_dynamics_sync_state`; update `last_complete_at` only when `_channel_status` is `complete`.

Return:

```python
{
    "status": status,
    "decision": decision.reason,
    "synced": True,
    "providers": [serialize_provider_result(result) for result in results],
    "last_complete_at": last_complete_at,
}
```

When `decide_sync` is false, return the persisted status with `"synced": False` and do not call an adapter.

Implement `list_public_dynamics(asset_id, start, end, kind="all", limit=None)` with explicit UTC start/end bounds, SQL ordered by `published_at DESC`, and no `LIMIT` unless the caller explicitly supplies one. Map `official` to `kind='announcement'`, `media` to `kind='news'`, and reject any other non-`all` value. Implement `get_public_dynamic` and `dynamic_evidence` with joins to `evidence` and JSON parsing.

- [ ] **Step 4: Run sync and aggregate tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_sync.py tests/test_public_dynamics_aggregate.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Verify no AI dependency enters the sync layer**

Run:

```bash
rg -n "openai|call_structured_model|run_grounded_stream|_call_model" app/services/public_dynamics.py app/services/public_dynamics_sources.py app/services/public_dynamics_aggregate.py
```

Expected: no output.

- [ ] **Step 6: Commit synchronization**

```bash
git add app/services/public_dynamics.py tests/test_public_dynamics_sync.py
git commit -m "feat: sync public dynamics with source health"
```

---

### Task 5: Public Dynamics API and 24-Hour Completeness Response

**Files:**
- Create: `app/routers/public_dynamics.py`
- Modify: `app/main.py:7-20`
- Modify: `app/routers/importance.py:256-285`
- Create: `tests/test_public_dynamics_api.py`

**Interfaces:**
- Consumes: query functions from Task 4.
- Produces: `GET /api/assets/{asset_id}/public-dynamics`.
- Produces: `GET /api/assets/{asset_id}/public-dynamics/source-status`.
- Produces: `GET /api/public-dynamics/{dynamic_id}`.
- Adds `recent_count_24h` to the `public` category in `daily_importance`.

- [ ] **Step 1: Write failing FastAPI endpoint tests**

Create `tests/test_public_dynamics_api.py` using `fastapi.testclient.TestClient`, the temporary database pattern from `tests/test_thesis_drafts.py`, and seeded dynamics at 2, 12, and 30 hours before a fixed time. Patch `app.routers.public_dynamics.utcnow` to the fixed time. Assert:

```python
response = client.get(f"/api/assets/{asset_id}/public-dynamics?hours=24&kind=all")
self.assertEqual(response.status_code, 200)
body = response.json()
self.assertEqual(body["counts"], {"all": 2, "official": 1, "media": 1})
self.assertEqual(len(body["items"]), 2)
self.assertIn("window_start", body)
self.assertIn("window_end", body)
self.assertIn("source_status", body)
```

Also assert `kind=official` returns one announcement, `kind=unsupported` returns 422, and an unknown dynamic returns 404.

- [ ] **Step 2: Run and verify route failures**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_api.py -v
```

Expected: FAIL because the endpoints are missing.

- [ ] **Step 3: Add the router**

Create `app/routers/public_dynamics.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .. import database as db
from ..services.public_dynamics import (
    get_public_dynamic,
    list_public_dynamics,
    source_status,
)
from .assets import _asset_row

router = APIRouter(prefix="/api")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/assets/{asset_id}/public-dynamics")
def public_dynamics_feed(
    asset_id: int,
    hours: int = Query(24, ge=24, le=24),
    kind: Literal["all", "official", "media"] = "all",
) -> dict:
    _asset_row(asset_id)
    end = utcnow()
    start = end - timedelta(hours=hours)
    all_items = list_public_dynamics(asset_id, start, end, kind="all")
    official = [item for item in all_items if item["kind"] == "announcement"]
    media = [item for item in all_items if item["kind"] == "news"]
    selected = all_items if kind == "all" else official if kind == "official" else media
    return {
        "window_start": start.astimezone().isoformat(timespec="seconds"),
        "window_end": end.astimezone().isoformat(timespec="seconds"),
        "counts": {"all": len(all_items), "official": len(official), "media": len(media)},
        "items": selected,
        "source_status": source_status(asset_id),
    }


@router.get("/assets/{asset_id}/public-dynamics/source-status")
def public_dynamics_source_status(asset_id: int) -> dict:
    _asset_row(asset_id)
    return source_status(asset_id)


@router.get("/public-dynamics/{dynamic_id}")
def public_dynamic_detail(dynamic_id: int) -> dict:
    item = get_public_dynamic(dynamic_id)
    if not item:
        raise HTTPException(status_code=404, detail="公开动态不存在")
    return {"dynamic": item, "fetched_at": db.utcnow()}
```

Import and include this router in `app/main.py` after `importance.router`.

- [ ] **Step 4: Add the 24-hour count to the daily importance response**

In `daily_importance` in `app/routers/importance.py`, compute:

```python
from datetime import datetime, timedelta, timezone
from ..services.public_dynamics import list_public_dynamics

now = datetime.now(timezone.utc)
public_count = len(list_public_dynamics(asset_id, now - timedelta(hours=24), now, kind="all"))
```

Add `"recent_count_24h": public_count if category == "public" else None` to each category payload. This count augments the card; it does not change the importance formula.

- [ ] **Step 5: Run API and full backend tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_api.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit the read API**

```bash
git add app/routers/public_dynamics.py app/routers/importance.py app/main.py tests/test_public_dynamics_api.py
git commit -m "feat: expose complete 24 hour public dynamics"
```

---

### Task 6: Safe On-Demand PDF Extraction

**Files:**
- Create: `app/services/document_text.py`
- Modify: `app/routers/public_dynamics.py`
- Modify: `requirements.txt`
- Create: `tests/test_document_text.py`
- Create: `tests/fixtures/public_dynamics/searchable.pdf`

**Interfaces:**
- Produces: `extract_dynamic_document(dynamic_id: int, client: httpx.Client | None = None) -> dict`.
- Produces: `POST /api/public-dynamics/{dynamic_id}/extract`.
- Consumes: `document_url` from primary announcement evidence raw metadata.

- [ ] **Step 1: Add PyMuPDF without removing concurrent visitor-AI dependencies**

Append this line to the current `requirements.txt`, retaining `httpx>=0.27`:

```text
PyMuPDF>=1.24
```

Install only the new dependency in the existing virtual environment:

```bash
.venv/bin/python -m pip install 'PyMuPDF>=1.24'
```

Expected: installation succeeds and `import fitz` exits zero.

- [ ] **Step 2: Create a small deterministic searchable PDF fixture**

Run this one-time fixture-generation command:

```bash
.venv/bin/python -c "import fitz; d=fitz.open(); p=d.new_page(); p.insert_text((72,72),'TradingBuddy public announcement fixture'); d.save('tests/fixtures/public_dynamics/searchable.pdf')"
```

Expected: the fixture exists and is below 20 KB.

- [ ] **Step 3: Write failing document safety tests**

Create `tests/test_document_text.py`. Use a fake `httpx.Client` whose response exposes `status_code`, `headers`, `content`, and `raise_for_status`. Test:

```python
from app.services.document_text import DocumentRejected, extract_pdf_bytes, validate_url


def test_validate_url_rejects_unlisted_host(self):
    with self.assertRaises(DocumentRejected):
        validate_url("http://127.0.0.1/private.pdf")


def test_extract_pdf_bytes_reads_searchable_text(self):
    content = (FIXTURES / "searchable.pdf").read_bytes()
    result = extract_pdf_bytes(content)
    self.assertIn("TradingBuddy public announcement fixture", result["text"])
    self.assertEqual(result["status"], "extracted")


def test_extract_pdf_bytes_rejects_non_pdf(self):
    with self.assertRaises(DocumentRejected):
        extract_pdf_bytes(b"<html>not pdf</html>")
```

Add tests for a response declaring more than 20 MB, a redirect to an unlisted host, and a PDF with no extracted text returning `unsupported`.

- [ ] **Step 4: Run and verify missing-module failure**

Run:

```bash
.venv/bin/python -m unittest tests/test_document_text.py -v
```

Expected: FAIL because `document_text` does not exist.

- [ ] **Step 5: Implement allowlisted PDF extraction**

Create `app/services/document_text.py` with:

```python
from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin, urlparse

import fitz
import httpx

from .. import database as db

ALLOWED_DOCUMENT_HOSTS = frozenset({
    "static.cninfo.com.cn",
    "www.cninfo.com.cn",
    "data.eastmoney.com",
    "pdf.dfcfw.com",
})
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_PAGES = 120
MAX_EXTRACTED_CHARS = 200_000


class DocumentRejected(RuntimeError):
    pass


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOCUMENT_HOSTS:
        raise DocumentRejected("公告地址不在允许列表中")
    return url


def extract_pdf_bytes(content: bytes) -> dict:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentRejected("公告文件超过 20 MB")
    if not content.startswith(b"%PDF"):
        raise DocumentRejected("响应内容不是 PDF")
    document = fitz.open(stream=content, filetype="pdf")
    try:
        text = "\n".join(
            document.load_page(index).get_text("text")
            for index in range(min(document.page_count, MAX_DOCUMENT_PAGES))
        ).strip()[:MAX_EXTRACTED_CHARS]
    finally:
        document.close()
    return {
        "status": "extracted" if text else "unsupported",
        "text": text,
        "hash": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
        "mime_type": "application/pdf",
    }


def _download(client: httpx.Client, url: str) -> bytes:
    current = validate_url(url)
    for _ in range(4):
        response = client.get(current, timeout=20.0, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            current = validate_url(urljoin(current, response.headers["location"]))
            continue
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        if declared > MAX_DOCUMENT_BYTES:
            raise DocumentRejected("公告文件超过 20 MB")
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type not in {"application/pdf", "application/octet-stream"}:
            raise DocumentRejected("公告响应类型不是 PDF")
        return response.content
    raise DocumentRejected("公告重定向次数过多")
```

Implement `extract_dynamic_document` to:

1. Return an existing `document_cache` row with `extraction_status='extracted'` unchanged.
2. Select the primary announcement evidence attached to the dynamic.
3. Read `document_url` from `evidence.raw`; raise `DocumentRejected` if absent.
4. Download and extract with `_download` and `extract_pdf_bytes`.
5. Upsert `document_cache` for success, unsupported, or failure.
6. On success, update `evidence.excerpt`, `evidence.content_status='full'`, and the parent `public_dynamics.content_status='full'` in one transaction.
7. Never include local paths or raw response bodies in `error_message`.

- [ ] **Step 6: Add the extraction endpoint**

In `app/routers/public_dynamics.py`:

```python
@router.post("/public-dynamics/{dynamic_id}/extract")
def extract_public_dynamic(dynamic_id: int) -> dict:
    if not get_public_dynamic(dynamic_id):
        raise HTTPException(status_code=404, detail="公开动态不存在")
    try:
        return extract_dynamic_document(dynamic_id)
    except DocumentRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="公告正文暂时无法获取") from exc
```

- [ ] **Step 7: Run document and backend tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_document_text.py tests/test_public_dynamics_api.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit document extraction**

```bash
git add app/services/document_text.py app/routers/public_dynamics.py tests/test_document_text.py tests/fixtures/public_dynamics/searchable.pdf
git add -p requirements.txt
git diff --cached -- requirements.txt
git commit -m "feat: extract announcement text safely"
```

Expected cached `requirements.txt` diff: only `PyMuPDF>=1.24`; the pre-existing `httpx>=0.27` hunk remains owned by the visitor-AI work unless it has already been committed separately.

---

### Task 7: Overview Refresh and Evidence-Aware Research Compatibility

**Files:**
- Modify: `app/routers/assets.py:156-238`
- Modify: `app/routers/research.py:19-86`
- Modify: `app/routers/chat.py:21-130`
- Create: `tests/test_public_dynamics_research.py`

**Interfaces:**
- Consumes: `sync_public_dynamics`, `list_public_dynamics`, `dynamic_evidence`.
- Produces overview events with both legacy `event_id` and canonical `dynamic_id`.
- Extends `ResearchRequest` and `ChatRequest` with optional `dynamic_id: int`.
- Retains legacy `event_id` behavior for stored data and old frontend calls.

- [ ] **Step 1: Write failing overview and research context tests**

Create `tests/test_public_dynamics_research.py` with temporary database data containing one dynamic linked to two evidence rows. Patch the sync function and `run_grounded_stream`. Assert:

```python
response = client.post("/api/research/stream", json={
    "asset_id": self.asset_id,
    "event_id": self.primary_evidence_id,
    "dynamic_id": self.dynamic_id,
})
self.assertEqual(response.status_code, 200)
self.assertEqual(
    {item["evidence_id"] for item in captured["evidence_items"]},
    {self.primary_evidence_id, self.secondary_evidence_id},
)
```

Add an overview test asserting the first event has `dynamic_id`, preserves a real evidence `event_id`, and contains `source_count=2`.

- [ ] **Step 2: Run and verify request/model failures**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_research.py -v
```

Expected: FAIL because requests do not accept `dynamic_id` and overview does not expose it.

- [ ] **Step 3: Integrate conditional sync into overview without removing market data**

In `app/routers/assets.py`, import:

```python
from datetime import datetime, timedelta, timezone
from ..services.public_dynamics import list_public_dynamics, sync_public_dynamics
```

At the start of `build_overview`, after `code` and `name` are defined, call:

```python
public_sync = sync_public_dynamics(asset, force=not use_cache)
```

If sync raises an unexpected internal error, record `errors["public_dynamics"]` and continue with local rows. Do not allow it to suppress snapshot or history retrieval.

Replace only the public-event selection portion with canonical dynamics from the latest 90 days. Serialize each row to the existing event shape plus:

```python
{
    "event_id": row["primary_evidence_id"],
    "evidence_id": row["primary_evidence_id"],
    "dynamic_id": row["id"],
    "source_count": row["source_count"],
    "title": row["canonical_title"],
    "excerpt": row["summary"],
    "published_at": row["published_at"],
    "source_type": row["kind"],
    "source_level": row["primary_source_level"],
    "content_status": row["content_status"],
    "priority": row["importance_score"],
}
```

Keep the existing market-fact event as a fallback only when canonical public dynamics are empty. Include `"public_sync": public_sync` in the overview response.

- [ ] **Step 4: Make manual refresh force public sync**

`refresh_overview` already calls `build_overview(asset, use_cache=False)`. Confirm with a test that this produces `force=True` in `sync_public_dynamics` and does not create a second independent sync call.

- [ ] **Step 5: Accept canonical dynamic context in research and chat**

Change both Pydantic request types:

```python
dynamic_id: Optional[int] = None
```

In each route, when `dynamic_id` is present:

```python
evidence_items = dynamic_evidence(payload.dynamic_id, asset_id=asset["id"])
if not evidence_items:
    raise HTTPException(status_code=404, detail="公开动态不存在或不属于当前标的")
selected_event = evidence_items[0]
```

When it is absent, execute the existing `event_id` lookup unchanged. Pass every linked evidence item to `run_grounded_stream`. The canonical `dynamic_id` exists only in the current research/chat request context and must not be written to the shared `analyses` or `messages` tables. Keep legacy `event_id` behavior unchanged. Analysis and conversation results continue to follow the visitor-AI local/request-scoped privacy boundary.

- [ ] **Step 6: Run compatibility and full tests**

Run:

```bash
.venv/bin/python -m unittest tests/test_public_dynamics_research.py tests/test_zhipu_compat.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit integration**

```bash
git add app/routers/assets.py app/routers/research.py app/routers/chat.py tests/test_public_dynamics_research.py
git commit -m "feat: ground research in aggregated dynamics"
```

---

### Task 8: Preserve the Main View and Add the 24-Hour Sheet Flow

**Files:**
- Create: `frontend/public-dynamics.js`
- Modify: `frontend/importance-detail.js:1-35`
- Modify: `frontend/app.js:1-1238`
- Modify: `frontend/styles.css`
- Create: `tests/frontend_public_dynamics.test.mjs`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Produces: `publicDynamicsSheet`, `publicDynamicDetailSheet`.
- Adds sheet types: `publicDynamics`, `publicDynamicDetail`.
- Uses existing `api`, `openSheet`, `backSheet`, `sheetHeader`, and request-generation helpers.
- Preserves the current main-page conversation markup.

- [ ] **Step 1: Write failing frontend contract tests**

Create `tests/frontend_public_dynamics.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const app = readFileSync(path.join(root, "frontend/app.js"), "utf8");
const details = readFileSync(path.join(root, "frontend/importance-detail.js"), "utf8");
const dynamics = readFileSync(path.join(root, "frontend/public-dynamics.js"), "utf8");
const styles = readFileSync(path.join(root, "frontend/styles.css"), "utf8");

test("public category opens a complete rolling 24 hour feed", () => {
  assert.ok(details.includes("recent_count_24h"));
  assert.ok(app.includes('openSheet("publicDynamics"'));
  assert.ok(app.includes("loadPublicDynamics"));
  assert.ok(dynamics.includes('data-public-kind="all"'));
  assert.ok(dynamics.includes('data-public-kind="official"'));
  assert.ok(dynamics.includes('data-public-kind="media"'));
  assert.ok(dynamics.includes("window_start"));
  assert.ok(dynamics.includes("source_status"));
});

test("dynamic detail keeps sources and active analysis action", () => {
  assert.ok(dynamics.includes("data-public-dynamic-id"));
  assert.ok(dynamics.includes("data-extract-dynamic"));
  assert.ok(dynamics.includes("data-analyze-dynamic"));
  assert.ok(styles.includes(".public-dynamics-list"));
  assert.ok(styles.includes(".public-source-status"));
});
```

- [ ] **Step 2: Run and verify missing-file failure**

Run:

```bash
node --test tests/frontend_public_dynamics.test.mjs
```

Expected: FAIL because `frontend/public-dynamics.js` is missing.

- [ ] **Step 3: Implement focused sheet renderers**

Create `frontend/public-dynamics.js`:

```javascript
const KIND_LABELS = { announcement: "官方", news: "媒体" };

function statusCopy(status) {
  if (status?.last_status === "complete") return "本次采集通道完整";
  if (status?.last_status === "partial") return "部分来源更新失败";
  return "当前展示本地缓存";
}

export function publicDynamicsSheet(data, { sheetHeader, escapeHtml, activeKind = "all" }) {
  const counts = data.counts || { all: 0, official: 0, media: 0 };
  const items = (data.items || []).map((item) => `
    <button class="public-dynamic-item pressable" type="button"
      data-public-dynamic-id="${escapeHtml(item.id)}">
      <span class="public-kind public-kind-${escapeHtml(item.kind)}">${KIND_LABELS[item.kind]}</span>
      <time>${escapeHtml(item.published_at)}</time>
      <strong>${escapeHtml(item.canonical_title)}</strong>
      <span>${escapeHtml(item.summary || "当前仅有标题")}</span>
      <small>${escapeHtml(String(item.source_count || 1))} 个来源 · ${escapeHtml(item.content_status)} · 重要性 ${Math.round(item.importance_score)}</small>
    </button>`).join("");
  return `${sheetHeader("公开动态", "最近 24 小时", true)}
    <div class="sheet-body">
      <div class="public-source-status"><strong>${escapeHtml(statusCopy(data.source_status))}</strong>
        <span>${escapeHtml(data.window_start)}—${escapeHtml(data.window_end)}</span></div>
      <div class="public-dynamics-counts"><span><strong>${counts.all}</strong>全部</span>
        <span><strong>${counts.official}</strong>官方</span><span><strong>${counts.media}</strong>媒体</span></div>
      <div class="public-kind-tabs">
        ${[["all", counts.all], ["official", counts.official], ["media", counts.media]].map(([kind, count]) =>
          `<button type="button" class="${activeKind === kind ? "is-active" : ""}" data-public-kind="${kind}">${kind === "all" ? "全部" : kind === "official" ? "官方" : "媒体"} ${count}</button>`
        ).join("")}
      </div>
      <div class="public-dynamics-list">${items || '<p class="muted">最近 24 小时没有采集到相关动态。</p>'}</div>
      <p class="public-completeness-note">完整表示已配置通道本次成功，并非覆盖互联网全部信息。</p>
    </div>`;
}

export function publicDynamicDetailSheet(data, { sheetHeader, escapeHtml }) {
  const item = data.dynamic;
  const sources = (item.evidence || []).map((source) => `
    <button type="button" class="public-source-row pressable" data-source-id="${escapeHtml(source.evidence_id)}">
      <strong>${escapeHtml(source.raw?.publisher || source.title)}</strong>
      <span>${escapeHtml(source.content_status)} · ${escapeHtml(source.published_at || source.fetched_at)}</span>
    </button>`).join("");
  return `${sheetHeader("动态详情", KIND_LABELS[item.kind], true)}
    <div class="sheet-body"><span class="detail-eyebrow">${escapeHtml(item.category)}</span>
      <h2>${escapeHtml(item.canonical_title)}</h2><p>${escapeHtml(item.summary || "当前仅有标题")}</p>
      <section class="detail-section"><span class="detail-eyebrow">来源与追溯</span>${sources}</section>
      <section class="detail-section"><span class="detail-eyebrow">重要性依据</span>
        <p>分数表示研究注意力，不代表利好或利空。</p></section>
      <div class="button-row">
        ${item.kind === "announcement" && item.content_status !== "full" ? `<button class="secondary-button" type="button" data-extract-dynamic="${item.id}">读取公告正文</button>` : ""}
        <button class="primary-button" type="button" data-analyze-dynamic="${item.id}">基于此动态分析</button>
      </div></div>`;
}
```

- [ ] **Step 4: Add the 24-hour count to the public category card**

In `dailyImportanceSheet`, render public card copy as:

```javascript
const summary = item.category === "public" && item.recent_count_24h != null
  ? `最近 24 小时共 ${item.recent_count_24h} 条 · ${item.summary || "暂无新信息"}`
  : item.summary || "暂无新信息";
```

Use `summary` inside `<small>` and preserve all existing category attributes.

- [ ] **Step 5: Wire sheets without replacing the main conversation**

In `frontend/app.js`:

1. Import `publicDynamicsSheet` and `publicDynamicDetailSheet`.
2. Add `publicDynamicsKind: "all"` to state.
3. Add `publicDynamics` and `publicDynamicDetail` branches to `renderSheet`.
4. Add load functions that capture the current `assetId`, `state.viewGeneration`, and sheet view before awaiting. Discard stale responses using the existing `captureView` and `isCurrentView` helpers.
5. In the importance-category click handler, route `category === "public"` to:

```javascript
openSheet("publicDynamics", importanceCategory, { kind: "all" });
```

Route other categories to the existing `importanceCategory` sheet unchanged.
6. Handle `data-public-kind` by updating `state.sheetView.kind` and refetching `/assets/${assetId}/public-dynamics?hours=24&kind=${kind}`.
7. Handle `data-public-dynamic-id` by opening `publicDynamicDetail` and loading `/public-dynamics/{id}`.
8. Handle `data-extract-dynamic` with POST `/public-dynamics/{id}/extract`, then reload the detail.
9. Handle `data-analyze-dynamic` by selecting the matching dynamic, closing the sheet, and calling `runAnalysis` with both its primary `event_id` and `dynamic_id`.
10. Update `runAnalysis` and `runChat` payloads to include `dynamic_id` when the selected overview event has one.

Do not change `renderDynamicMessage`, `renderConversation`, the composer, the tour, or the current request-generation safeguards except for adding the optional dynamic ID.

- [ ] **Step 6: Add styles in the existing design language**

Append focused selectors to `frontend/styles.css` using existing variables:

```css
.public-source-status { padding: 13px 14px; border-radius: 13px; background: var(--green-wash); }
.public-source-status strong, .public-source-status span { display: block; }
.public-source-status span { margin-top: 4px; color: var(--muted); font-size: 11px; }
.public-dynamics-counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }
.public-dynamics-counts span { padding: 11px; border-radius: 12px; background: var(--canvas); color: var(--muted); font-size: 11px; }
.public-dynamics-counts strong { display: block; color: var(--ink); font-size: 20px; }
.public-kind-tabs { display: flex; gap: 4px; padding: 4px; border-radius: 12px; background: var(--canvas); }
.public-kind-tabs button { flex: 1; border: 0; border-radius: 9px; padding: 8px; background: transparent; color: var(--muted); }
.public-kind-tabs button.is-active { background: white; color: var(--ink); box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.public-dynamic-item { display: grid; grid-template-columns: auto 1fr; gap: 7px 10px; width: 100%; padding: 15px 0; border: 0; border-bottom: 1px solid var(--line); background: transparent; text-align: left; }
.public-dynamic-item time { justify-self: end; color: var(--muted); font-size: 11px; }
.public-dynamic-item strong, .public-dynamic-item > span:not(.public-kind), .public-dynamic-item small { grid-column: 1 / -1; }
.public-dynamic-item > span:not(.public-kind) { color: var(--ink-soft); font-size: 13px; line-height: 1.55; }
.public-dynamic-item small, .public-completeness-note { color: var(--muted); font-size: 11px; }
.public-kind { width: fit-content; padding: 4px 7px; border-radius: 999px; color: var(--blue); background: var(--blue-wash); font-size: 10px; font-weight: 650; }
.public-kind-news { color: #7641a4; background: #f4edfb; }
.public-source-row { display: block; width: 100%; padding: 11px 0; border: 0; border-bottom: 1px solid var(--line); background: transparent; text-align: left; }
.public-source-row strong, .public-source-row span { display: block; }
.public-source-row span { margin-top: 4px; color: var(--muted); font-size: 11px; }
```

- [ ] **Step 7: Run frontend and backend regression tests**

Run:

```bash
node --test tests/frontend_public_dynamics.test.mjs tests/frontend_prototype.test.mjs
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 8: Commit the confirmed interaction flow**

```bash
git add frontend/public-dynamics.js frontend/importance-detail.js frontend/styles.css tests/frontend_public_dynamics.test.mjs tests/frontend_prototype.test.mjs
git add -p frontend/app.js
git diff --cached -- frontend/app.js
git commit -m "feat: add complete 24 hour dynamics drilldown"
```

Expected cached `frontend/app.js` diff: public-dynamics routing and optional `dynamic_id` changes only; the pre-existing view-capture and abort-guard changes must not be claimed by this commit unless they have already been committed separately.

---

### Task 9: Live Source Smoke Test, Documentation, and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if document limits become configurable during implementation; otherwise leave it unchanged.
- Verify: all files from Tasks 1-8.

**Interfaces:**
- No new runtime interface.
- Produces operator documentation and fresh verification evidence.

- [ ] **Step 1: Add source and completeness documentation**

Add a “公开动态增强” section to `README.md` containing exactly these operational facts:

```markdown
## 公开动态增强

- 官方主源为巨潮资讯，东方财富公告作为备用索引，媒体层使用东方财富个股新闻并保留原始媒体名称。
- 新标的首次回溯最近 90 天；以后按来源最后成功时间增量获取，并保留 24 小时重叠窗口。
- 启动或切换标的时，只有最近完整更新超过 24 小时才自动刷新；失败后的自动重试冷却为 30 分钟。手动刷新不受该窗口限制。
- 时间线中的“公开动态”展示滚动最近 24 小时内全部已采集相关动态，重要性只用于突出重点，不过滤低分内容。
- “完整更新”表示已配置的官方和媒体通道满足成功条件，不表示覆盖互联网全部信息。
- 公告 PDF 仅在查看正文或主动分析时下载并提取；扫描件不执行 OCR。同步阶段不会调用模型。
```

- [ ] **Step 2: Run the deterministic full suite**

Run:

```bash
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.mjs
git diff --check
```

Expected: compile exits 0; all Python tests PASS; all Node tests PASS; `git diff --check` emits no errors.

- [ ] **Step 3: Run one bounded live-source smoke test**

Use an isolated temporary database and one known A-share code so user data is untouched:

```bash
DATABASE_PATH=/tmp/tradingbuddy-public-dynamics-smoke.db .venv/bin/python -c "from app import database as db; from app.services.public_dynamics import sync_public_dynamics, list_public_dynamics; from datetime import datetime, timedelta, timezone; db.init_db(); now=db.utcnow(); asset_id=db.execute(\"INSERT INTO assets (stock_code, stock_name, asset_type, notifications_enabled, created_at, updated_at) VALUES ('600519','贵州茅台','watchlist',0,?,?)\", (now,now)); asset=db.query_one('SELECT * FROM assets WHERE id=?',(asset_id,)); result=sync_public_dynamics(asset, force=True); end=datetime.now(timezone.utc); rows=list_public_dynamics(asset_id,end-timedelta(hours=24),end,'all'); print({'status':result['status'],'providers':[(p['provider'],p['status']) for p in result['providers']],'count_24h':len(rows)})"
```

Expected: command exits 0 and prints provider statuses plus a non-negative count. If an external source is unavailable, the result may be `partial` or `failed`; that is acceptable only when the output identifies the failing provider and deterministic adapter tests still pass.

- [ ] **Step 4: Start the application against an isolated smoke database**

Run:

```bash
DATABASE_PATH=/tmp/tradingbuddy-public-dynamics-ui.db APP_PORT=8012 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8012
```

In a second terminal, verify:

```bash
curl -fsS http://127.0.0.1:8012/api/health
```

Expected: JSON with `"status":"ok"`.

Manually verify:

1. Add `600519` if the isolated database is empty.
2. Open the latest blue importance node.
3. Open the public category.
4. Confirm the rolling start and end timestamps are visible.
5. Confirm every returned item remains visible in “全部”, including low-importance items.
6. Compare “全部” count with official plus media counts.
7. Open an announcement, inspect all sources, and request text extraction.
8. Trigger analysis and confirm cited evidence comes from the canonical dynamic.
9. Switch away and back within 24 hours; confirm no new source request occurs.
10. Use manual refresh; confirm a new attempt occurs.

- [ ] **Step 5: Inspect the exact feature diff and protected concurrent work**

Run:

```bash
git status --short
git diff --stat 9434513..HEAD
git diff -- app/services/thesis_draft.py frontend/app.js requirements.txt
git log --oneline 9434513..HEAD
```

Expected: public-dynamics feature commits are present; the working-tree diff still contains any visitor-AI changes that were uncommitted at execution start; no public-dynamics commit contains `app/services/thesis_draft.py`; unrelated `.superpowers/` and `deploy/` content is unstaged.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs: document public dynamics sources and freshness"
```

- [ ] **Step 7: Run final verification after the last commit**

Run:

```bash
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.mjs
git status --short
```

Expected: compile exits 0; all tests PASS; status contains only the pre-existing unrelated or concurrent user changes, if any.

---

## Plan Self-Review Mapping

- Spec sections 5 and 8, architecture and storage: Tasks 1-4.
- Spec section 4, source selection and license-safe adaptation: Task 2.
- Spec sections 6 and 7, 90-day backfill, 24-hour overlap, freshness, classification, aggregation, and scoring: Tasks 3-4.
- Spec section 9, on-demand document extraction and safety: Task 6.
- Spec section 10, API and AI compatibility: Tasks 5 and 7.
- Spec section 11, preserved main view and complete 24-hour drilldown: Task 8.
- Spec section 12, source and PDF degradation: Tasks 4-7.
- Spec sections 13 and 14, deterministic tests and acceptance checks: Tasks 1-9.
- Spec section 15, implementation order: the task order matches the approved dependency order.
- No task implements background scheduling, multi-user support, OCR, paid providers, semantic search, or the other three importance categories.
