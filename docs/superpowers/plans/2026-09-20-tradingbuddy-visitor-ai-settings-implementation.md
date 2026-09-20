# TradingBuddy Visitor-Owned AI Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, visitor-owned AI configuration while keeping source collection usable without AI and preserving the current TradingBuddy visual language.

**Architecture:** Store each visitor's AI configuration and AI workspace in versioned browser `localStorage`; send the configuration only on AI requests; build a request-scoped OpenAI-compatible client on the server; never persist new AI analyses or messages in SQLite. Keep all non-AI market, event, importance, and evidence flows unchanged.

**Tech Stack:** FastAPI, Pydantic, OpenAI Python SDK, SQLite, native ES modules, browser `localStorage`, Node test runner, Python `unittest`, Nginx/systemd deployment.

## Global Constraints

- The AI switch defaults to off.
- Enabling AI requires a non-empty API Key and model name; a blank API URL maps to `https://api.openai.com/v1`.
- API Key, AI messages, and analyses are stored only in the current browser and are never logged or persisted by the server.
- Custom API URLs must be HTTPS public addresses; localhost, private, link-local, multicast, reserved, unspecified, credential-bearing, and redirecting destinations are rejected.
- AI-off mode shows asset management, market data, importance timeline, public events, refresh, and evidence sources only.
- AI-off mode hides analysis, quick prompts, composer, inference views, server AI history, and AI thesis draft entry points.
- Existing AI thesis draft code and historical database rows remain intact, but generation is unavailable in visitor-local mode.
- Each asset retains at most 50 local AI messages and 20 local analyses.
- Reuse the current top bar, sheet, card, form, button, Toast, tour, color, spacing, radius, shadow, typography, motion, focus, mobile breakpoint, and reduced-motion rules.
- Desktop and mobile both display the full `TradingBuddy` brand name.

---

## File Structure

- Create `app/services/visitor_ai.py`: parse request headers, validate API configuration, resolve and pin public hosts, and expose `VisitorAIConfig`.
- Modify `app/services/ai.py`: consume `VisitorAIConfig` explicitly and remove global/server-key fallback.
- Modify `app/services/thesis_draft.py`: make future model generation require explicit visitor configuration.
- Modify `app/routers/research.py`: require visitor configuration and stream results without persistence.
- Modify `app/routers/chat.py`: accept bounded browser context and stream results without persistence.
- Modify `app/routers/assets.py`: stop exposing public AI history and report visitor-AI capability in health output.
- Modify `app/routers/theses.py`: return an explicit unavailable response from AI draft generation.
- Modify `app/main.py`: add security response headers.
- Create `frontend/ai-local.js`: own versioned local configuration/workspace parsing, validation, capping, and AI headers.
- Modify `frontend/api.js`: allow request-specific headers in streaming calls and preserve structured error metadata.
- Modify `frontend/app.js`: render AI-off/on modes, settings interactions, local AI history, and conditional tours.
- Modify `frontend/index.html`: update branding, add stable tour targets, identify the composer dock, and bump static versions.
- Modify `frontend/styles.css`: style settings controls using existing tokens and preserve full branding on narrow screens.
- Create `tests/test_visitor_ai_config.py`: backend URL/header validation.
- Create `tests/test_visitor_ai_routes.py`: stateless AI routes, bounded context, health output, and disabled draft generation.
- Create `tests/test_security_headers.py`: browser security headers.
- Create `tests/ai_local.test.mjs`: browser-local configuration/workspace behavior.
- Modify `tests/test_zhipu_compat.py`: request-scoped provider compatibility.
- Modify `tests/frontend_prototype.test.mjs`: brand, source-only mode, settings, and tour markers.
- Modify `README.md`: visitor-owned AI setup and privacy behavior.

---

### Task 1: Request-Scoped Visitor AI Configuration

**Files:**
- Create: `app/services/visitor_ai.py`
- Create: `tests/test_visitor_ai_config.py`

**Interfaces:**
- Produces: `VisitorAIConfig(api_key: str, model: str, base_url: str, resolved_ips: tuple[str, ...])`.
- Produces: `build_visitor_ai_config(api_key, model, base_url, resolver=socket.getaddrinfo) -> VisitorAIConfig`.
- Produces: FastAPI dependency `visitor_ai_config(...) -> VisitorAIConfig`.
- Consumed by: Tasks 2 and 3.

- [ ] **Step 1: Write failing configuration tests**

```python
# tests/test_visitor_ai_config.py
import socket
import unittest

from fastapi import HTTPException

from app.services.visitor_ai import build_visitor_ai_config


def public_resolver(host, port, type=socket.SOCK_STREAM):
    return [(socket.AF_INET, type, 6, "", ("8.8.8.8", port))]


def private_resolver(host, port, type=socket.SOCK_STREAM):
    return [(socket.AF_INET, type, 6, "", ("10.0.0.8", port))]


class VisitorAIConfigTest(unittest.TestCase):
    def test_blank_url_uses_openai_default(self):
        config = build_visitor_ai_config("sk-user", "gpt-4.1-mini", "", resolver=public_resolver)
        self.assertEqual(config.base_url, "https://api.openai.com/v1")

    def test_public_compatible_url_is_accepted(self):
        config = build_visitor_ai_config(
            "visitor-key", "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4/",
            resolver=public_resolver,
        )
        self.assertEqual(config.model, "glm-4-flash")

    def test_missing_key_or_model_is_rejected(self):
        for key, model in (("", "gpt-4.1-mini"), ("sk-user", "")):
            with self.subTest(key=key, model=model), self.assertRaises(HTTPException) as caught:
                build_visitor_ai_config(key, model, "", resolver=public_resolver)
            self.assertEqual(caught.exception.status_code, 400)

    def test_non_https_and_private_destinations_are_rejected(self):
        cases = [
            ("http://api.example.com/v1", public_resolver),
            ("https://localhost/v1", public_resolver),
            ("https://service.local/v1", public_resolver),
            ("https://user:pass@api.example.com/v1", public_resolver),
            ("https://api.example.com/v1", private_resolver),
        ]
        for url, resolver in cases:
            with self.subTest(url=url), self.assertRaises(HTTPException):
                build_visitor_ai_config("sk-user", "model", url, resolver=resolver)

    def test_length_limits_are_enforced(self):
        with self.assertRaises(HTTPException):
            build_visitor_ai_config("k" * 513, "model", "", resolver=public_resolver)
        with self.assertRaises(HTTPException):
            build_visitor_ai_config("key", "m" * 129, "", resolver=public_resolver)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `python3 -m unittest tests/test_visitor_ai_config.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.visitor_ai'`.

- [ ] **Step 3: Implement immutable configuration and URL validation**

