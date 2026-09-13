import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const index = readFileSync(path.join(root, "frontend/index.html"), "utf8");
const styles = readFileSync(path.join(root, "frontend/styles.css"), "utf8");
const app = readFileSync(path.join(root, "frontend/app.js"), "utf8");
const apiModule = readFileSync(path.join(root, "frontend/api.js"), "utf8");
const importanceChart = readFileSync(path.join(root, "frontend/importance-chart.js"), "utf8");
const importanceDetail = readFileSync(path.join(root, "frontend/importance-detail.js"), "utf8");

test("MVP preserves the prototype interaction shell", () => {
  for (const marker of [
    'class="conversation-scroll"',
    'id="asset-switcher"',
    'id="asset-popover"',
    'id="detail-sheet"',
    'id="tour-layer"',
    'data-tour="composer"',
  ]) {
    assert.ok(index.includes(marker), `missing prototype shell marker: ${marker}`);
  }

  for (const marker of [
    "--canvas: #f5f5f7",
    "font-family: -apple-system",
    ".sheet.is-open",
    ".tour-popover",
    ".thinking-dots",
    "prefers-reduced-motion",
  ]) {
    assert.ok(styles.includes(marker), `missing prototype visual rule: ${marker}`);
  }

  const appShellBlock = styles.match(/\.app-shell\s*\{([^}]*)\}/s)?.[1] || "";
  assert.match(appShellBlock, /(?:^|;)\s*height\s*:\s*100dvh;/, "app shell must constrain the scroll viewport");

  const workspaceBlock = styles.match(/\.workspace\s*\{([^}]*)\}/s)?.[1] || "";
  assert.match(workspaceBlock, /(?:^|;)\s*height\s*:\s*100%;/, "workspace must fill the grid row");
  assert.match(workspaceBlock, /(?:^|;)\s*overflow\s*:\s*hidden;/, "workspace must contain the scrolling child");

  for (const marker of [
    "function openSheet",
    "function startTour",
    "function positionTour",
    "conversationScroll.scrollTo",
    "requestAnimationFrame",
  ]) {
    assert.ok(app.includes(marker), `missing prototype interaction behavior: ${marker}`);
  }
});

test("importance timeline is keyboard accessible and drillable", () => {
  assert.ok(index.includes('type="module"'));
  assert.ok(app.includes("importanceRows"));
  assert.ok(importanceChart.includes('role="button"'));
  assert.ok(importanceChart.includes('tabindex="0"'));
  assert.ok(importanceChart.includes("aria-label"));
  assert.ok(importanceChart.includes("data-importance-days"));
  assert.ok(importanceDetail.includes("data-importance-category"));
  assert.ok(importanceDetail.includes("data-source-id"));
  assert.ok(importanceDetail.includes("data-add-day-to-thesis"));
  assert.ok(apiModule.includes("export async function api"));
  assert.ok(styles.includes(".importance-timeline"));
  assert.ok(styles.includes("@media (prefers-reduced-motion: reduce)"));
});
