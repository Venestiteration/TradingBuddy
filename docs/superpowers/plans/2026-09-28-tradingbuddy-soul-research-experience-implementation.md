# TradingBuddy SOUL Research Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-grounded 24-hour event brief, SOUL-guided stock analysis, and progressive event reading experience without changing TradingBuddy's visitor-AI privacy boundary.

**Architecture:** Add a deterministic second-stage event layer above persisted `public_dynamics`, then expose a stable research-brief contract consumed by both the frontend and the AI context selector. AI remains opt-in and stateless on the server: prompt layers and validators constrain visitor-model output, while raw evidence and deterministic reports remain usable when AI fails.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLite, OpenAI-compatible APIs, vanilla JavaScript ES modules, CSS, Python `unittest`, Node `node:test`.

## Global Constraints

- Base every change on commit `fabb14c` through branch `codex/tradingbuddy-research-experience`.
- Keep AI disabled by default; API keys, model configuration, conversations, and AI results remain browser-local.
- Never write visitor AI prompts, outputs, or conversation history to shared SQLite tables.
- Do not infer holdings, cost basis, risk tolerance, or preferences from navigation, wording, defaults, or asset type.
- Title-only evidence may support only a conservative paraphrase of its title; it may not support invented body text, causes, results, or numbers.
- Conflicting evidence must remain visible and must reduce confidence; do not average or silently choose conflicting claims.
- Market movement is coincident context, not evidence of causal intent or fundamentals.
- Do not produce buy/sell, position-sizing, stop-loss, target-price, or timing instructions.
- Preserve existing `/api/research/stream`, `/api/chat/stream`, `dynamic_id`, and public-dynamics routes for compatibility.
- Reuse the existing Python and frontend stacks; add no runtime dependency unless a test demonstrates it is necessary.
- Complete every task with its focused tests before moving to the next task.

---

## File Map

- Create `app/services/research_events.py`: second-stage clustering, conflict retention, attention scoring, and stable `cluster_id` generation.
- Create `app/services/research_brief.py`: deterministic 24-hour report and event-detail payloads.
- Create `app/services/research_context.py`: bounded evidence and recent-message selection for AI calls.
- Create `app/services/research_prompt.py`: compose product constitution, SOUL reasoning, and task prompt layers.
- Create `app/routers/research_brief.py`: deterministic brief/detail and visitor-AI brief stream routes.
- Create `prompts/product_constitution.md`: highest-priority privacy, evidence, and investment-safety rules.
- Create `prompts/research_soul.md`: stable research persona and reasoning discipline derived from the reference repository.
- Create `prompts/research_tasks.md`: task-specific instructions for daily brief, event analysis, and follow-up.
- Create `frontend/research-brief.js`: pure renderers and event-card interaction binding.
- Modify `app/services/ai.py`: expanded schema, prompt composition, strict validation, and one repair attempt.
- Modify `app/routers/research.py` and `app/routers/chat.py`: accept `cluster_id` and use the shared context selector.
- Modify `app/main.py`: register the research-brief router.
- Modify `frontend/app.js`: load and render the brief, expand clusters in place, call AI on demand, and preserve fallback content.
- Modify `frontend/public-dynamics.js`: render source lists and evidence-state labels from an event cluster.
- Modify `frontend/styles.css`: progressive reading hierarchy and all loading/empty/error/conflict states.
- Create `tests/test_research_events.py`, `tests/test_research_brief_api.py`, `tests/test_research_context.py`, `tests/test_research_ai.py`, and `tests/frontend_research_brief.test.mjs`.
- Modify `tests/test_public_dynamics_research.py`, `tests/test_visitor_ai_routes.py`, and `tests/frontend_prototype.test.mjs` for compatibility and end-to-end contracts.

---

### Task 1: Stable Second-Stage Event Clustering

**Files:**
- Create: `app/services/research_events.py`
- Test: `tests/test_research_events.py`

**Interfaces:**
- Consumes: persisted dynamic dictionaries returned by `list_public_dynamics()` plus their linked evidence from `dynamic_evidence()`.
- Produces: `build_research_events(asset_id: int, start: datetime, end: datetime) -> list[dict]` and `get_research_event(asset_id: int, cluster_id: str, start: datetime, end: datetime) -> dict | None`.

- [ ] **Step 1: Write failing clustering and conflict tests**

