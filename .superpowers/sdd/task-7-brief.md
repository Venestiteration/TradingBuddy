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
