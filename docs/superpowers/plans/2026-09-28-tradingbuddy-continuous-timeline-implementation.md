# TradingBuddy Continuous Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the primary 30/90-day button interaction with an accessible continuously zoomable and pannable importance timeline that works with mouse, trackpad, keyboard, and touch.

**Architecture:** Keep the existing server endpoint and SVG renderer, but always preload the available 90-day window and maintain a client-side viewport expressed as start/end row indices. Pure viewport transforms drive rendering; a focused interaction binder handles wheel anchoring, drag/pinch, keyboard alternatives, boundary feedback, and cleanup.

**Tech Stack:** Vanilla JavaScript ES modules, SVG, Pointer Events, Wheel Events, CSS touch-action, Node `node:test`, existing FastAPI importance API.

## Global Constraints

- Reuse `GET /api/assets/{asset_id}/importance?days=90`; do not add a chart library.
- Initial view shows the latest 30 trading rows while the loaded domain remains up to 90 rows.
- Wheel/trackpad zoom is centered on the pointer's position inside the plot.
- Pointer drag pans the time window; two-pointer distance changes perform pinch zoom.
- Vertical page scrolling must remain usable; prevent default only for an intentional chart zoom/pan gesture.
- Lines, nodes, markers, and label density derive continuously from the same viewport; no abrupt 30/90 switch.
- Provide zoom-in, zoom-out, earlier, later, and reset controls usable by keyboard and screen readers.
- Show bounded feedback at loaded-data limits and preserve node drill-down behavior.
- Complete every task with its focused tests before moving to the next task.

---

## File Map

- Modify `frontend/importance-chart.js`: pure viewport math, viewport-aware SVG rendering, and gesture/keyboard binding.
- Modify `frontend/app.js`: load 90 days, initialize/reset per-asset viewport, and remove range switching.
- Modify `frontend/styles.css`: interaction affordances, boundary feedback, responsive controls, and `touch-action` behavior.
- Create `tests/frontend_importance_chart.test.mjs`: viewport math, anchored zoom, pan clamping, markup, and gesture contract tests.
- Modify `tests/frontend_prototype.test.mjs`: replace 30/90 assertions with continuous-control assertions.

---

### Task 1: Pure Viewport Model and Viewport-Aware SVG

**Files:**
- Modify: `frontend/importance-chart.js`
- Create: `tests/frontend_importance_chart.test.mjs`

**Interfaces:**
- Produces: `createImportanceViewport(total, initialVisible = 30)`, `zoomImportanceViewport(viewport, scale, anchorRatio)`, `panImportanceViewport(viewport, deltaRows)`, `visibleImportanceRows(rows, viewport)`, and `renderImportanceChart(rows, { escapeHtml, viewport })`.

- [ ] **Step 1: Write failing viewport tests**

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createImportanceViewport,
  panImportanceViewport,
  renderImportanceChart,
  visibleImportanceRows,
  zoomImportanceViewport,
} from "../frontend/importance-chart.js";

const sampleRow = (index) => ({
  date: `2026-06-${String(index + 1).padStart(2, "0")}`,
  status: "complete",
  composite_score: 40 + (index % 20),
  dominant_category: "public",
  summary: `第 ${index + 1} 个交易日`,
  category_scores: { public: 60, upstream: 40, market: 50, cross_asset: 30 },
});

test("initial viewport shows latest 30 of 90 rows", () => {
  assert.deepEqual(createImportanceViewport(90), { start: 60, end: 90, minVisible: 7, total: 90 });
});

test("zoom keeps the pointer anchor stable", () => {
  const zoomed = zoomImportanceViewport(createImportanceViewport(90), 0.5, 0.25);
  assert.equal(zoomed.end - zoomed.start, 15);
  assert.ok(Math.abs((zoomed.start + 0.25 * 15) - (60 + 0.25 * 30)) < 1);
});

test("pan clamps to loaded bounds", () => {
  const viewport = createImportanceViewport(90);
  assert.equal(panImportanceViewport(viewport, 100).end, 90);
  assert.equal(panImportanceViewport(viewport, -100).start, 0);
});