```python
from datetime import datetime, timezone
from unittest import TestCase

from app.services.research_events import cluster_dynamic_rows


def dynamic(row_id, title, published_at, *, kind="news", summary="", evidence=None):
    return {
        "id": row_id,
        "asset_id": 7,
        "kind": kind,
        "category": "媒体报道" if kind == "news" else "日常经营与重大合同",
        "canonical_title": title,
        "summary": summary,
        "published_at": published_at,
        "importance_score": 70.0,
        "content_status": "excerpt" if summary else "title_only",
        "conflict_status": "none",
        "evidence": evidence or [],
    }


class ResearchEventClusteringTest(TestCase):
    def test_duplicate_media_reports_form_one_stable_cluster(self):
        first = dynamic(11, "公司签署重大供货合同", "2026-09-28T01:00:00+00:00")
        second = dynamic(18, "公司签订重大供货合同", "2026-09-28T03:00:00+00:00")
        events = cluster_dynamic_rows([first, second], now=datetime(2026, 9, 28, 8, tzinfo=timezone.utc))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["cluster_id"], "7:11")
        self.assertEqual(events[0]["dynamic_ids"], [11, 18])

    def test_new_member_does_not_change_cluster_id(self):
        base = [dynamic(11, "公司签署重大供货合同", "2026-09-28T01:00:00+00:00")]
        expanded = base + [dynamic(24, "公司签订重大供货合同", "2026-09-28T04:00:00+00:00")]
        self.assertEqual(cluster_dynamic_rows(base)[0]["cluster_id"], cluster_dynamic_rows(expanded)[0]["cluster_id"])

    def test_conflicting_numbers_are_retained(self):
        rows = [
            dynamic(3, "合同金额为10亿元", "2026-09-28T01:00:00+00:00"),
            dynamic(4, "合同金额为12亿元", "2026-09-28T02:00:00+00:00"),
        ]
        event = cluster_dynamic_rows(rows)[0]
        self.assertEqual(event["conflict_status"], "possible")
        self.assertEqual({item["title"] for item in event["conflicts"]}, {row["canonical_title"] for row in rows})

    def test_market_words_alone_do_not_merge_unrelated_events(self):
        rows = [
            dynamic(1, "公司获得新订单", "2026-09-28T01:00:00+00:00"),
            dynamic(2, "公司股价上涨", "2026-09-28T02:00:00+00:00"),
        ]
        self.assertEqual(len(cluster_dynamic_rows(rows)), 2)
```

- [ ] **Step 2: Run the focused test and verify the missing module failure**

Run: `python -m unittest tests.test_research_events -v`

Expected: `ModuleNotFoundError: No module named 'app.services.research_events'`.

- [ ] **Step 3: Implement conservative clustering and scoring**

Implement these public contracts in `app/services/research_events.py`:

```python
ATTENTION_WEIGHTS = {
    "relevance": 0.30,
    "materiality": 0.25,
    "freshness": 0.20,
    "evidence_quality": 0.15,
    "independent_corroboration": 0.10,
}


def cluster_dynamic_rows(rows: list[dict], now: datetime | None = None) -> list[dict]:
    """Return conservative event clusters sorted by attention_score descending.

    Similar media titles within 36 hours may merge when their normalized Chinese
    bigram Jaccard score is at least 0.72. Announcements may link to media within
    72 hours only when subject terms, event terms, and category agree. A numeric
    or negation mismatch sets conflict_status=possible and retains every claim.
    """


def build_research_events(asset_id: int, start: datetime, end: datetime) -> list[dict]:
    rows = list_public_dynamics(asset_id, start, end, kind="all")
    for row in rows:
        row["evidence"] = dynamic_evidence(row["id"], asset_id=asset_id)
    return cluster_dynamic_rows(rows)


def get_research_event(
    asset_id: int, cluster_id: str, start: datetime, end: datetime
) -> dict | None:
    return next(
        (event for event in build_research_events(asset_id, start, end)
         if event["cluster_id"] == cluster_id),
        None,
    )
```

Each returned event must include exactly these stable fields: `cluster_id`, `asset_id`, `dynamic_ids`, `title`, `summary`, `published_at`, `category`, `kinds`, `content_status`, `conflict_status`, `conflicts`, `attention_score`, `attention_factors`, `source_count`, and `evidence`. Generate `cluster_id` as `f"{asset_id}:{min(dynamic_ids)}"`. Deduplicate evidence by `evidence_id`, prefer primary/full evidence for the lead title, and never synthesize missing summaries.

- [ ] **Step 4: Run clustering tests**

Run: `python -m unittest tests.test_research_events -v`

Expected: all four tests pass.

- [ ] **Step 5: Commit the event layer**

```bash
git add app/services/research_events.py tests/test_research_events.py
git commit -m "feat: add stable research event clustering"
```

---

### Task 2: Deterministic 24-Hour Research Brief API