```python
# app/services/visitor_ai.py
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Annotated, Callable
from urllib.parse import urlparse

from fastapi import Header, HTTPException

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class VisitorAIConfig:
    api_key: str
    model: str
    base_url: str
    resolved_ips: tuple[str, ...]


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return not any((
        address.is_private,
        address.is_loopback,
        address.is_link_local,
        address.is_multicast,
        address.is_reserved,
        address.is_unspecified,
    ))


def build_visitor_ai_config(
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    resolver: Callable = socket.getaddrinfo,
) -> VisitorAIConfig:
    key = (api_key or "").strip()
    model_name = (model or "").strip()
    url = (base_url or "").strip() or DEFAULT_OPENAI_BASE_URL
    if not key or len(key) > 512:
        raise HTTPException(status_code=400, detail="请填写有效的 API Key")
    if not model_name or len(model_name) > 128:
        raise HTTPException(status_code=400, detail="请填写有效的模型名称")
    if len(url) > 512:
        raise HTTPException(status_code=400, detail="API 地址过长")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="API 地址必须是不含凭据的 HTTPS 公网地址")
    if parsed.query or parsed.fragment or host == "localhost" or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="API 地址不是允许的公网地址")
    try:
        addresses = [item[4][0] for item in resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)]
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="无法解析 API 地址") from exc
    if not addresses or any(not _public_ip(value) for value in addresses):
        raise HTTPException(status_code=400, detail="API 地址不能指向本机或内网")
    return VisitorAIConfig(
        api_key=key,
        model=model_name,
        base_url=url.rstrip("/"),
        resolved_ips=tuple(dict.fromkeys(addresses)),
    )


def visitor_ai_config(
    api_key: Annotated[str | None, Header(alias="X-TB-API-Key")] = None,
    model: Annotated[str | None, Header(alias="X-TB-Model")] = None,
    base_url: Annotated[str | None, Header(alias="X-TB-Base-URL")] = None,
) -> VisitorAIConfig:
    return build_visitor_ai_config(api_key, model, base_url)
```

- [ ] **Step 4: Run configuration tests**

Run: `python3 -m unittest tests/test_visitor_ai_config.py -v`

Expected: 5 tests PASS.

- [ ] **Step 5: Commit the request boundary**

```bash
git add app/services/visitor_ai.py tests/test_visitor_ai_config.py
git commit -m "feat: validate visitor-owned AI configuration"
```

---

### Task 2: Refactor the AI Service to Require Visitor Configuration

**Files:**
- Modify: `app/services/ai.py:7-119,156-236,368-445`
- Modify: `app/services/thesis_draft.py:77-95`
- Modify: `tests/test_zhipu_compat.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `VisitorAIConfig` from Task 1.
- Produces: `call_structured_model(config, instructions, context, schema, schema_name, max_tokens=2400)`.
- Produces: `run_grounded_stream(config, mode, asset, question, event, evidence_items, thesis, recent_messages, snapshot)`.
- Consumed by: Task 3 route changes.

- [ ] **Step 1: Rewrite compatibility tests around explicit configuration**

Use this setup in `tests/test_zhipu_compat.py` and pass `config` to every call:

```python
from app.services.visitor_ai import VisitorAIConfig, visitor_ai_config

ZHIPU_CONFIG = VisitorAIConfig(
    api_key="visitor-key",
    model="glm-5.3",
    base_url="https://open.bigmodel.cn/api/paas/v4",
    resolved_ips=("8.8.8.8",),
)

# In each test:
original_client = ai._client
try:
    fake = FakeClient()
    ai._client = lambda config: fake
    result = ai._call_model(ZHIPU_CONFIG, "system instructions", {"stock": {"code": "600519"}})
    self.assertEqual(result["impact_state"], "insufficient")
finally:
    ai._client = original_client
```

Update the custom schema call to:

```python
result = ai.call_structured_model(
    ZHIPU_CONFIG,
    "整理判断",
    {"messages": []},
    {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    },
    "thesis_draft",
)
```

- [ ] **Step 2: Run compatibility tests and verify signature failures**

Run: `python3 -m unittest tests/test_zhipu_compat.py -v`

Expected: FAIL because `_client`, `_call_model`, and `call_structured_model` do not yet accept `VisitorAIConfig`.

- [ ] **Step 3: Make all provider decisions request-scoped**

Add `httpx>=0.27` to `requirements.txt`. Change the AI service signatures and client creation so outbound requests connect to the already-validated public IP instead of resolving the visitor-controlled hostname a second time:

```python
import httpx
from urllib.parse import urlparse

from .visitor_ai import VisitorAIConfig


def _pin_request_to_validated_ip(config: VisitorAIConfig):
    parsed = urlparse(config.base_url)
    expected_host = parsed.hostname or ""
    authority = expected_host
    if parsed.port and parsed.port != 443:
        authority = f"{authority}:{parsed.port}"

    def pin(request: httpx.Request) -> None:
        if request.url.host != expected_host:
            raise AIError("network", "模型请求目标与已验证地址不一致")
        request.headers["Host"] = authority
        request.extensions["sni_hostname"] = expected_host
        request.url = request.url.copy_with(host=config.resolved_ips[0])

    return pin


def _client(config: VisitorAIConfig):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIError("unknown", "未安装 openai Python 包") from exc
    http_client = httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=settings.ai_timeout_seconds,
        event_hooks={"request": [_pin_request_to_validated_ip(config)]},
    )
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=settings.ai_timeout_seconds,
        max_retries=1,
        http_client=http_client,
    )


def _uses_zhipu_chat_api(config: VisitorAIConfig) -> bool:
    value = config.base_url.lower()
    return "bigmodel.cn" in value or "zhipu" in value


def _zhipu_extra_body(config: VisitorAIConfig) -> dict[str, Any]:
    if config.model.lower().startswith("glm-5.3"):
        return {"reasoning_effort": "low"}
    return {"thinking": {"type": "disabled"}}
```

Add `config` as the first argument to `call_structured_model`, `_call_model`, and `run_grounded_stream`. Replace every use of `settings.openai_model` and `settings.openai_base_url` in model calls and completed SSE payloads with `config.model` and `config.base_url`. Remove `is_configured()` and the `.env` not-configured SSE branch. Remove `save_result`, `analysis_id`, and the `Callable` import from `run_grounded_stream`; emit the completed payload directly with `model: config.model`.

Replace the model exception categorization with:

```python
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if "timeout" in lowered or isinstance(exc, TimeoutError):
            raise AIError("timeout", "模型调用超时") from exc
        if "quota" in lowered or "insufficient" in lowered or "429" in text:
            raise AIError("quota", "模型额度或频率受限") from exc
        if "api key" in lowered or "401" in text or "403" in text:
            raise AIError("auth", "API Key 无效或没有模型权限") from exc
        raise AIError("network", f"模型调用失败: {text[:200]}") from exc
```

Add a unit test that creates an `httpx.Request` for the configured host, invokes `_pin_request_to_validated_ip(ZHIPU_CONFIG)`, and asserts that the URL host becomes `8.8.8.8`, the `Host` header remains `open.bigmodel.cn`, and `request.extensions["sni_hostname"]` remains `open.bigmodel.cn`. Add a second assertion that a request for any different host raises `AIError`. This prevents DNS rebinding while retaining correct TLS certificate validation.

- [ ] **Step 4: Make the dormant thesis generator explicit**

Change `generate_suggestion` to require a configuration even though its route will be disabled:

```python
from .visitor_ai import VisitorAIConfig


