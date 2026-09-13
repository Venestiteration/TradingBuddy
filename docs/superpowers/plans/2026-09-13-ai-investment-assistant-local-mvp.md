# AI 投研助手本地 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有桌面端原型和 FastAPI/SQLite 骨架收敛为一个可在本机运行的真实数据、证据可核验、支持 AI 分析和判断持久化的 MVP。

**Architecture:** 保留 FastAPI 单进程架构，由 API 路由调用 SQLite、真实行情/资讯适配器和 OpenAI Responses API；静态前端拆到 `frontend/`，通过 JSON 和 SSE 调用后端。外部数据和模型调用均经过超时、三次以内重试、缓存和明确的 stale/error 状态，AI 输出必须经过 Schema 与证据编号校验。

**Tech Stack:** Python 3.10+、FastAPI、Pydantic v2、SQLite、AkShare、requests、pandas/numpy、OpenAI Python SDK、原生 HTML/CSS/JavaScript、Node `node:test`。

## Global Constraints

- 本机服务地址默认为 `http://127.0.0.1:8000`，由 `start.sh` 启动。
- `asset_type` 仅允许 `watchlist` 或 `holding`；数量和成本不用于交易建议。
- 外部请求必须设置连接/读取超时，并且最多三次有限重试；失败时展示缓存或明确错误，不生成伪造数据。
- AI 只在生成分析、快捷问题或自由追问时调用；切换标的、刷新页面、打开研究档案不自动调用模型。
- AI 结构化结果中的每个“已知事实”至少引用一个本次输入中的有效 `evidence_id`；无有效引用的事实必须被删除或降级。
- 任何买卖、仓位、目标价格或交易时点表达必须改写为条件化分析，产品不输出交易指令。
- `data/assistant.db`、`.env`、`.venv` 和真实用户数据不得提交。
- 前端不得继续把模拟行情、模拟事件、模拟来源或假流式文本当成真实内容展示。

---