**Files:**
- Create: `app/services/research_brief.py`
- Create: `app/routers/research_brief.py`
- Modify: `app/main.py`
- Test: `tests/test_research_brief_api.py`

**Interfaces:**
- Consumes: `build_research_events()` and `get_research_event()` from Task 1.
- Produces: `build_research_brief(asset: dict, hours: int = 24, now: datetime | None = None) -> dict`, `GET /api/assets/{asset_id}/research-brief?hours=24`, and `GET /api/assets/{asset_id}/research-events/{cluster_id}`.

- [ ] **Step 1: Write API tests for complete, title-only, conflict, and empty states**

```python
def sample_event(**overrides):
    event = {
        "cluster_id": "1:10",
        "asset_id": 1,
        "dynamic_ids": [10],
        "title": "公司签署重大供货合同",
        "summary": "公司披露已签署供货合同。",
        "published_at": "2026-09-28T01:00:00+00:00",
        "category": "日常经营与重大合同",
        "kinds": ["announcement", "news"],
        "content_status": "excerpt",
        "conflict_status": "none",
        "conflicts": [],
        "attention_score": 86.0,
        "attention_factors": {},
        "source_count": 2,
        "evidence": [{
            "evidence_id": "e1",
            "title": "公司签署重大供货合同",
            "excerpt": "公司披露已签署供货合同。",
            "source_level": "primary",
            "source_type": "announcement",
            "content_status": "excerpt",
            "published_at": "2026-09-28T01:00:00+00:00",
            "source_url": "https://example.test/e1",
        }],
    }
    event.update(overrides)
    return event


class ResearchBriefAPITest(unittest.TestCase):
    @patch("app.services.research_brief.build_research_events")
    def test_brief_is_an_event_report_not_a_single_news_copy(self, events):
        events.return_value = [sample_event(source_count=3)]
        body = self.client.get(f"/api/assets/{self.asset_id}/research-brief?hours=24").json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["headline"]["cluster_id"], "1:10")
        self.assertIn("known_facts", body)
        self.assertIn("why_it_matters", body)
        self.assertIn("impact_paths", body)
        self.assertIn("unknowns", body)
        self.assertEqual(body["coverage"]["event_count"], 1)

    @patch("app.services.research_brief.build_research_events")
    def test_title_only_never_creates_causes_or_numbers(self, events):
        events.return_value = [sample_event(content_status="title_only", summary="")]
        body = self.client.get(f"/api/assets/{self.asset_id}/research-brief?hours=24").json()
        self.assertEqual(body["known_facts"][0]["claim"], events.return_value[0]["title"])
        self.assertEqual(body["why_it_matters"], [])
        self.assertEqual(body["impact_paths"], [])
        self.assertIn("当前仅有标题", body["unknowns"][0])

    @patch("app.services.research_brief.build_research_events", return_value=[])
    def test_empty_brief_is_readable(self, _events):
        body = self.client.get(f"/api/assets/{self.asset_id}/research-brief?hours=24").json()
        self.assertEqual(body["status"], "empty")
        self.assertEqual(body["events"], [])

    @patch("app.services.research_brief.build_research_events")
    def test_conflict_is_preserved(self, events):
        events.return_value = [sample_event(conflict_status="possible", conflicts=[{"title": "10亿元"}, {"title": "12亿元"}])]
        body = self.client.get(f"/api/assets/{self.asset_id}/research-brief?hours=24").json()
        self.assertEqual(body["conflict_status"], "possible")
        self.assertTrue(any("冲突" in item for item in body["unknowns"]))
```

- [ ] **Step 2: Run tests and verify missing route failures**

Run: `python -m unittest tests.test_research_brief_api -v`

Expected: requests return `404` because the new router is not registered.

- [ ] **Step 3: Implement deterministic report construction**

`build_research_brief()` must return this shape for every request, including empty and degraded states:

```python
{
    "status": "ready",  # ready | empty | degraded
    "window": {"hours": 24, "start": start.isoformat(), "end": end.isoformat()},
    "headline": {"cluster_id": event["cluster_id"], "title": event["title"]},
    "core_conclusion": event["summary"] or event["title"],
    "known_facts": [
        {"claim": fact_text, "evidence_ids": evidence_ids, "basis": "evidence"}
    ],
    "why_it_matters": rule_explanations,
    "impact_paths": rule_impact_paths,
    "inferences": [],
    "unknowns": unknowns,
    "watch_signals": watch_signals,
    "sources": public_sources,
    "coverage": {"event_count": len(events), "source_count": source_count},
    "conflict_status": event["conflict_status"],
    "events": events,
}
```

