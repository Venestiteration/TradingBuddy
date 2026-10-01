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

test("production app owns and passes the importance viewport", () => {
  assert.match(appSource, /importanceViewport/);
  assert.match(appSource, /renderImportanceChart\(state\.importanceRows, \{ escapeHtml, viewport: state\.importanceViewport \}\)/);
  assert.match(appSource, /onViewport:\s*\(viewport, action\) =>/);
  assert.match(appSource, /state\.importanceViewport\s*=\s*viewport/);
});