## Task 1: Test Harness, Shared Schemas, and Startup Contract

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_api_smoke.py`
- Create: `app/schemas.py`
- Modify: `app/config.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`

**Interfaces:**
- `app.schemas`: define `AssetCreate`, `AssetUpdate`, `ThesisCreate`, `ResearchRequest`, `ChatRequest`, and response-facing typed models used by routers.
- `app.main.create_app()`: returns a FastAPI app with database initialization, all `/api` routers, and `frontend/` mounted at `/`.
- Test fixtures set `DATABASE_PATH` to a temporary SQLite file and restore process state after each test; tests never touch `data/assistant.db`.

- [ ] **Step 1: Write the failing startup tests**

Add tests that import `create_app`, request `/api/health` and `/`, and assert the health response contains `status == "ok"`, `database`, `openai_configured`, and `fetched_at`-compatible time data. Assert the root response is the new frontend entry point, not the old root prototype file.

```python
def test_health_and_frontend_are_served(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "AI 投研助手" in page.text
    assert "data-api-root" in page.text
```

- [ ] **Step 2: Run the smoke test and confirm the expected failure**

Run `python -m pytest tests/test_api_smoke.py -q`. It must fail because the test client fixture, shared request schemas, or `frontend/index.html` does not yet exist; fix only test setup errors before implementing the feature.

- [ ] **Step 3: Add the shared request/response models and isolated fixtures**

Use Pydantic v2 models with the same constraints as the API contract. The fixture must set `DATABASE_PATH` before importing the application, reload `app.config`, `app.database`, and `app.main`, then yield `TestClient(create_app())`. Add `httpx>=0.27` to `requirements.txt` for FastAPI's test client.

- [ ] **Step 4: Implement the startup contract**

Make `create_app()` mount `frontend/` when it exists and return a JSON 404 for missing API routes. Extend `/api/health` with `status`, `app`, `openai_configured`, `openai_model`, `database`, and `time`; keep secrets out of the response. Create a minimal `frontend/index.html` only as a test fixture if Task 6 has not yet supplied the full page.

- [ ] **Step 5: Run the focused test and the existing prototype test**

Run `python -m pytest tests/test_api_smoke.py -q` and `node --test tests/prototype.test.mjs`. The new test must pass. Record the existing prototype failure as a separate frontend migration issue until Task 5 fixes it.

## Task 2: Database Isolation, Asset Lifecycle, and Thesis Versioning

**Files:**
- Create: `tests/test_assets_api.py`
- Modify: `app/database.py`
- Modify: `app/routers/assets.py`
- Modify: `app/schemas.py`

**Interfaces:**
- `POST /api/assets` accepts a six-digit code and returns the persisted asset.
- `PATCH /api/assets/{id}` changes only supplied fields.
- `DELETE /api/assets/{id}` removes dependent theses, analyses, messages, and the asset through SQLite foreign keys.
- `GET/POST /api/assets/{id}/theses` returns current version and complete history; creating a thesis increments the version without overwriting previous rows.

- [ ] **Step 1: Write failing lifecycle tests**

Cover creating a watchlist asset, duplicate rejection, updating only `asset_type`, deleting an asset, and thesis version history.

```python
def test_thesis_versions_are_append_only(client, monkeypatch):
    monkeypatch.setattr(market_service, "stock_name", lambda code: "贵州茅台")
    asset = client.post("/api/assets", json={"stock_code": "600519"}).json()
    first = client.post(f"/api/assets/{asset['id']}/theses", json={"core_thesis": "关注现金流"})
    second = client.post(f"/api/assets/{asset['id']}/theses", json={"core_thesis": "关注提价与需求"})
    assert first.status_code == 201 and second.status_code == 201
    history = client.get(f"/api/assets/{asset['id']}/theses").json()["theses"]
    assert [row["version"] for row in history] == [1, 2]
    assert history[0]["core_thesis"] == "关注现金流"
```

- [ ] **Step 2: Run the focused tests and verify they fail for missing behavior**

Run `python -m pytest tests/test_assets_api.py -q`. The duplicate, partial-update, or append-only assertions must fail before changing production code.

- [ ] **Step 3: Harden database initialization and asset mutations**

Keep foreign keys enabled on every connection, preserve the current schema, and make test configuration independent from the module-level default database. Normalize codes before lookup, reject invalid lengths/characters with HTTP 400, return HTTP 409 for duplicates, and use parameterized SQL for every value.

- [ ] **Step 4: Implement and verify thesis history behavior**

Calculate the next version with `MAX(version) + 1` within the same transaction, write `created_at`, return the inserted row, and expose newest-first current data plus oldest-to-newest history. Run `python -m pytest tests/test_assets_api.py -q` until green.

## Task 3: Real Market Data, Cache, Indicators, and Search

**Files:**
- Create: `tests/test_market_service.py`
- Modify: `app/services/market.py`
- Modify: `app/routers/assets.py`
- Modify: `requirements.txt`

**Interfaces:**
- `normalize_code(raw) -> str` accepts a six-digit A-share code and rejects other input.
- `MarketService.search(query, limit) -> list[dict]` returns `stock_code`, `stock_name`, and source/cache metadata.
- `MarketService.snapshot(code, use_cache=True) -> dict` returns normalized price fields plus `data_time`, `fetched_at`, and `stale`.
- `MarketService.history(code, use_cache=True) -> dict` returns normalized OHLCV rows and all requested indicators.
- A failed live request first returns a fresh cache, then an expired cache marked `stale`, and only then raises `MarketDataError`.

- [ ] **Step 1: Write failing pure-function tests**

Test code normalization, number conversion, date ordering, invalid row removal, and indicator keys using a three-row fixture plus a twenty-five-row fixture for rolling values.

```python
def test_history_normalization_drops_invalid_rows_and_keeps_indicator_keys():
    rows = normalize_history(raw_fixture_frame())
    assert [row["date"] for row in rows] == sorted(row["date"] for row in rows)
    assert all(row["close"] is not None for row in rows)
    assert {"MA5", "MA10", "MA20", "MA60", "MACD_DIF", "RSI", "KDJ_K", "BOLL_UPPER"} <= rows[-1].keys()
```

- [ ] **Step 2: Run the market tests and confirm the intended red state**

Run `python -m pytest tests/test_market_service.py -q`; the tests must fail because the public normalization function and deterministic indicator fixture are not yet complete.

- [ ] **Step 3: Implement deterministic normalization and indicator calculation**

Keep upstream-specific parsing inside private adapter functions. Convert dates to ISO strings, sort ascending, drop rows with no valid close, and calculate MA5/10/20/60, MACD DIF/DEA/histogram, RSI, KDJ K/D/J, and Bollinger upper/mid/lower with `None` until enough observations exist. Ensure JSON serialization converts numpy scalars to Python numbers.

- [ ] **Step 4: Implement bounded network access and cache fallback**

Use a `requests.Session` or AkShare call wrapper with `REQUEST_TIMEOUT_SECONDS`, at most three attempts, and exponential delays capped below the page timeout. Store normalized values in SQLite `kv` keys `market:snapshot:{code}`, `market:history:{code}`, and `stocks:list`; expose `fetched_at`, `data_time`, and `stale`. Keep a memory cache only as an optimization, never as the sole persistence layer.

- [ ] **Step 5: Add adapter-level tests without network access**

Monkeypatch the upstream call functions to return deterministic frames and then to raise exceptions. Assert successful responses, fresh-cache responses, stale-cache responses, and final `MarketDataError`. Run `python -m pytest tests/test_market_service.py -q` and `python -m pytest tests/test_assets_api.py -q`.

## Task 4: Evidence, News/Announcements, Event Ranking, and Overview Degradation

**Files:**
- Create: `tests/test_events_and_evidence.py`
- Modify: `app/services/evidence.py`
- Modify: `app/services/events.py`
- Modify: `app/routers/assets.py`

**Interfaces:**
- `make_evidence(...) -> dict` always returns the standard evidence object with `content_status` set to `full`, `excerpt`, or `title_only`.
- `collect_events(code, name, snapshot, history, use_cache=True) -> dict` returns `events`, `errors`, `fetched_at`, and `stale`.
- Events are deduplicated by normalized title plus URL, rank announcements above news, then relevance and recency, and add a market-only fact event only when no high-quality event exists.
- `GET /api/evidence/{id}` returns the public evidence object and 404s for unknown IDs.

- [ ] **Step 1: Write failing event and evidence tests**

Test title normalization/deduplication, primary-source ranking, title-only status, invalid URL cleanup, market-only fallback, and “news failure does not erase announcements.”

```python
def test_title_only_evidence_cannot_claim_body_content():
    item = make_evidence("600519", "announcement", "primary", "年度报告摘要", excerpt="", content_status="title_only")
    assert item["content_status"] == "title_only"
    assert item["excerpt"] == ""
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run `python -m pytest tests/test_events_and_evidence.py -q`; verify the failure is in the expected ranking/degradation behavior, not import setup.

- [ ] **Step 3: Complete standard evidence persistence and public projection**

Preserve stable SHA-1 evidence IDs, upsert only refreshed fields, decode `raw` safely, and never expose raw provider payloads through the public endpoint. Keep `source_level` and `content_status` in every event returned to the browser.

- [ ] **Step 4: Complete event adapters and deterministic ranking**

Keep AkShare imports lazy, map Chinese provider columns through candidate-name lookup, trim excerpts to bounded size, and catch each source independently. Apply the specification's announcement/news/market ranking and per-source quota. Save every selected evidence item before returning the public event list.

- [ ] **Step 5: Verify overview failure behavior**

Make overview return available snapshot/history/events even when another source fails, include a human-readable `errors` object, `data_time`, `fetched_at`, and `stale`, and run the focused tests plus the asset API tests.

## Task 5: Grounded AI Analysis, Validation, Cache, and SSE

**Files:**
- Create: `tests/test_ai_service.py`
- Create: `tests/test_research_api.py`
- Modify: `app/services/ai.py`
- Modify: `app/routers/research.py`
- Modify: `app/routers/chat.py`
- Modify: `app/schemas.py`

**Interfaces:**
- `validate_result(result, evidence_lookup) -> (clean_result, notes)` enforces the structured output and evidence rules.
- `run_grounded_stream(...) -> Generator[str, None, None]` emits exactly `context_ready`, `model_running`, `validating`, and terminal `completed` or `failed` SSE events.
- `POST /api/research/stream` accepts `asset_id`, `event_id`, and optional `question`.
- `POST /api/chat/stream` accepts `asset_id`, `question`, and optional `event_id`; it uses only the selected asset's evidence, thesis, and recent messages.

- [ ] **Step 1: Write failing validator tests**

Cover invalid impact states, missing required fields, invalid evidence IDs, uncited facts, title-only evidence, trading language, and insufficient-state downgrade.

```python
def test_validator_removes_uncited_facts_and_downgrades_impact():
    result = valid_result(facts=[{"claim": "unsupported", "evidence_ids": ["missing"]}])
    cleaned, notes = validate_result(result, {"e1": excerpt_evidence()})
    assert cleaned["facts"] == []
    assert cleaned["impact_state"] == "insufficient"
    assert notes
```

- [ ] **Step 2: Run validator tests and verify red**

Run `python -m pytest tests/test_ai_service.py -q`; correct only fixture errors, then keep the behavior assertion failing until the implementation is updated.

- [ ] **Step 3: Implement strict model context and one retry**

Build context from the selected asset, snapshot, event, evidence IDs/content status, current thesis version, and recent messages. Use the existing JSON Schema with the configured OpenAI model. Classify timeout, quota, API key, network, and schema errors; retry only schema failures once and never synthesize a result when the model is unavailable.

- [ ] **Step 4: Implement persistence and cache keying**

Persist `analyses` with event ID, sorted evidence fingerprint, thesis version, model, validation notes, result JSON, and creation time. Reuse a matching completed analysis for the same asset/event/evidence/thesis tuple; do not reuse a failed result. Persist user and assistant messages for chat.

- [ ] **Step 5: Implement and test SSE routers**

Return `text/event-stream` with JSON payloads and terminal events. Validate asset/event ownership before calling the model. Tests monkeypatch the model call to return a deterministic structured object and assert event order, saved analysis, evidence IDs, and a failed terminal event when no API key is configured.

- [ ] **Step 6: Run all backend tests**

Run `python -m pytest tests/test_api_smoke.py tests/test_assets_api.py tests/test_market_service.py tests/test_events_and_evidence.py tests/test_ai_service.py tests/test_research_api.py -q`.

## Task 6: Split the Prototype Frontend and Connect the Main Flow

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/styles.css`
- Create: `frontend/app.js`
- Modify: `tests/prototype.test.mjs`
- Modify: `README.md`

**Interfaces:**
- `frontend/app.js` owns API calls, selected asset state, loading/error/stale state, SSE consumption, and rendering; it must not contain hard-coded simulated stock data.
- The page exposes `data-api-root="/api"`, elements for asset switcher, dynamic feed, composer, detail sheet, thesis, and tour layer.
- `window.__mvpTestHooks` exposes only deterministic render helpers needed by the Node smoke test; production behavior remains event-driven.

- [ ] **Step 1: Extend the failing prototype test for the MVP contract**

Assert the new files exist, `frontend/index.html` references `styles.css` and `app.js`, the root page contains `data-tour="thesis"`, and the frontend has no `模拟新动态`, `buildMarketSeries`, `resolveAnswer`, or fake stream phrases. Keep the existing accessibility and reduced-motion assertions.

- [ ] **Step 2: Run the test and confirm red**

Run `node --test tests/prototype.test.mjs`; it must fail because the frontend directory and API-backed data flow do not yet exist.

- [ ] **Step 3: Split stable visual structure from the old prototype**

Move reusable CSS into `frontend/styles.css` and semantic markup into `frontend/index.html`. Preserve focus-visible, reduced motion/transparency, high contrast, keyboard tour navigation, drawer focus restoration, and the four-layer answer structure. Add the missing thesis tour target to the actual thesis panel rather than weakening the assertion.

- [ ] **Step 4: Replace simulated state with API state**

Implement `fetchHealth`, `searchStocks`, `loadAssets`, `createAsset`, `updateAsset`, `deleteAsset`, `loadOverview`, `refreshOverview`, `saveThesis`, `openEvidence`, `startResearch`, and `startChat`. Render source type, source level, publication time, fetched time, stale status, and explicit errors. Do not auto-call research on asset switch or page refresh.

- [ ] **Step 5: Implement finite SSE state handling**

Use `EventSource` only for server endpoints that support GET or use `fetch` with a reader for POST SSE. Map `context_ready → model_running → validating → completed/failed` to visible status text; render the completed JSON only after parsing the terminal payload. On failure preserve overview data and show retry.

- [ ] **Step 6: Run frontend and backend tests**

Run `node --test tests/prototype.test.mjs` and the full Python test command from Task 5. Fix integration mismatches in the API or DOM; do not add simulated fixtures to make tests pass.

## Task 7: Local Runtime, Documentation, and End-to-End Smoke Check

**Files:**
- Create: `tests/smoke_test.py`
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `start.sh`
- Modify: `.env.example`

**Interfaces:**
- `start.sh` creates/uses Python 3.10+ virtualenv, installs dependencies, creates `.env` from `.env.example` when absent, and starts only the local FastAPI server.
- `tests/smoke_test.py` uses an isolated temporary database and monkeypatched provider/model adapters; it proves the primary flow without requiring network access or an API key.

- [ ] **Step 1: Write the failing end-to-end smoke test**

The test must start with an empty database, patch stock search/market/events/model providers, add `600519`, fetch overview, stream a completed analysis, save a thesis, create a fresh app instance against the same database, and assert the asset and thesis remain.

```python
def test_primary_flow_survives_app_restart(client_factory, monkeypatch):
    patch_deterministic_providers(monkeypatch)
    client = client_factory()
    asset = client.post("/api/assets", json={"stock_code": "600519"}).json()
    assert client.get(f"/api/assets/{asset['id']}/overview").json()["events"]
    assert terminal_event(client.post("/api/research/stream", json={"asset_id": asset["id"], "event_id": "e1"})) == "completed"
    client.post(f"/api/assets/{asset['id']}/theses", json={"core_thesis": "关注需求变化"})
    restarted = client_factory()
    assert restarted.get("/api/assets").json()["assets"][0]["stock_code"] == "600519"
```

- [ ] **Step 2: Run the smoke test and verify the expected red state**

Run `python -m pytest tests/smoke_test.py -q`; the test should fail until all route and persistence boundaries are connected.

- [ ] **Step 3: Make runtime configuration explicit**

Ensure `.env.example` contains `OPENAI_API_KEY`, `OPENAI_MODEL`, optional `OPENAI_BASE_URL`, `APP_HOST`, `APP_PORT`, `DATABASE_PATH`, `REQUEST_TIMEOUT_SECONDS`, and `AI_TIMEOUT_SECONDS`. Add `data/*`, `.env`, `.venv/`, `__pycache__/`, and test caches to `.gitignore`. Make `start.sh` print the actual configured bind address and never launch background fetches.

- [ ] **Step 4: Rewrite README for a second user**

Document prerequisites, virtualenv setup, dependency installation, `.env` configuration, startup URL, API health check, the exact primary demo flow, data/source limitations, API key behavior, and the fact that the product does not provide investment advice. State that public data availability and commercial display rights are not guaranteed.

- [ ] **Step 5: Run the complete verification set**

Run:

```bash
python -m pytest -q
node --test tests/prototype.test.mjs
python -m compileall app
git diff --check
```

Expected result: all automated tests pass, Python compilation succeeds, and `git diff --check` prints no whitespace errors. If live credentials are available, manually run `./start.sh`, open `http://127.0.0.1:8000`, add `600519`, inspect the fetched timestamp and source list, generate an analysis, ask a follow-up question, save a thesis, restart, and verify persistence. Without credentials, report the manual live-call limitation explicitly rather than replacing it with fake data.

---

## Plan Self-Review

- Spec coverage: startup and health are covered by Task 1; assets/theses/database by Task 2; search/snapshot/history/indicators/cache by Task 3; news/announcements/evidence/ranking by Task 4; structured AI/SSE/validation by Task 5; frontend migration and removal of simulated behavior by Task 6; persistence restart, README, and runtime delivery by Task 7.
- Placeholder scan: no step depends on a future unnamed function or an unspecified provider; provider failures are tested through deterministic monkeypatches.
- Type consistency: all routers consume the shared Pydantic request models; `evidence_id` is the stable key across events, AI context, analyses, and frontend links; `asset_id` is the SQLite integer key throughout.
- Scope: no login, broker integration, automatic push, portfolio optimization, backtesting, target-price valuation, vector database, or production deployment is included.