Use category-to-explanation rules only when clearly labeled with `basis="rule"`. For `title_only`, leave `why_it_matters` and `impact_paths` empty. `sources` must expose only public evidence fields and never raw document text. Use the top `attention_score` event as `headline`, while `coverage` and the body remain derived from all events in the 24-hour window.

- [ ] **Step 4: Implement and register the router**

Add the following routes to `app/routers/research_brief.py` and include the router in `app/main.py` before the static mount:

```python
@router.get("/assets/{asset_id}/research-brief")
def research_brief(asset_id: int, hours: int = Query(24, ge=24, le=24)) -> dict:
    return build_research_brief(_asset_row(asset_id), hours=hours)


@router.get("/assets/{asset_id}/research-events/{cluster_id}")
def research_event_detail(asset_id: int, cluster_id: str) -> dict:
    asset = _asset_row(asset_id)
    end = datetime.now(timezone.utc)
    event = get_research_event(asset["id"], cluster_id, end - timedelta(days=90), end)
    if event is None:
        raise HTTPException(status_code=404, detail="研究事件不存在或不属于当前标的")
    return {"event": event, "fetched_at": db.utcnow()}
```

- [ ] **Step 5: Run API and existing public-dynamics tests**

Run: `python -m unittest tests.test_research_brief_api tests.test_public_dynamics_api tests.test_public_dynamics_research -v`

Expected: all tests pass; existing endpoints retain their previous payloads.

- [ ] **Step 6: Commit the deterministic brief**

```bash
git add app/services/research_brief.py app/routers/research_brief.py app/main.py tests/test_research_brief_api.py
git commit -m "feat: add deterministic daily research brief"
```

---

### Task 3: Four-Layer SOUL Prompt Stack and Bounded Context

**Files:**
- Create: `prompts/product_constitution.md`
- Create: `prompts/research_soul.md`
- Create: `prompts/research_tasks.md`
- Create: `app/services/research_prompt.py`
- Create: `app/services/research_context.py`
- Test: `tests/test_research_context.py`

**Interfaces:**
- Consumes: asset, optional cluster, deterministic brief, snapshot, confirmed thesis, evidence rows, question, and browser-supplied recent messages.
- Produces: `compose_research_prompt(mode: str) -> str`, `classify_question_focus(question: str) -> str`, and `select_research_context(asset: dict, question: str, snapshot: dict | None, selected_event: dict | None, daily_brief: dict, evidence_items: list[dict], thesis: dict | None, recent_messages: list[dict]) -> dict` with at most 12 evidence items and 6 messages.

- [ ] **Step 1: Write prompt-order and context-bound tests**

```python
def sample_evidence(index):
    return {
        "evidence_id": f"e{index}",
        "source_type": "news",
        "source_level": "secondary",
        "title": f"合同进展 {index}",
        "excerpt": f"公司披露合同进展 {index}",
        "published_at": f"2026-09-{28 - min(index, 20):02d}T01:00:00+00:00",
        "content_status": "excerpt",
    }


def selected_event(evidence):
    return {
        "cluster_id": "1:10",
        "title": "公司合同进展",
        "published_at": "2026-09-28T01:00:00+00:00",
        "conflict_status": "none",
        "evidence": evidence,
    }


class ResearchContextTest(unittest.TestCase):
    def test_prompt_layers_product_constitution_first(self):
        prompt = compose_research_prompt("event")
        self.assertLess(prompt.index("产品宪法"), prompt.index("研究思维"))
        self.assertLess(prompt.index("研究思维"), prompt.index("任务模板"))
        self.assertIn("不推断用户持仓", prompt)
        self.assertIn("结论前置", prompt)

    def test_context_is_bounded_and_selected_cluster_first(self):
        evidence = [sample_evidence(index) for index in range(20)]
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同对盈利有什么影响？",
            snapshot={"price": 10.2},
            selected_event=selected_event(evidence[:3]),
            daily_brief={"events": []},
            evidence_items=evidence,
            thesis=None,
            recent_messages=[{"role": "user", "content": str(i)} for i in range(9)],
        )
        self.assertLessEqual(len(context["evidence"]), 12)
        self.assertLessEqual(len(context["recent_messages"]), 6)
        self.assertEqual(context["evidence"][0]["evidence_id"], evidence[0]["evidence_id"])
        self.assertNotIn("assumed_risk_tolerance", context)

    def test_old_ai_answer_is_conversation_not_evidence(self):
        evidence = [sample_evidence(1)]
        context = select_research_context(
            asset={"stock_code": "600000", "stock_name": "浦发银行"},
            question="合同有什么影响？",
            snapshot=None,
            selected_event=selected_event(evidence),
            daily_brief={"events": []},
            evidence_items=evidence,
            thesis=None,
            recent_messages=[
                {"role": "assistant", "content": "assistant-answer 是上一轮模型文本"}
            ],
        )
        ids = {item["evidence_id"] for item in context["evidence"]}
        self.assertNotIn("assistant-answer", ids)

    def test_question_focus_changes_density_not_safety(self):
        self.assertEqual(classify_question_focus("这个市盈率是什么意思？"), "concept")
        self.assertEqual(classify_question_focus("我现在很恐慌怎么办？"), "emotion")
        self.assertEqual(classify_question_focus("这件事影响公司利润吗？"), "asset_analysis")
```

