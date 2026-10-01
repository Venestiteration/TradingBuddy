import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  createImportanceViewport,
  bindImportanceChart,
  panImportanceViewport,
  renderImportanceChart,
  visibleImportanceRows,
  zoomImportanceViewport,
} from "../frontend/importance-chart.js";

const appSource = readFileSync(
  path.join(path.dirname(fileURLToPath(import.meta.url)), "../frontend/app.js"),
  "utf8",
);

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

test("rendered anchor keeps the same x position after zoom", () => {
  const rows = Array.from({ length: 90 }, (_, index) => sampleRow(index));
  const initial = renderImportanceChart(rows, {
    escapeHtml: String,
    viewport: createImportanceViewport(90),
  });
  const zoomed = renderImportanceChart(rows, {
    escapeHtml: String,
    viewport: zoomImportanceViewport(createImportanceViewport(90), 0.5, 0.25),
  });
  const circles = (html) => [...html.matchAll(/<circle[^>]*\bcx="([^\"]+)"/g)]
    .map((match) => Number(match[1]));
  assert.ok(Math.abs(circles(initial)[7] - circles(zoomed)[3]) < 0.001);
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

test("visible rows resolve fractional viewport boundaries only for slicing", () => {
  const rows = Array.from({ length: 10 }, (_, index) => sampleRow(index));
  const viewport = { start: 2.4, end: 7.6, minVisible: 7, total: 10 };
  assert.deepEqual(visibleImportanceRows(rows, viewport).map((row) => row.date), [
    "2026-06-03",
    "2026-06-04",
    "2026-06-05",
    "2026-06-06",
    "2026-06-07",
    "2026-06-08",
  ]);
});

test("fractional viewport edge coordinates stay within the plot", () => {
  const rows = Array.from({ length: 10 }, (_, index) => sampleRow(index));
  const html = renderImportanceChart(rows, {
    escapeHtml: String,
    viewport: { start: 2.4, end: 7.6, minVisible: 7, total: 10 },
  });
  const xCoordinates = [...html.matchAll(/\b(?:cx|x|x1|x2)="([^\"]+)"/g)]
    .map((match) => Number(match[1]));
  assert.ok(xCoordinates.length > 0);
  assert.ok(xCoordinates.every((value) => value >= 42 && value <= 732), xCoordinates.join(", "));
});

test("chart controls report viewport changes through the binder", () => {
  const listeners = new Map();
  const container = {
    querySelector: () => null,
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: () => {},
  };
  const changes = [];
  const viewport = createImportanceViewport(90);
  bindImportanceChart(container, {
    rows: [],
    viewport,
    onViewport: (next, action) => changes.push({ next, action }),
    onOpen: () => {},
    escapeHtml: String,
  });
  const click = (action) => listeners.get("click")({
    target: {
      closest: (selector) => selector === "[data-chart-action]"
        ? { dataset: { chartAction: action } }
        : null,
    },
  });
  click("zoom-in");
  click("reset");
  assert.equal(changes.length, 2);
  assert.equal(changes[0].action, "zoom-in");
  assert.equal(changes[0].next.end - changes[0].next.start, 15);
  assert.deepEqual(changes[1].next, viewport);
});

function interactionContainer() {
  const listeners = new Map();
  const removed = [];
  const surface = {
    getBoundingClientRect: () => ({ left: 100, top: 0, width: 700, height: 230 }),
    classList: { add() {}, remove() {} },
  };
  return {
    listeners,
    removed,
    surface,
    querySelector: (selector) => selector === ".importance-chart-wrap" ? surface : null,
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: (name, handler) => removed.push([name, handler]),
  };
}

test("chart registers wheel and pointer interaction listeners and anchors wheel zoom to clientX", () => {
  const container = interactionContainer();
  const changes = [];
  bindImportanceChart(container, {
    rows: Array.from({ length: 90 }, (_, index) => sampleRow(index)),
    viewport: createImportanceViewport(90),
    onViewport: (next, action) => changes.push({ next, action }),
    onBoundary: () => {},
    onOpen: () => {},
    escapeHtml: String,
  });
  for (const eventName of ["wheel", "pointerdown", "pointermove", "pointerup", "keydown"]) {
    assert.equal(typeof container.listeners.get(eventName), "function", eventName);
  }
  let prevented = false;
  container.listeners.get("wheel")({
    clientX: 275,
    deltaY: -100,
    deltaX: 0,
    ctrlKey: true,
    metaKey: false,
    preventDefault: () => { prevented = true; },
  });
  assert.equal(prevented, true);
  assert.equal(changes.at(-1).action, "wheel-zoom");
  const expectedAnchor = (275 - 100) / 700;
  const next = changes.at(-1).next;
  assert.ok(Math.abs((next.start + expectedAnchor * (next.end - next.start)) - (60 + 0.25 * 30)) < 1);
});

test("ordinary vertical wheel preserves page scrolling while horizontal intent pans", () => {
  const container = interactionContainer();
  const changes = [];
  bindImportanceChart(container, {
    rows: Array.from({ length: 90 }, (_, index) => sampleRow(index)),
    viewport: createImportanceViewport(90),
    onViewport: (next, action) => changes.push({ next, action }),
    onBoundary: () => {},
    onOpen: () => {},
    escapeHtml: String,
  });
  let ordinaryPrevented = false;
  container.listeners.get("wheel")({ deltaX: 0, deltaY: 80, ctrlKey: false, metaKey: false, preventDefault: () => { ordinaryPrevented = true; } });
  assert.equal(ordinaryPrevented, false);
  assert.equal(changes.length, 0);
  let horizontalPrevented = false;
  container.listeners.get("wheel")({
    clientX: 450,
    deltaX: 80,
    deltaY: 10,
    ctrlKey: false,
    metaKey: false,
    preventDefault: () => { horizontalPrevented = true; },
  });
  assert.equal(horizontalPrevented, true);
  assert.equal(changes.at(-1).action, "wheel-pan");
  assert.ok(changes.at(-1).next.start < 60);
});

test("two pointers pinch around their midpoint and cleanup removes every listener", () => {
  const container = interactionContainer();
  const changes = [];
  const cleanup = bindImportanceChart(container, {
    rows: Array.from({ length: 90 }, (_, index) => sampleRow(index)),
    viewport: createImportanceViewport(90),
    onViewport: (next, action) => changes.push({ next, action }),
    onBoundary: () => {},
    onOpen: () => {},
    escapeHtml: String,
  });
  const pointer = (id, clientX, clientY) => ({
    pointerId: id,
    pointerType: "touch",
    isPrimary: id === 1,
    button: 0,
    clientX,
    clientY,
    target: { setPointerCapture() {}, releasePointerCapture() {} },
    preventDefault() {},
  });
  container.listeners.get("pointerdown")(pointer(1, 200, 80));
  container.listeners.get("pointerdown")(pointer(2, 400, 80));
  container.listeners.get("pointermove")(pointer(2, 500, 80));
  assert.equal(changes.at(-1).action, "pinch-zoom");
  assert.ok(changes.at(-1).next.end - changes.at(-1).next.start < 30);
  container.listeners.get("pointerup")(pointer(1, 200, 80));
  cleanup();
  assert.ok(container.removed.length >= container.listeners.size);
});

test("keyboard shortcuts use viewport transforms and report loaded boundaries", () => {
  const container = interactionContainer();
  const changes = [];
  const boundaries = [];
  bindImportanceChart(container, {
    rows: Array.from({ length: 90 }, (_, index) => sampleRow(index)),
    viewport: { start: 0, end: 30, minVisible: 7, total: 90 },
    onViewport: (next, action) => changes.push({ next, action }),
    onBoundary: (edge) => boundaries.push(edge),
    onOpen: () => {},
    escapeHtml: String,
  });
  const key = (key) => container.listeners.get("keydown")({ key, preventDefault() {} });
  key("ArrowLeft");
  key("+");
  key("Home");
  assert.deepEqual(changes.map(({ action }) => action), ["zoom-in", "reset"]);
  assert.deepEqual(boundaries, ["start"]);
});

test("production app owns and passes the importance viewport", () => {
  assert.match(appSource, /importanceViewport/);
  assert.match(appSource, /renderImportanceChart\(state\.importanceRows, \{ escapeHtml, viewport: state\.importanceViewport \}\)/);
  assert.match(appSource, /onViewport:\s*\(viewport, action\) =>/);
  assert.match(appSource, /state\.importanceViewport\s*=\s*viewport/);
});