def generate_suggestion(
    config: VisitorAIConfig,
    base_version: int,
    thesis: dict | None,
    messages: list[dict],
    evidence: list[dict],
) -> dict:
    result = call_structured_model(
        config,
        instructions=(
            "比较用户已确认判断与所选对话、证据，只整理对判断的新增、修改、删除或不变建议。"
            "不要提供买卖、仓位、目标价或交易时点建议。每项建议必须引用输入中的消息或证据编号。"
        ),
        context={
            "base_version": base_version,
            "current_thesis": thesis,
            "messages": messages,
            "evidence": evidence,
        },
        schema=THESIS_DRAFT_SCHEMA,
        schema_name="thesis_draft",
        max_tokens=2200,
    )
```

- [ ] **Step 5: Run AI unit tests**

Run: `python3 -m unittest tests/test_zhipu_compat.py tests/test_thesis_drafts.py -v`

Expected: all tests PASS; no test mutates `settings.openai_api_key`, `settings.openai_model`, or `settings.openai_base_url`.

- [ ] **Step 6: Commit request-scoped model calls**

```bash
git add app/services/ai.py app/services/thesis_draft.py tests/test_zhipu_compat.py requirements.txt
git commit -m "refactor: make AI clients request scoped"
```

---

### Task 3: Make AI Routes Stateless and Disable Shared Draft Generation

**Files:**
- Modify: `app/routers/research.py:1-86`
- Modify: `app/routers/chat.py:1-130`
- Modify: `app/routers/assets.py:54-65,141-220`
- Modify: `app/routers/theses.py:59-130`
- Create: `tests/test_visitor_ai_routes.py`

**Interfaces:**
- Consumes: `visitor_ai_config` and `run_grounded_stream(config, ...)`.
- Produces: `ChatMessage(role: Literal["user", "assistant"], content: str)` and `ChatRequest.recent_messages` capped at 6.
- Produces: health field `visitor_ai_supported: true`.

- [ ] **Step 1: Write route tests that count database writes**

Create tests with a temporary database, one asset/evidence row, and patched `run_grounded_stream`:

```python
# tests/test_visitor_ai_routes.py
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database as db
from app.main import create_app
from app.services.visitor_ai import VisitorAIConfig, visitor_ai_config


def completed_stream(**kwargs):
    yield "event: completed\ndata: " + json.dumps({
        "mode": kwargs["mode"],
        "question": kwargs["question"],
        "event_id": (kwargs.get("event") or {}).get("event_id"),
        "model": kwargs["config"].model,
        "result": {
            "conclusion": "测试结论",
            "impact_state": "insufficient",
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "next_checks": [],
            "safety_boundary": "不构成投资建议",
        },
    }, ensure_ascii=False) + "\n\n"


class VisitorAIRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_path = db.settings.database_path
        self.original_ready = db._schema_ready
        db.settings.database_path = str(Path(self.tempdir.name) / "test.db")
        db._schema_ready = False
        db.init_db()
        now = db.utcnow()
        self.asset_id = db.execute(
            "INSERT INTO assets (stock_code, stock_name, asset_type, notifications_enabled, created_at, updated_at) "
            "VALUES ('600000', '浦发银行', 'watchlist', 0, ?, ?)", (now, now),
        )
        db.execute(
            "INSERT INTO evidence (evidence_id, stock_code, source_type, source_level, title, excerpt, "
            "published_at, fetched_at, content_status, raw) VALUES "
            "('ev-1', '600000', 'news', 'secondary', '测试事件', '测试摘要', ?, ?, 'excerpt', '{}')",
            (now, now),
        )
        self.client = TestClient(create_app())
        self.headers = {
            "X-TB-API-Key": "visitor-key",
            "X-TB-Model": "test-model",
        }

    def configured_client(self):
        app = create_app()
        app.dependency_overrides[visitor_ai_config] = lambda: VisitorAIConfig(
            api_key="visitor-key",
            model="test-model",
            base_url="https://api.openai.com/v1",
            resolved_ips=("8.8.8.8",),
        )
        return TestClient(app)

    def tearDown(self):
        db.settings.database_path = self.original_path
        db._schema_ready = self.original_ready
        self.tempdir.cleanup()

    def test_missing_visitor_config_is_rejected(self):
        response = self.client.post("/api/research/stream", json={"asset_id": self.asset_id, "event_id": "ev-1"})
        self.assertEqual(response.status_code, 400)

    @patch("app.routers.research.run_grounded_stream", side_effect=completed_stream)
    def test_research_does_not_persist_analysis(self, mocked):
        response = self.configured_client().post(
            "/api/research/stream",
            json={"asset_id": self.asset_id, "event_id": "ev-1"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM analyses")["count"], 0)

    @patch("app.routers.chat.run_grounded_stream", side_effect=completed_stream)
    def test_chat_uses_client_context_without_persistence(self, mocked):
        response = self.configured_client().post(
            "/api/chat/stream",
            json={
                "asset_id": self.asset_id,
                "event_id": "ev-1",
                "question": "影响是什么？",
                "recent_messages": [{"role": "user", "content": "上一问"}],
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked.call_args.kwargs["recent_messages"], [{"role": "user", "content": "上一问"}])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS count FROM messages")["count"], 0)

    def test_overview_omits_shared_ai_history_and_health_reports_capability(self):
        health = self.client.get("/api/health").json()
        self.assertTrue(health["visitor_ai_supported"])
        with patch("app.routers.assets.market_service.snapshot", return_value={"name": "浦发银行"}), \
             patch("app.routers.assets.market_service.history", return_value={"rows": [], "data_time": "2026-09-20"}), \
             patch("app.routers.assets.collect_events", return_value={"events": [], "errors": [], "fetched_at": db.utcnow()}):
            overview = self.client.get(f"/api/assets/{self.asset_id}/overview").json()
        self.assertNotIn("messages", overview)
        self.assertNotIn("analyses", overview)
        self.assertNotIn("latest_analysis", overview)

    def test_ai_thesis_draft_generation_is_unavailable(self):
        response = self.client.post(
            f"/api/assets/{self.asset_id}/thesis-drafts/generate",
            json={"message_ids": [], "evidence_ids": []},
        )
        self.assertEqual(response.status_code, 410)
```

- [ ] **Step 2: Run route tests and verify persistence failures**

Run: `python3 -m unittest tests/test_visitor_ai_routes.py -v`

Expected: FAIL because headers are not dependencies, routes still read/write public AI rows, and draft generation is active.

- [ ] **Step 3: Update research and chat request contracts**

Use explicit dependencies and bounded local context. Preserve the current asset validation and evidence/thesis/snapshot collection in `app/routers/chat.py:49-89`, delete its database message query at current lines 77-81, and replace the persistence/generator section at current lines 91-130 with the generator below:

```python
# app/routers/chat.py
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from ..services.visitor_ai import VisitorAIConfig, visitor_ai_config


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    asset_id: int
    question: str = Field(min_length=1, max_length=2000)
    event_id: Optional[str] = None
    recent_messages: list[ChatMessage] = Field(default_factory=list, max_length=6)


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    config: Annotated[VisitorAIConfig, Depends(visitor_ai_config)],
) -> StreamingResponse:
    generator = run_grounded_stream(
        config=config,
        mode="chat",
        asset=dict(asset),
        question=question,
        event=selected_event,
        evidence_items=evidence_items,
        thesis=thesis,
        recent_messages=[item.model_dump() for item in payload.recent_messages],
        snapshot=snapshot,
    )
    return _sse_response(generator)
```

Apply the same dependency pattern to `research_stream`; pass `recent_messages=[]`. Delete all `save_result`, `save_analysis`, `persist`, and public message-query code from both routes.

- [ ] **Step 4: Remove public AI history from overview and health**

Return this health shape and remove analysis/message queries from `build_overview`:

```python
@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": "AI 投研助手 MVP",
        "visitor_ai_supported": True,
        "database": str(settings.db_file),
        "time": db.utcnow(),
    }
```

The overview response keeps `asset`, `snapshot`, `history`, `events`, `thesis`, errors, times, and stale status; it no longer contains `latest_analysis`, `analyses`, or `messages`.

- [ ] **Step 5: Disable public AI draft generation**

Replace only the generate endpoint body with:

```python
@router.post("/thesis-drafts/generate", status_code=410)
def generate_thesis_draft(asset_id: int, payload: DraftGenerateRequest) -> None:
    _asset_row(asset_id)
    raise HTTPException(
        status_code=410,
        detail="AI 判断草稿暂不支持浏览器本地模式；可继续查看数据和来源。",
    )
```

Remove unused `StreamingResponse`, `AIError`, `generate_suggestion`, `_current_thesis`, and `_sse_response` imports from `app/routers/theses.py`.

- [ ] **Step 6: Run route and existing backend tests**

Run: `python3 -m unittest tests/test_visitor_ai_routes.py tests/test_database_schema.py tests/test_thesis_drafts.py -v`

Expected: all tests PASS and temporary `analyses`/`messages` tables remain empty.

- [ ] **Step 7: Commit stateless routes**

```bash
git add app/routers/research.py app/routers/chat.py app/routers/assets.py app/routers/theses.py tests/test_visitor_ai_routes.py
git commit -m "feat: keep visitor AI results out of shared storage"
```

---

### Task 4: Add Browser Security Headers

**Files:**
- Modify: `app/main.py:12-26`
- Create: `tests/test_security_headers.py`

**Interfaces:**
- Produces: security headers on API and static responses.

- [ ] **Step 1: Write a failing security-header test**

```python
# tests/test_security_headers.py
import unittest

from fastapi.testclient import TestClient

from app.main import create_app


class SecurityHeadersTest(unittest.TestCase):
    def test_static_and_api_responses_have_browser_security_headers(self):
        client = TestClient(create_app())
        for path in ("/", "/api/health"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "strict-origin-when-cross-origin")
            self.assertIn("camera=()", response.headers["permissions-policy"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify headers are absent**

Run: `python3 -m unittest tests/test_security_headers.py -v`

Expected: FAIL with missing `content-security-policy`.

- [ ] **Step 3: Add response middleware before mounting static files**

```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    return response
```

- [ ] **Step 4: Run the security test**

Run: `python3 -m unittest tests/test_security_headers.py -v`

Expected: PASS for `/` and `/api/health`.

- [ ] **Step 5: Commit headers**

```bash
git add app/main.py tests/test_security_headers.py
git commit -m "security: protect browser-local AI credentials"
```

---

### Task 5: Browser-Local AI Configuration and Workspace Module

**Files:**
- Create: `frontend/ai-local.js`
- Create: `tests/ai_local.test.mjs`

**Interfaces:**
- Produces: `loadAIConfig`, `saveAIConfig`, `disableAI`, `clearAIData`, `aiHeaders`.
- Produces: `loadAssetAI`, `saveAnalysis`, `saveConversationTurn`.
- Consumed by: Tasks 6 and 7.

- [ ] **Step 1: Write failing Node tests with an in-memory storage object**

```javascript
// tests/ai_local.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AI_CONFIG_KEY,
  aiHeaders,
  clearAIData,
  disableAI,
  loadAIConfig,
  loadAssetAI,
  saveAIConfig,
  saveAnalysis,
  saveConversationTurn,
} from "../frontend/ai-local.js";

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

class BlockedStorage extends MemoryStorage {
  getItem() { throw new Error("blocked"); }
  setItem() { throw new Error("blocked"); }
  removeItem() { throw new Error("blocked"); }
}

test("AI defaults off and valid configuration survives reload", () => {
  const storage = new MemoryStorage();
  assert.equal(loadAIConfig(storage).enabled, false);
  storage.setItem(AI_CONFIG_KEY, "{broken-json");
  assert.equal(loadAIConfig(storage).enabled, false);
  saveAIConfig({ enabled: true, apiKey: "sk-user", model: "gpt-4.1-mini", baseUrl: "" }, storage);
  assert.deepEqual(aiHeaders(loadAIConfig(storage)), {
    "X-TB-API-Key": "sk-user",
    "X-TB-Model": "gpt-4.1-mini",
    "X-TB-Base-URL": "https://api.openai.com/v1",
  });
});

test("disabling preserves credentials while clearing removes all AI state", () => {
  const storage = new MemoryStorage();
  saveAIConfig({ enabled: true, apiKey: "key", model: "model", baseUrl: "" }, storage);
  saveConversationTurn(7, "question", { result: { conclusion: "answer" } }, storage);
  disableAI(storage);
  assert.equal(loadAIConfig(storage).enabled, false);
  assert.equal(loadAIConfig(storage).apiKey, "key");
  clearAIData(storage);
  assert.equal(loadAIConfig(storage).apiKey, "");
  assert.equal(loadAssetAI(7, storage).messages.length, 0);
});

test("workspace is isolated by asset and capped", () => {
  const storage = new MemoryStorage();
  for (let index = 0; index < 30; index += 1) {
    saveConversationTurn(1, `q-${index}`, { result: { conclusion: `a-${index}` } }, storage);
    saveAnalysis(1, { event_id: `e-${index}`, result: { conclusion: `c-${index}` } }, storage);
  }
  saveConversationTurn(2, "other", { result: { conclusion: "other-answer" } }, storage);
  assert.equal(loadAssetAI(1, storage).messages.length, 50);
  assert.equal(loadAssetAI(1, storage).analyses.length, 20);
  assert.equal(loadAssetAI(2, storage).messages.length, 2);
});

test("blocked browser storage keeps AI off and reports an actionable error", () => {
  const storage = new BlockedStorage();
  assert.equal(loadAIConfig(storage).enabled, false);
  assert.throws(
    () => saveAIConfig({ enabled: true, apiKey: "key", model: "model", baseUrl: "" }, storage),
    /允许本地存储/,
  );
});
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `node --test tests/ai_local.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 3: Implement versioned parsing, validation, and caps**

Implement these exact exports in `frontend/ai-local.js`:

```javascript
export const AI_CONFIG_KEY = "tradingbuddy.ai.config.v1";
export const AI_WORKSPACE_KEY = "tradingbuddy.ai.workspace.v1";
export const SOURCE_TOUR_KEY = "tradingbuddy.tour.sources.v2";
export const AI_TOUR_KEY = "tradingbuddy.tour.ai.v1";
export const DEFAULT_BASE_URL = "https://api.openai.com/v1";

const blankConfig = () => ({ enabled: false, apiKey: "", model: "", baseUrl: "", updatedAt: "" });
const parse = (value, fallback) => {
  try { return JSON.parse(value) ?? fallback; } catch { return fallback; }
};
const browserStorage = () => {
  try { return globalThis.localStorage || null; } catch { return null; }
};
const safeGet = (storage, key) => {
  if (!storage) return null;
  try { return storage.getItem(key); } catch { return null; }
};
const safeSet = (storage, key, value) => {
  if (!storage) throw new Error("浏览器需要允许本地存储才能启用 AI");
  try { storage.setItem(key, value); }
  catch { throw new Error("浏览器需要允许本地存储才能启用 AI"); }
};
const safeRemove = (storage, key) => {
  if (!storage) throw new Error("无法清除本地配置，请允许浏览器站点存储");
  try { storage.removeItem(key); }
  catch { throw new Error("无法清除本地配置，请允许浏览器站点存储"); }
};

export function loadAIConfig(storage = null) {
  const target = storage || browserStorage();
  const value = parse(safeGet(target, AI_CONFIG_KEY), blankConfig());
  return {
    enabled: value.enabled === true,
    apiKey: typeof value.apiKey === "string" ? value.apiKey.slice(0, 512) : "",
    model: typeof value.model === "string" ? value.model.slice(0, 128) : "",
    baseUrl: typeof value.baseUrl === "string" ? value.baseUrl.slice(0, 512) : "",
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  };
}

export function validateAIConfig(input) {
  const value = {
    enabled: input.enabled === true,
    apiKey: String(input.apiKey || "").trim(),
    model: String(input.model || "").trim(),
    baseUrl: String(input.baseUrl || "").trim(),
  };
  if (!value.apiKey || value.apiKey.length > 512) throw new Error("请填写有效的 API Key");
  if (!value.model || value.model.length > 128) throw new Error("请填写有效的模型名称");
  if (value.baseUrl) {
    let parsed;
    try { parsed = new URL(value.baseUrl); }
    catch { throw new Error("API 地址必须是有效的 HTTPS 地址"); }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
      throw new Error("API 地址必须是 HTTPS 公网地址");
    }
  }
  return value;
}

export function saveAIConfig(input, storage = null) {
  const target = storage || browserStorage();
  const value = validateAIConfig(input);
  const saved = { ...value, updatedAt: new Date().toISOString() };
  safeSet(target, AI_CONFIG_KEY, JSON.stringify(saved));
  return saved;
}

export function disableAI(storage = null) {
  const target = storage || browserStorage();
  const value = loadAIConfig(storage);
  safeSet(target, AI_CONFIG_KEY, JSON.stringify({ ...value, enabled: false, updatedAt: new Date().toISOString() }));
}

export function clearAIData(storage = null) {
  const target = storage || browserStorage();
  safeRemove(target, AI_CONFIG_KEY);
  safeRemove(target, AI_WORKSPACE_KEY);
  safeRemove(target, AI_TOUR_KEY);
}

export function aiHeaders(config) {
  if (!config.enabled) throw new Error("请先在设置中启用 AI 分析");
  return {
    "X-TB-API-Key": config.apiKey,
    "X-TB-Model": config.model,
    "X-TB-Base-URL": config.baseUrl || DEFAULT_BASE_URL,
  };
}

function loadWorkspace(storage) {
  const target = storage || browserStorage();
  const value = parse(safeGet(target, AI_WORKSPACE_KEY), { assets: {} });
  return value && typeof value.assets === "object" ? value : { assets: {} };
}

export function loadAssetAI(assetId, storage = null) {
  const asset = loadWorkspace(storage).assets[String(assetId)] || {};
  return {
    messages: Array.isArray(asset.messages) ? asset.messages.slice(-50) : [],
    analyses: Array.isArray(asset.analyses) ? asset.analyses.slice(-20) : [],
  };
}

function updateAsset(assetId, update, storage) {
  const target = storage || browserStorage();
  const workspace = loadWorkspace(target);
  const current = loadAssetAI(assetId, target);
  workspace.assets[String(assetId)] = update(current);
  safeSet(target, AI_WORKSPACE_KEY, JSON.stringify(workspace));
}

export function saveAnalysis(assetId, analysis, storage = null) {
  updateAsset(assetId, (current) => ({ ...current, analyses: [...current.analyses, analysis].slice(-20) }), storage);
}

export function saveConversationTurn(assetId, question, completed, storage = null) {
  const createdAt = new Date().toISOString();
  updateAsset(assetId, (current) => ({
    ...current,
    messages: [
      ...current.messages,
      { role: "user", content: question, created_at: createdAt },
      { role: "assistant", content: JSON.stringify(completed), created_at: createdAt },
    ].slice(-50),
  }), storage);
}
```

- [ ] **Step 4: Run local storage tests**

Run: `node --test tests/ai_local.test.mjs`

Expected: 4 tests PASS.

- [ ] **Step 5: Commit the browser data boundary**

```bash
git add frontend/ai-local.js tests/ai_local.test.mjs
git commit -m "feat: store visitor AI state in the browser"
```

---

### Task 6: Pass Visitor Configuration Through Streaming Requests

**Files:**
- Modify: `frontend/api.js:20-30`
- Modify: `frontend/app.js:1-42,794-842,844-873,932-950`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: `loadAIConfig`, `loadAssetAI`, `saveAnalysis`, `saveConversationTurn`, `aiHeaders`.
- Produces: `streamPost(path, payload, onEvent, signal, headers={})`.

- [ ] **Step 1: Add failing source assertions**

Add to `tests/frontend_prototype.test.mjs`:

```javascript
const aiLocal = readFileSync(path.join(root, "frontend/ai-local.js"), "utf8");

test("AI requests use visitor headers and local results", () => {
  assert.ok(apiModule.includes("headers = {}"));
  assert.ok(app.includes("aiHeaders(state.aiConfig)"));
  assert.ok(app.includes("saveAnalysis(state.assetId"));
  assert.ok(app.includes("saveConversationTurn(state.assetId"));
  assert.ok(app.includes("recent_messages"));
  assert.ok(aiLocal.includes("AI_WORKSPACE_KEY"));
});
```

- [ ] **Step 2: Run frontend tests and verify missing integration**

Run: `node --test tests/frontend_prototype.test.mjs tests/ai_local.test.mjs`

Expected: FAIL because `streamPost` has no custom headers and app state does not use `ai-local.js`.

- [ ] **Step 3: Extend the streaming API and preserve status metadata**

Replace the `streamPost` signature, request options, and non-OK branch with:

```javascript
export async function streamPost(path, payload, onEvent, signal, headers = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...headers },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
}
```

Retain the current byte reader and SSE block parser from `frontend/api.js:31-53` immediately after the new non-OK branch.

- [ ] **Step 4: Load local AI state per selected asset**

Import the local module, then add the listed properties before the closing brace of the existing `state` object:

```javascript
import {
  AI_TOUR_KEY,
  SOURCE_TOUR_KEY,
  aiHeaders,
  clearAIData,
  disableAI,
  loadAIConfig,
  loadAssetAI,
  saveAIConfig,
  saveAnalysis,
  saveConversationTurn,
} from "./ai-local.js";

// Add to the existing state object after toastTimer.
aiConfig: loadAIConfig(),
localMessages: [],
localAnalyses: [],
aiSettingsExpanded: false,
tourKind: "sources",
tourSteps: [],
```

At the end of successful overview loading and asset selection, load the asset-local workspace and derive the current analysis:

```javascript
function loadLocalAIState() {
  const workspace = state.assetId ? loadAssetAI(state.assetId) : { messages: [], analyses: [] };
  state.localMessages = workspace.messages;
  state.localAnalyses = workspace.analyses;
  const latest = [...workspace.analyses].reverse().find(
    (item) => !state.selectedEventId || item.event_id === state.selectedEventId,
  );
  state.analysis = latest?.result || null;
}
```

Do not read `overview.latest_analysis` or `overview.messages`.

- [ ] **Step 5: Store completed SSE payloads locally**

Update `stream` to pass `aiHeaders(state.aiConfig)`. In `runAnalysis`, capture `completed` and call `saveAnalysis`; in `runChat`, send bounded local context and save the successful turn:

```javascript
async function stream(path, payload, onEvent) {
  state.abortController = new AbortController();
  await streamPost(path, payload, onEvent, state.abortController.signal, aiHeaders(state.aiConfig));
}

// runAnalysis callback
if (event === "completed") {
  saveAnalysis(state.assetId, data);
  state.analysis = data.result;
}

// runChat payload and callback. Keep stored JSON for rendering, but send only bounded text.
const recentMessages = state.localMessages.slice(-6).map(({ role, content }) => {
  let bounded = String(content || "");
  if (role === "assistant") {
    try {
      const parsed = JSON.parse(bounded);
      bounded = parsed.result?.conclusion || parsed.conclusion || bounded;
    } catch {
      // Older local entries may already be plain text.
    }
  }
  return { role, content: bounded.slice(0, 2000) };
});
await stream("/chat/stream", {
  asset_id: state.assetId,
  event_id: state.selectedEventId,
  question,
  recent_messages: recentMessages,
}, ({ event, data }) => {
  if (event === "completed") {
    saveConversationTurn(state.assetId, question, data);
    state.analysis = data.result;
  }
  if (event === "failed") showToast(aiErrorMessage(data), "error");
});
loadLocalAIState();
```

Add `aiErrorMessage(data)` mapping `not_configured`, `auth`, `network`, `quota`, `timeout`, and `schema` to the approved actionable Chinese messages. Do not call `loadOverview` after successful AI requests.

- [ ] **Step 6: Run frontend tests**

Run: `node --test tests/frontend_prototype.test.mjs tests/ai_local.test.mjs`

Expected: all tests PASS.

- [ ] **Step 7: Commit local request integration**

```bash
git add frontend/api.js frontend/app.js tests/frontend_prototype.test.mjs
git commit -m "feat: route AI requests through visitor configuration"
```

---

### Task 7: Implement Source-Only Mode, Settings UI, and Branding

**Files:**
- Modify: `frontend/index.html:6-63`
- Modify: `frontend/app.js:68-74,235-349,459-495,646-701,1083-1202`
- Modify: `frontend/styles.css:68-117,879-917,1073-1089`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: local configuration functions from Task 5.
- Produces: `syncAIMode()`, `saveAISettings(form)`, `clearAISettings()`, and conditional source/AI renderers.

- [ ] **Step 1: Write failing visual-contract assertions**

Add this test:

```javascript
test("visitor AI settings preserve the current interaction style", () => {
  assert.ok(index.includes("<span>TradingBuddy</span>"));
  assert.ok(index.includes('id="composer-dock"'));
  assert.ok(index.includes('data-tour="settings"'));
  assert.ok(app.includes('id="ai-settings-form"'));
  assert.ok(app.includes('role="switch"'));
  assert.ok(app.includes("清除本地 AI 配置"));
  assert.ok(app.includes("配置和分析结果仅保存在当前浏览器"));
  assert.ok(app.includes("function syncAIMode"));
  assert.ok(styles.includes(".ai-settings"));
  assert.ok(styles.includes(".composer-dock[hidden]"));
  assert.doesNotMatch(styles, /\.brand span:last-child\s*\{\s*display:\s*none/);
});
```

- [ ] **Step 2: Run the frontend test and verify missing UI**

Run: `node --test tests/frontend_prototype.test.mjs`

Expected: FAIL on the TradingBuddy brand and AI settings form assertions.

- [ ] **Step 3: Update stable HTML targets and cache versions**

In `frontend/index.html`:

```html
<title>TradingBuddy</title>
<link rel="stylesheet" href="/styles.css?v=20260920-visitor-ai">
<!-- Existing brand mark remains unchanged. -->
<span>TradingBuddy</span>
<!-- Add to the existing settings button. -->
data-tour="settings"
<!-- Replace the composer dock opening tag. AI is off until local configuration loads. -->
<div id="composer-dock" class="composer-dock" hidden>
<script type="module" src="/app.js?v=20260920-visitor-ai"></script>
```

- [ ] **Step 4: Render distinct AI-off and AI-on surfaces**

Add the stable element lookup beside the existing `els` entries, then add `aiEnabled()` and use it in render functions:

```javascript
composerDock: $("#composer-dock"),

const aiEnabled = () => state.aiConfig.enabled === true;

function syncAIMode() {
  els.composerDock.hidden = !aiEnabled();
  els.appShell.classList.toggle("ai-disabled", !aiEnabled());
}
```

When AI is off:

- `renderDynamicMessage` uses status `信息源已收集`, removes relative-thesis text, trace link, quick prompts, analysis toggle, and generate button.
- `renderEventPush` omits `data-action="select-event"` and keeps only “查看来源”.
- `renderConversation` renders no local messages and no thesis-draft banner.
- `archiveSheet` uses tabs `data` and `sources`, defaulting to `data`. If `state.archiveTab` still contains the former AI-only `thesis` value when AI is disabled, reset it to `data` before rendering.
- `traceSheet` and all AI thesis-draft open actions are unreachable from rendered UI.

When AI is on, use the existing analysis and composer markup with `state.localMessages` and `state.analysis`. Always omit `renderThesisDraftBanner()` in visitor mode.

During application startup, load `state.aiConfig` and the local AI workspace first, call `syncAIMode()`, and only then run the existing asset/overview loading sequence. This keeps the composer hidden by default and prevents a flash of AI controls for first-time visitors.

- [ ] **Step 5: Build the settings form inside the existing sheet**

Render the current product/data sections followed by:

```html
<section class="detail-section ai-settings" id="ai-settings">
  <div class="setting-row">
    <div class="setting-copy"><strong>AI 分析</strong><span>使用你自己的模型密钥生成分析和继续追问</span></div>
    <button class="switch pressable" type="button" role="switch" data-ai-toggle aria-checked="false" aria-label="启用 AI 分析"></button>
  </div>
  <p class="local-privacy-note">配置和分析结果仅保存在当前浏览器。</p>
  <form id="ai-settings-form" class="sheet-form ai-settings-form">
    <label>API Key<div class="secret-field"><input name="api_key" type="password" autocomplete="off" required><button type="button" class="text-button pressable" data-toggle-api-key>显示</button></div></label>
    <label>模型名称<input name="model" placeholder="例如 gpt-4.1-mini 或 glm-4-flash" required></label>
    <label>API 地址（选填）<input name="base_url" inputmode="url" placeholder="留空使用 OpenAI 官方接口"></label>
    <div class="button-row"><button class="primary-button pressable" type="submit">保存并启用</button></div>
  </form>
  <div class="button-row"><button class="secondary-button pressable" type="button" data-replay-ai-tour>重新查看 AI 使用说明</button><button class="text-button danger pressable" type="button" data-clear-ai>清除本地 AI 配置</button></div>
</section>
```

Populate the three inputs with `escapeHtml(state.aiConfig.apiKey)`, `escapeHtml(state.aiConfig.model)`, and `escapeHtml(state.aiConfig.baseUrl)`. Add these handlers:

```javascript
function saveAISettings(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    state.aiConfig = saveAIConfig({
      enabled: true,
      apiKey: values.api_key,
      model: values.model,
      baseUrl: values.base_url,
    });
    state.aiSettingsExpanded = false;
    loadLocalAIState();
    syncAIMode();
    closeSheet();
    renderConversation();
    showToast("AI 分析已启用", "success");
    requestAnimationFrame(() => startTour("ai"));
  } catch (error) {
    showToast(error.message, "error");
  }
}

function turnOffAI() {
  disableAI();
  state.aiConfig = loadAIConfig();
  state.analysis = null;
  syncAIMode();
  renderSheet();
  renderConversation();
  showToast("AI 分析已关闭");
}

function clearAISettings() {
  const confirmed = window.confirm("将删除本浏览器中的 API Key、模型配置和全部 AI 分析记录。继续吗？");
  if (!confirmed) return;
  clearAIData();
  state.aiConfig = loadAIConfig();
  state.localMessages = [];
  state.localAnalyses = [];
  state.analysis = null;
  state.aiSettingsExpanded = false;
  syncAIMode();
  renderSheet();
  renderConversation();
  showToast("本地 AI 配置已清除");
}
```

When the disabled switch is pressed, set `state.aiSettingsExpanded = true` and rerender the sheet so the form is visible; do not mark AI enabled until form submission succeeds. Turning an enabled switch off calls `turnOffAI()` and retains credentials.

- [ ] **Step 6: Extend existing styles without changing the visual direction**

Add focused rules based on existing tokens:

```css
.composer-dock[hidden] { display: none; }
.app-shell.ai-disabled .conversation { padding-bottom: 72px; }

.ai-settings { scroll-margin-top: 84px; }
.ai-settings-form { margin-top: 16px; }
.local-privacy-note { margin: 12px 0 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.secret-field { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px; }
.secret-field .text-button { min-width: 46px; }
.text-button.danger { color: var(--red); }

@media (max-width: 860px) {
  .topbar { grid-template-columns: minmax(118px, auto) minmax(0, 1fr) auto; gap: 10px; }
  .brand { min-width: 0; gap: 7px; font-size: 14px; }
  .brand-mark { flex: 0 0 auto; }
  .asset-switcher { width: 100%; max-width: 180px; }
  #asset-switcher-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}

@media (max-width: 560px) {
  .topbar { padding: 0 10px; }
  .asset-switcher { max-width: 132px; }
  .top-actions { gap: 0; }
}
```

Delete the existing mobile rule that hides `.brand span:last-child`.

- [ ] **Step 7: Bind settings controls and block accidental AI calls**

Add click handlers for `data-ai-toggle`, `data-toggle-api-key`, `data-clear-ai`, and `data-replay-ai-tour`; add submit handling for `ai-settings-form`. At the start of `runAnalysis` and `runChat`, if AI is disabled, open settings and show `请先配置并启用 AI 分析` instead of making a request.

- [ ] **Step 8: Run frontend tests**

Run: `node --test tests/frontend_prototype.test.mjs tests/ai_local.test.mjs`

Expected: all tests PASS.

- [ ] **Step 9: Commit the UI mode and settings**

```bash
git add frontend/index.html frontend/app.js frontend/styles.css tests/frontend_prototype.test.mjs
git commit -m "feat: add visitor AI settings and source-only mode"
```

---

### Task 8: Split the Existing Tour by Capability

**Files:**
- Modify: `frontend/app.js:68-74,972-1066,1111-1126,1227-1229`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: `SOURCE_TOUR_KEY`, `AI_TOUR_KEY`, and `state.aiConfig.enabled`.
- Produces: `startTour(kind, force=false)` where `kind` is `"sources"` or `"ai"`.

- [ ] **Step 1: Add failing conditional-tour assertions**

```javascript
test("onboarding explains source mode and the first AI enablement", () => {
  assert.ok(app.includes("sourceTourSteps"));
  assert.ok(app.includes("aiTourSteps"));
  assert.ok(app.includes("SOURCE_TOUR_KEY"));
  assert.ok(app.includes("AI_TOUR_KEY"));
  assert.ok(app.includes("打开 AI 设置"));
  assert.ok(app.includes('startTour("ai"'));
});
```

- [ ] **Step 2: Run the test and verify the old single tour fails it**

Run: `node --test tests/frontend_prototype.test.mjs`

Expected: FAIL because only `tourSteps` and the old completion key exist.

- [ ] **Step 3: Define source and AI tour steps**

```javascript
const sourceTourSteps = [
  { target: '[data-tour="asset"]', title: "选择标的", body: "这里只显示你的持仓和自选。点击可切换当前研究标的。" },
  { target: '[data-tour="dynamic"]', title: "查看公开动态", body: "AI 关闭时仍会收集行情、公告、新闻和可核验来源。" },
  { target: ".importance-timeline", title: "识别研究重点", body: "重要性时间线由确定性规则整理，不需要调用大模型。" },
  { target: '[data-tour="archive"]', title: "核验数据与来源", body: "研究档案会保留行情口径和原始来源，便于独立核验。" },
  { target: '[data-tour="settings"]', title: "按需启用 AI", body: "AI 默认关闭。进入设置并填写自己的 API Key 后，可生成分析和继续追问。", action: "open-ai-settings" },
];

const aiTourSteps = [
  { target: '[data-action="run-analysis"]', title: "生成证据约束的分析", body: "分析会区分已知事实、当前推断、未知和下一步核验。" },
  { target: '[data-tour="composer"]', title: "围绕证据继续追问", body: "问题和回答只保存在当前浏览器，不会进入公共数据库。" },
];
```

- [ ] **Step 4: Make tour state capability-aware**

Change `startTour` to select and filter steps that exist in the DOM:

```javascript
function tourWasSeen(storageKey) {
  try { return localStorage.getItem(storageKey) === "true"; }
  catch { return false; }
}

function rememberTour(storageKey) {
  try { localStorage.setItem(storageKey, "true"); }
  catch { /* Source browsing remains usable when storage is blocked. */ }
}

function startTour(kind = aiEnabled() ? "ai" : "sources", force = false) {
  const storageKey = kind === "ai" ? AI_TOUR_KEY : SOURCE_TOUR_KEY;
  if (state.tourActive || (!force && tourWasSeen(storageKey))) return;
  const candidates = kind === "ai" ? aiTourSteps : sourceTourSteps;
  state.tourSteps = candidates.filter((step) => document.querySelector(step.target));
  if (!state.tourSteps.length) return;
  state.tourKind = kind;
  state.tourIndex = 0;
  // Keep the current focus return, inert, layer, and animation setup.
}
```

Update all tour functions to use `state.tourSteps`. `finishTour(true)` calls `rememberTour(state.tourKind === "ai" ? AI_TOUR_KEY : SOURCE_TOUR_KEY)`. If the final source step action is `open-ai-settings`, the final button text is “打开 AI 设置”; its click finishes the tour, sets `state.aiSettingsExpanded = true`, opens the settings sheet, and scrolls `#ai-settings` into view.

After first successful AI settings save, call `startTour("ai")`. The question-mark button calls `startTour(aiEnabled() ? "ai" : "sources", true)`. “重新查看 AI 使用说明” does the same after closing the sheet.

- [ ] **Step 5: Run tour and local storage tests**

Run: `node --test tests/frontend_prototype.test.mjs tests/ai_local.test.mjs`

Expected: all tests PASS and the old `tradingbuddy-tour-complete-v1` key is no longer used.

- [ ] **Step 6: Commit conditional onboarding**

```bash
git add frontend/app.js tests/frontend_prototype.test.mjs
git commit -m "feat: explain AI enablement in existing onboarding"
```

---

### Task 9: Documentation, Full Verification, and Production Deployment

**Files:**
- Modify: `README.md:26-39`
- Verify: all files changed in Tasks 1-8
- Deploy to: `/opt/tradingbuddy` on `42.192.108.82`

**Interfaces:**
- Consumes: completed feature and current systemd/Nginx deployment.
- Produces: updated production site at `https://antiteration.com`.

- [ ] **Step 1: Update user-facing setup documentation**

Replace server `.env` AI setup instructions with:

```markdown
## AI 分析配置

AI 分析默认关闭。行情、重要性时间线、公告、新闻和来源查看不需要模型。

如需启用 AI：

1. 打开页面右上角“设置”；
2. 打开“AI 分析”；
3. 填写自己的 API Key 和模型名称；
4. 使用兼容服务时填写 HTTPS API 地址，留空则使用 OpenAI 官方接口。

API Key、分析和对话仅保存在当前浏览器。服务器只在单次请求中使用配置，不写入 `.env`、日志或 SQLite。清除浏览器站点数据会同时清除这些配置和结果。
```

- [ ] **Step 2: Run all automated tests**

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/*.test.mjs
```

Expected: all Python and Node tests PASS; no warnings expose API keys.

- [ ] **Step 3: Run local HTTP smoke tests**

Run the app on an unused local port and verify:

```bash
APP_PORT=8010 ./start.sh
curl -fsS http://127.0.0.1:8010/api/health
curl -fsSI http://127.0.0.1:8010/ | rg -i 'content-security-policy|x-content-type-options|referrer-policy|permissions-policy'
```

Expected: health contains `"visitor_ai_supported":true`; all four security headers are present.

- [ ] **Step 4: Perform browser acceptance checks before deployment**

Verify in a clean browser profile:

1. The full `TradingBuddy` brand appears at desktop and 390px mobile width.
2. First visit starts the source-only tour and its last action opens AI settings.
3. AI-off mode contains no analysis button, quick prompt, composer, inference tab, or AI draft entry.
4. Saving a valid configuration enables the AI UI and starts the two-step AI tour once.
5. Refresh keeps configuration and local results; disabling retains credentials; clearing removes all AI state.
6. A second clean profile has no configuration or results from the first.
7. Invalid HTTPS/private URL attempts show actionable errors and source browsing remains usable.

- [ ] **Step 5: Commit documentation and final verified state**

```bash
git add README.md
git commit -m "docs: explain visitor-owned AI configuration"
```

- [ ] **Step 6: Deploy without copying local secrets or data**

```bash
rsync -az --exclude='.git/' --exclude='.venv/' --exclude='data/' --exclude='.env' --exclude='__pycache__/' --exclude='.superpowers/' -e 'ssh -i /Users/venest/.ssh/id_ed25519_tradingbuddy -o BatchMode=yes' ./ root@42.192.108.82:/opt/tradingbuddy/
ssh -i /Users/venest/.ssh/id_ed25519_tradingbuddy root@42.192.108.82 'chown -R tradingbuddy:tradingbuddy /opt/tradingbuddy && runuser -u tradingbuddy -- /opt/tradingbuddy/.venv/bin/pip install --no-cache-dir -i https://mirrors.cloud.tencent.com/pypi/simple -r /opt/tradingbuddy/requirements.txt && systemctl restart tradingbuddy && systemctl reload nginx'
```

Expected: transfer completes without `.env` or `data/assistant.db`; both services restart successfully.

- [ ] **Step 7: Verify production and persistence boundaries**

```bash
curl -fsS https://antiteration.com/api/health
curl -fsSI https://antiteration.com/ | rg -i 'content-security-policy|x-content-type-options|referrer-policy|permissions-policy'
ssh -i /Users/venest/.ssh/id_ed25519_tradingbuddy root@42.192.108.82 'systemctl is-active tradingbuddy nginx; cd /opt/tradingbuddy && /opt/tradingbuddy/.venv/bin/python -c "from app import database as db; print(db.query_one(\"SELECT COUNT(*) AS count FROM analyses\")); print(db.query_one(\"SELECT COUNT(*) AS count FROM messages\"))"'
```

Expected: health is OK, security headers are present, both services are `active`, and a browser AI request does not increase the production `analyses` or `messages` counts.

- [ ] **Step 8: Final production browser check**

Open `https://antiteration.com`, complete one real streamed analysis with a temporary visitor key, verify local persistence after refresh, clear the configuration, and confirm the page returns immediately to source-only mode without changing public database counts.