- [ ] **Step 2: Run tests and verify imports fail**

Run: `python -m unittest tests.test_research_context -v`

Expected: missing `research_prompt` and `research_context` modules.

- [ ] **Step 3: Write the three prompt layers**

`product_constitution.md` must explicitly state evidence-only facts, title-only limits, conflict retention, visitor privacy, no inferred holdings/preferences, market-data causality limits, no trading instruction, and unknown-state requirements. `research_soul.md` must encode conclusion-first explanation, key tension, plain-language translation, material company variables, impact paths, contrary evidence, and verification signals. `research_tasks.md` must define separate daily-brief, event, and follow-up modes without embedding historical examples or claims.

Implement deterministic composition:

```python
PROMPT_FILES = {
    "constitution": ROOT_DIR / "prompts" / "product_constitution.md",
    "soul": ROOT_DIR / "prompts" / "research_soul.md",
    "tasks": ROOT_DIR / "prompts" / "research_tasks.md",
}


def compose_research_prompt(mode: str) -> str:
    if mode not in {"daily", "event", "chat"}:
        raise ValueError(f"unsupported research mode: {mode}")
    layers = [PROMPT_FILES[name].read_text(encoding="utf-8").strip()
              for name in ("constitution", "soul", "tasks")]
    return "\n\n".join([*layers, f"当前任务模式：{mode}"])
```

- [ ] **Step 4: Implement bounded context selection**

Use these rules in `select_research_context()`: selected-cluster evidence first; then main daily-cluster evidence; then question-overlap evidence from the last 90 days; deduplicate by `evidence_id`; cap at 12. Retain only the last 6 messages whose normalized tokens overlap the question or selected event, cap each at 2000 characters, and label them as conversation context rather than evidence. Include only explicitly confirmed thesis fields. Add a fixed `product_boundary` string and never include `asset_type`, `quantity`, or `cost_price` as inferred user state.

Implement `classify_question_focus()` as a bounded presentation hint with values `information`, `asset_analysis`, `trading_plan`, `emotion`, and `concept`. Store it in context as `question_focus`; it may change ordering and information density only. It must never weaken the product constitution, infer user state, generate trading instructions, or trigger new external data collection.

- [ ] **Step 5: Run context tests**

Run: `python -m unittest tests.test_research_context -v`

Expected: all tests pass.

- [ ] **Step 6: Commit prompt and context layers**

```bash
git add prompts/product_constitution.md prompts/research_soul.md prompts/research_tasks.md app/services/research_prompt.py app/services/research_context.py tests/test_research_context.py
git commit -m "feat: add SOUL prompt and bounded research context"
```

---

### Task 4: Structured AI Output and Evidence Validation

**Files:**
- Modify: `app/services/ai.py`
- Test: `tests/test_research_ai.py`
- Modify: `tests/test_zhipu_compat.py`

**Interfaces:**
- Consumes: `compose_research_prompt(mode)` and selected context from Task 3.
- Produces: `RESEARCH_SCHEMA`, `validate_research_result(result, evidence_lookup, conflict_status)`, and SSE `completed` payloads with the expanded result shape.

- [ ] **Step 1: Write failing schema and validator tests**

