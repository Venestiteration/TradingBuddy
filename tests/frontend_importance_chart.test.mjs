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

test("visible rows round fractional viewport boundaries only for slicing", () => {
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