test("renderer removes range buttons and exposes accessible controls", () => {
  const rows = Array.from({ length: 90 }, (_, index) => sampleRow(index));
  const html = renderImportanceChart(rows, { escapeHtml: String, viewport: createImportanceViewport(90) });
  assert.doesNotMatch(html, /data-importance-days/);
  assert.match(html, /data-chart-action="zoom-in"/);
  assert.match(html, /data-chart-action="reset"/);
  assert.match(html, /tabindex="0"/);
});
```

- [ ] **Step 2: Run tests and verify missing exports**

Run: `node --test tests/frontend_importance_chart.test.mjs`

Expected: import failure for the new viewport functions.

- [ ] **Step 3: Implement immutable viewport transforms**

Represent `end` as an exclusive index. Clamp visible span to `[minVisible, total]`. For zoom, preserve `anchor = start + anchorRatio * span`; for pan, preserve span and clamp both edges. Round only when slicing rows; keep intermediate start/end values as numbers so trackpad zoom remains smooth.

- [ ] **Step 4: Render only the current viewport with continuous density**

Map x-coordinates using fractional viewport positions, not the sliced-array index. Set node radius and date-label stride from the visible span: radius interpolates from 6 at 7 rows to 3 at 90 rows; label stride is `max(1, ceil(span / 8))`. Keep paths, nodes, event markers, tooltips, and labels on the same coordinate transform. Add an `aria-label` that states the visible first/last date and loaded boundary.

- [ ] **Step 5: Run viewport tests**

Run: `node --test tests/frontend_importance_chart.test.mjs`

Expected: all viewport and markup tests pass.

- [ ] **Step 6: Commit viewport rendering**

```bash
git add frontend/importance-chart.js tests/frontend_importance_chart.test.mjs
git commit -m "feat: add continuous importance viewport"
```

---

### Task 2: Mouse, Trackpad, Touch, and Keyboard Interaction

**Files:**
- Modify: `frontend/importance-chart.js`
- Modify: `frontend/styles.css`
- Modify: `tests/frontend_importance_chart.test.mjs`

**Interfaces:**
- Consumes: viewport transforms from Task 1.
- Produces: `bindImportanceChart(container, { rows, viewport, onViewport, onOpen, onBoundary, escapeHtml })` with a complete cleanup function.

- [ ] **Step 1: Add failing interaction-contract tests**

Add assertions that the module registers `wheel`, `pointerdown`, `pointermove`, `pointerup`, and `keydown`; computes a wheel anchor from `clientX` and the plot rectangle; calls `preventDefault()` only when `ctrlKey`/`metaKey` or dominant horizontal/zoom intent is present; tracks two pointers for pinch; exposes keyboard actions; and removes every listener in cleanup.

- [ ] **Step 2: Run the focused test**

Run: `node --test tests/frontend_importance_chart.test.mjs`

Expected: new interaction assertions fail.

- [ ] **Step 3: Implement wheel zoom and drag pan**

Normalize wheel delta, use `Math.exp(deltaY * 0.002)` as the scale, and anchor to `(clientX - rect.left) / rect.width`. Begin drag only after primary-pointer movement exceeds 4 px. Translate horizontal pixels to row delta using current span/plot width. Do not call `preventDefault()` for ordinary vertical wheel events, so the conversation page continues scrolling.

- [ ] **Step 4: Implement pinch and pointer cancellation**

Store active pointers by `pointerId`. When two pointers are active, compare current distance to the starting distance and zoom around their midpoint. Call `setPointerCapture()` when available. Handle `pointerup`, `pointercancel`, lost capture, and component cleanup so no pointer state survives a rerender or asset switch.

- [ ] **Step 5: Implement accessible alternative controls and feedback**

Buttons and keyboard shortcuts must invoke the same viewport transforms: `+`/`=` zoom in, `-` zoom out, `ArrowLeft` earlier, `ArrowRight` later, `Home` reset. Announce visible date range through a polite live region. Invoke `onBoundary("start"|"end")` only when an attempted transform crosses the loaded range.

- [ ] **Step 6: Add interaction CSS**

Set the plot surface to `touch-action: pan-y`; use a grabbing cursor only during active drag; keep a visible focus ring; make controls wrap on narrow screens; and respect `prefers-reduced-motion`. Do not set `touch-action: none` on the chart or any ancestor.

- [ ] **Step 7: Run interaction tests**

Run: `node --test tests/frontend_importance_chart.test.mjs`

Expected: all tests pass.

- [ ] **Step 8: Commit multi-input interactions**

```bash
git add frontend/importance-chart.js frontend/styles.css tests/frontend_importance_chart.test.mjs
git commit -m "feat: add accessible timeline zoom and pan"
```

---

### Task 3: App Integration and Timeline Regression

**Files:**
- Modify: `frontend/app.js`
- Modify: `tests/frontend_prototype.test.mjs`

**Interfaces:**
- Consumes: viewport-aware renderer and binder.
- Produces: a per-asset 90-day loaded domain with latest-30 initial view and reset/boundary behavior.

- [ ] **Step 1: Update failing app-contract tests**

Assert `loadOverview()` requests `/importance?days=90`, state holds `importanceViewport`, asset transitions clear it, render passes it into `renderImportanceChart`, binder updates it through `onViewport`, and no `data-importance-days` or `onRange` path remains.

- [ ] **Step 2: Run frontend prototype tests**

Run: `node --test tests/frontend_prototype.test.mjs tests/frontend_importance_chart.test.mjs`

Expected: app-contract assertions fail before integration.

- [ ] **Step 3: Integrate the 90-day domain and viewport state**

Initialize `state.importanceViewport = null`. After a successful 90-day response, set `state.importanceRows` and initialize the viewport only when the asset/generation is still current. Preserve viewport across ordinary rerenders, reset it after refresh only if row count/domain changed, and always reset it on asset switch. Remove `importanceDays` and the asynchronous range-switch handler.

- [ ] **Step 4: Connect rerender-safe cleanup and boundary copy**

Store the binder cleanup function and invoke it before replacing conversation HTML. `onViewport(next)` updates state and rerenders without refetching. `onBoundary` shows `已到达已加载的最早/最新数据`; reset returns to the latest 30 rows. Keep daily-node click and keyboard drill-down behavior unchanged.

- [ ] **Step 5: Run all frontend tests**

Run: `node --test tests/*.test.mjs`

Expected: all frontend tests pass.

- [ ] **Step 6: Validate page-scroll coexistence in a browser**

With a mouse and trackpad, confirm ordinary vertical scrolling moves the page, horizontal drag pans the chart, modifier/intentional wheel zoom centers on the pointer, and the tooltip/node click still works. In mobile emulation, confirm one-finger vertical page scroll and two-finger chart pinch. With keyboard only, confirm focus, zoom, pan, reset, boundary announcement, and day-detail opening.

- [ ] **Step 7: Run complete regression checks**

Run: `python -m unittest discover -s tests -p 'test_*.py' -v && node --test tests/*.test.mjs && git diff --check`

Expected: all Python and frontend tests pass and diff check is clean.

- [ ] **Step 8: Commit integration fixes**

```bash
git add frontend/app.js tests/frontend_prototype.test.mjs
git commit -m "feat: integrate continuous importance timeline"
```