```python
def sample_evidence():
    return {
        "evidence_id": "e1",
        "title": "公司签署合同",
        "excerpt": "公司披露已签署合同",
        "content_status": "excerpt",
        "source_type": "announcement",
        "source_level": "primary",
        "published_at": "2026-09-28T01:00:00+00:00",
    }


def valid_result(**overrides):
    result = {
        "answer_mode": "event",
        "core_conclusion": "事件值得跟踪，但证据尚不足以确认财务影响。",
        "key_tension": "合同已披露，但履约与收入确认尚待核验。",
        "impact_state": "watch",
        "sections": [],
        "facts": [{"claim": "公司签署合同", "evidence_ids": ["e1"]}],
        "impact_paths": [],
        "inferences": [],
        "unknowns": ["尚不清楚收入确认时点"],
        "watch_signals": ["后续履约公告"],
        "thesis_relationship": "尚未触及已确认判断的失效条件。",
        "follow_up_question": "是否要继续核验合同履约节点？",
        "confidence": "medium",
        "safety_boundary": "以上为研究信息整理，不构成投资建议。",
    }
    result.update(overrides)
    return result


class ResearchAIValidationTest(unittest.TestCase):
    def test_title_only_claim_cannot_add_number(self):
        lookup = {"e1": {"title": "公司签署合同", "excerpt": "", "content_status": "title_only"}}
        result = valid_result(facts=[{"claim": "合同金额10亿元", "evidence_ids": ["e1"]}])
        with self.assertRaises(AIError):
            validate_research_result(result, lookup, "none")

    def test_conflict_caps_confidence_and_requires_unknown(self):
        result = valid_result(confidence="high", unknowns=[])
        cleaned, notes = validate_research_result(result, {"e1": sample_evidence()}, "possible")
        self.assertEqual(cleaned["confidence"], "low")
        self.assertTrue(any("冲突" in item for item in cleaned["unknowns"]))

    def test_invalid_reference_is_rejected(self):
        result = valid_result(facts=[{"claim": "事实", "evidence_ids": ["missing"]}])
        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")

    def test_trading_instruction_is_rejected(self):
        result = valid_result(core_conclusion="建议买入并设置止损")
        with self.assertRaises(AIError):
            validate_research_result(result, {"e1": sample_evidence()}, "none")
```

- [ ] **Step 2: Run tests and verify the new validator is missing**

Run: `python -m unittest tests.test_research_ai -v`

Expected: import failure for `validate_research_result`.

- [ ] **Step 3: Replace the old analysis schema with the research schema**

The strict schema must require these fields and reject additional properties:

```python
{
    "answer_mode": "daily|event|question",
    "core_conclusion": "string",
    "key_tension": "string",
    "impact_state": "unaffected|watch|may_affect|insufficient",
    "sections": [{"heading": "string", "body": "string", "evidence_ids": ["string"]}],
    "facts": [{"claim": "string", "evidence_ids": ["string"]}],
    "impact_paths": [{"path": "string", "evidence_ids": ["string"], "uncertainty": "string"}],
    "inferences": [{"claim": "string", "evidence_ids": ["string"], "uncertainty": "string"}],
    "unknowns": ["string"],
    "watch_signals": ["string"],
    "thesis_relationship": "string",
    "follow_up_question": "string",
    "confidence": "low|medium|high",
    "safety_boundary": "string"
}
```

Keep `conclusion` and `next_checks` aliases only in the final SSE payload for old frontend compatibility; derive them from `core_conclusion` and `watch_signals` rather than asking the model for duplicate fields.

- [ ] **Step 4: Implement strict validation and one repair attempt**

Reject, rather than silently relabel, invalid citations, title-only numeric additions, and trading instructions. Check numeric tokens in `facts` and `sections` against the cited title/excerpt or whitelisted snapshot fields. When `conflict_status == "possible"`, force confidence to `low`, impact state to `insufficient`, and append a conflict unknown. Keep the existing two-attempt loop: the first validation failure is supplied to the model as repair feedback; the second failure emits `failed` and no AI result.

- [ ] **Step 5: Use the composed prompt and selected context**

Change `run_grounded_stream()` to receive the already selected `context` and `conflict_status`, call `compose_research_prompt(mode)`, and emit both the new shape and compatibility aliases. Do not persist the result. Ensure OpenAI Responses and Chat JSON-mode paths continue using the same strict schema and validation.

- [ ] **Step 6: Run validator and provider compatibility tests**

Run: `python -m unittest tests.test_research_ai tests.test_zhipu_compat -v`

Expected: all tests pass for Responses and Chat modes.

- [ ] **Step 7: Commit AI quality changes**

```bash
git add app/services/ai.py tests/test_research_ai.py tests/test_zhipu_compat.py
git commit -m "feat: enforce SOUL research output validation"
```

---

### Task 5: Cluster-Aware Research and Follow-Up Routes

**Files:**
- Modify: `app/routers/research.py`
- Modify: `app/routers/chat.py`
- Modify: `app/routers/research_brief.py`
- Modify: `tests/test_public_dynamics_research.py`
- Modify: `tests/test_visitor_ai_routes.py`

**Interfaces:**
- Consumes: `cluster_id`, `build_research_brief()`, `get_research_event()`, and `select_research_context()`.
- Produces: cluster-aware `/api/research/stream`, `/api/chat/stream`, and `/api/research-brief/stream` while retaining old IDs.

- [ ] **Step 1: Add failing route tests**

