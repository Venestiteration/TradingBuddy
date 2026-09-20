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
const aiLocal = readFileSync(path.join(root, "frontend/ai-local.js"), "utf8");
const importanceChart = readFileSync(path.join(root, "frontend/importance-chart.js"), "utf8");
const importanceDetail = readFileSync(path.join(root, "frontend/importance-detail.js"), "utf8");
const thesisWorkflow = readFileSync(path.join(root, "frontend/thesis-workflow.js"), "utf8");

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

test("conversation conclusions require user confirmation before versioning", () => {
  assert.ok(app.includes("data-build-thesis-draft"));
  assert.ok(app.includes("thesisDraft"));
  assert.ok(thesisWorkflow.includes("data-thesis-message"));
  assert.ok(thesisWorkflow.includes("data-thesis-evidence"));
  assert.ok(thesisWorkflow.includes("data-accept-thesis-field"));
  assert.ok(thesisWorkflow.includes("data-confirm-thesis-version"));
  assert.ok(thesisWorkflow.includes("历史记录"));
  assert.ok(styles.includes(".thesis-draft-banner"));
});

test("AI requests use visitor headers and local results", () => {
  assert.ok(apiModule.includes("headers = {}"));
  assert.ok(app.includes("aiHeaders(state.aiConfig)"));
  assert.ok(app.includes("saveAnalysis(state.assetId"));
  assert.ok(app.includes("saveConversationTurn(state.assetId"));
  assert.ok(app.includes("recent_messages"));
  assert.ok(aiLocal.includes("AI_WORKSPACE_KEY"));
});

test("AI SSE failures do not announce a successful response", () => {
  assert.match(app, /if \(completed\) \{\s*loadLocalAIState\(\);\s*state\.analysis = completed\.result;/);
  assert.match(app, /if \(completedResult\) \{\s*loadLocalAIState\(\);\s*state\.analysis = completedResult\.result;/);
});

test("streamPost sends visitor headers and exposes structured errors", async () => {
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  globalThis.document = { body: { dataset: { apiRoot: "/api" } } };
  try {
    const { streamPost } = await import("../frontend/api.js");
    let request;
    globalThis.fetch = async (url, options) => {
      request = { url, options };
      return {
        ok: true,
        body: { getReader: () => ({ read: async () => ({ done: true }) }) },
      };
    };

    await streamPost("/chat/stream", { question: "q" }, () => {}, null, {
      "X-TB-API-Key": "visitor-key",
      "X-TB-Model": "visitor-model",
    });

    assert.equal(request.url, "/api/chat/stream");
    assert.deepEqual(request.options.headers, {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-TB-API-Key": "visitor-key",
      "X-TB-Model": "visitor-model",
    });

    globalThis.fetch = async () => ({
      ok: false,
      status: 429,
      body: {},
      json: async () => ({ category: "quota", detail: "额度受限" }),
    });
    await assert.rejects(
      () => streamPost("/research/stream", {}, () => {}, null),
      (error) => {
        assert.equal(error.message, "额度受限");
        assert.equal(error.status, 429);
        assert.deepEqual(error.body, { category: "quota", detail: "额度受限" });
        return true;
      },
    );
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("asset switches refresh local AI context before loading overview", () => {
  const selectStart = app.indexOf("function selectAsset");
  const selectEnd = app.indexOf("\nfunction ", selectStart + 1);
  const selectBlock = app.slice(selectStart, selectEnd);
  assert.match(selectBlock, /state\.assetId = id;[\s\S]*loadLocalAIState\(\)/);

  const draftStart = app.indexOf("async function generateThesisDraft");
  const draftEnd = app.indexOf("\nfunction ", draftStart + 1);
  const draftBlock = app.slice(draftStart, draftEnd);
  assert.ok(draftBlock.includes("state.abortController.signal, aiHeaders(state.aiConfig)"));
});