Add tests that submit `cluster_id="1:10"`, assert every cluster evidence item reaches `run_grounded_stream`, assert the latest relevant browser messages are bounded to six, assert another asset's cluster returns 404, and assert `analyses`/`messages` row counts remain unchanged. Add a failure test proving `/api/research-brief/stream` emits `failed` while `GET /research-brief` still returns deterministic data.

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_public_dynamics_research tests.test_visitor_ai_routes -v`

Expected: `cluster_id` is ignored or rejected and the new stream route returns 404.

- [ ] **Step 3: Extend request models without breaking old clients**

```python
class ResearchRequest(BaseModel):
    asset_id: int
    cluster_id: str | None = Field(default=None, max_length=80)
    event_id: str | None = Field(default=None, max_length=160)
    dynamic_id: int | None = None


class ChatRequest(BaseModel):
    asset_id: int
    question: str = Field(min_length=1, max_length=2000)
    cluster_id: str | None = Field(default=None, max_length=80)
    event_id: str | None = Field(default=None, max_length=160)
    dynamic_id: int | None = None
    recent_messages: list[ChatMessage] = Field(default_factory=list, max_length=6)
```

Resolve context in priority order: `cluster_id`, `dynamic_id`, `event_id`, then daily headline. A client-supplied ID must belong to the current asset or return 404. Use 90 days only for context retrieval; the default brief remains 24 hours.

- [ ] **Step 4: Add the daily AI stream route**

`POST /api/research-brief/stream` accepts `asset_id`, optional `cluster_id`, and optional `question`. It obtains visitor config through `visitor_ai_config`, builds deterministic context first, then streams the validated AI interpretation. It never mutates the database.

- [ ] **Step 5: Run route tests and privacy assertions**

Run: `python -m unittest tests.test_public_dynamics_research tests.test_visitor_ai_routes -v`

Expected: all tests pass and database AI-history counts remain zero.

- [ ] **Step 6: Commit cluster-aware routes**

```bash
git add app/routers/research.py app/routers/chat.py app/routers/research_brief.py tests/test_public_dynamics_research.py tests/test_visitor_ai_routes.py
git commit -m "feat: make research routes event-cluster aware"
```

---

### Task 6: Progressive Research Brief and Event Reading UI

**Files:**
- Create: `frontend/research-brief.js`
- Modify: `frontend/public-dynamics.js`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`
- Create: `tests/frontend_research_brief.test.mjs`
- Modify: `tests/frontend_public_dynamics.test.mjs`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: deterministic brief and event-detail API payloads plus browser-local AI results keyed by asset and `cluster_id`.
- Produces: `renderResearchBrief(brief, options)`, `renderResearchEvents(events, options)`, and `bindResearchBrief(container, handlers)`.

- [ ] **Step 1: Write renderer and interaction tests**

```javascript
const escapeHtml = (value) => String(value);
const sampleEvent = (overrides = {}) => ({
  cluster_id: "1:10",
  title: "公司签署重大供货合同",
  summary: "公司披露已签署供货合同。",
  published_at: "2026-09-28T01:00:00+00:00",
  source_count: 2,
  content_status: "excerpt",
  conflict_status: "none",
  evidence: [],
  ...overrides,
});
const sampleBrief = () => ({
  status: "ready",
  core_conclusion: "公司今日披露了新的合同事件。",
  known_facts: [{ claim: "已签署合同", evidence_ids: ["e1"] }],
  why_it_matters: [{ text: "可能影响未来订单转化", basis: "rule" }],
  impact_paths: [{ text: "订单→履约→收入确认", basis: "rule" }],
  unknowns: ["履约时间未确认"],
  watch_signals: ["后续履约公告"],
  events: [sampleEvent()],
});

test("daily report renders synthesis before source cards", () => {
  const html = renderResearchBrief(sampleBrief(), { escapeHtml });
  assert.ok(html.indexOf("今天真正发生了什么") < html.indexOf("查看来源"));
  assert.match(html, /为什么重要/);
  assert.match(html, /影响路径/);
  assert.match(html, /还有什么不确定/);
});

test("duplicate source reports remain one expandable cluster", () => {
  const html = renderResearchEvents([sampleEvent({ source_count: 3 })], { escapeHtml });
  assert.equal((html.match(/data-research-cluster=/g) || []).length, 1);
  assert.match(html, /3 个来源/);
  assert.match(html, /aria-expanded="false"/);
});

test("title-only and conflict states are explicit", () => {
  const html = renderResearchEvents([
    sampleEvent({ content_status: "title_only" }),
    sampleEvent({ cluster_id: "1:12", conflict_status: "possible" }),
  ], { escapeHtml });
  assert.match(html, /仅标题/);
  assert.match(html, /来源存在差异/);
});
```

- [ ] **Step 2: Run the Node test and verify the missing module failure**

Run: `node --test tests/frontend_research_brief.test.mjs`

Expected: module-not-found failure for `frontend/research-brief.js`.

- [ ] **Step 3: Implement pure renderers and binder**

`renderResearchBrief()` must render: status/coverage, core conclusion, known facts with source buttons, why-it-matters, impact paths, unknowns, watch signals, and an opt-in `展开 AI 解读` action. `renderResearchEvents()` must render one card per cluster with title, time, evidence state, two-line summary, source count, conflict badge, an in-place disclosure region, and a `查看来源` list. `bindResearchBrief()` must delegate expand, source, and AI actions and return a cleanup callback.

- [ ] **Step 4: Load the brief without coupling it to AI**

In `loadOverview()`, fetch `/overview`, `/theses`, `/importance?days=90`, and `/research-brief?hours=24`. A brief failure sets `researchBriefError` but does not replace overview, raw events, or the timeline. Reset brief, expanded cluster, and cluster-scoped analysis on asset transition.

- [ ] **Step 5: Replace the top single-news presentation without turning the landing page into a feed**

Replace `renderDynamicMessage(asset, event)` with `renderResearchBriefMessage(asset, state.researchBrief)`. The landing conversation shows only the synthesized daily report and a clear entry into public dynamics; it must not render the complete event feed. Render compact progressive event-cluster cards inside the existing public-dynamics sheet opened from that entry. Allow only one cluster in that sheet to expand at a time, preserve the user's sheet context on source drill-down/back, and keep raw source links readable when AI is disabled or failed.

- [ ] **Step 6: Connect on-demand AI and follow-up context**

Send `cluster_id` from the expanded or selected event to `/api/research-brief/stream` and `/api/chat/stream`. Store returned analysis in the existing browser workspace with `cluster_id`; never send it back as evidence. When AI fails, show a compact inline failure state and leave the deterministic brief, cluster summary, evidence list, and external links intact.

- [ ] **Step 7: Add complete UI states and accessible styling**

Add CSS and copy for skeleton/loading, empty 24-hour window, deterministic-report failure, AI generation failure, unavailable source URL, title-only, excerpt/full, and source conflict. Disclosure buttons must expose `aria-expanded` and `aria-controls`; status changes use a polite live region; source links open with `rel="noreferrer"`; focus remains on the disclosure trigger after collapse.

- [ ] **Step 8: Run frontend tests**

Run: `node --test tests/frontend_research_brief.test.mjs tests/frontend_public_dynamics.test.mjs tests/frontend_prototype.test.mjs tests/ai_local.test.mjs`

Expected: all tests pass; no test expects the removed 30/90 timeline buttons because that change belongs to the continuous-timeline plan.

- [ ] **Step 9: Commit the progressive reading UI**

```bash
git add frontend/research-brief.js frontend/public-dynamics.js frontend/app.js frontend/styles.css tests/frontend_research_brief.test.mjs tests/frontend_public_dynamics.test.mjs tests/frontend_prototype.test.mjs
git commit -m "feat: add progressive event research reading"
```

---

### Task 7: Full Research-Experience Regression and Browser Validation

**Files:**
- Modify only files that fail verification; do not broaden scope.

**Interfaces:**
- Consumes: completed Tasks 1-6.
- Produces: a verified research experience ready to combine with the continuous-timeline plan.

- [ ] **Step 1: Run the complete Python suite**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`

Expected: all tests pass; the previous baseline was 114 passing tests, and the total is now higher.

- [ ] **Step 2: Run the complete frontend suite**

Run: `node --test tests/*.test.mjs`

Expected: all tests pass; the previous baseline was 33 passing tests, and the total is now higher.

- [ ] **Step 3: Run static and diff checks**

Run: `python -m compileall -q app && git diff --check && git status --short`

Expected: compile and diff checks produce no errors; status contains only intentional changes or is clean after task commits.

- [ ] **Step 4: Validate the acceptance scenarios in a local browser**

Start the local app with `uvicorn app.main:app --host 127.0.0.1 --port 8000`. Verify one asset with duplicate reports, one title-only event, one conflict fixture, an AI-disabled session, a successful visitor-AI session, and a forced AI failure. Confirm: one event cluster per real event; an event-level top report; in-place expansion; source traceability; no title-only invention; explicit conflict; relevant follow-up context; and raw data remaining readable after AI failure.

- [ ] **Step 5: Commit only verification fixes**

```bash
git add app frontend tests prompts
git commit -m "fix: close research experience acceptance gaps"
```

Skip this commit when verification requires no code changes.
