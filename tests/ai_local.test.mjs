import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AI_CONFIG_KEY,
  AI_WORKSPACE_KEY,
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

test("recent local messages are limited to six and 2000 characters", async () => {
  const { boundRecentMessages } = await import("../frontend/ai-local.js");
  assert.equal(typeof boundRecentMessages, "function");
  const messages = Array.from({ length: 7 }, (_, index) => ({
    role: "user",
    content: `q-${index}`,
  }));
  messages.push({
    role: "assistant",
    content: JSON.stringify({ result: { conclusion: "x".repeat(2400) } }),
  });

  const bounded = boundRecentMessages(messages);

  assert.equal(bounded.length, 6);
  assert.equal(bounded[0].content, "q-2");
  assert.equal(bounded.at(-1).content, "x".repeat(2000));
  assert.ok(bounded.every((message) => message.content.length <= 2000));
});

test("view guard ignores out-of-order overview responses", async () => {
  const { applyIfCurrentView, captureView } = await import("../frontend/ai-local.js");
  assert.equal(typeof applyIfCurrentView, "function");
  const state = { assetId: 1, viewGeneration: 1 };
  const oldView = captureView(state);
  state.assetId = 2;
  state.viewGeneration += 1;
  let applied = false;

  assert.equal(applyIfCurrentView(state, oldView, () => { applied = true; }), false);
  assert.equal(applied, false);
});

test("view guard ignores stale AI completions", async () => {
  const { applyIfCurrentView, captureView } = await import("../frontend/ai-local.js");
  const state = { assetId: 7, viewGeneration: 3 };
  const oldView = captureView(state);
  state.viewGeneration += 1;
  let saved = false;

  assert.equal(applyIfCurrentView(state, oldView, () => { saved = true; }), false);
  assert.equal(saved, false);
  const currentView = captureView(state);
  assert.equal(applyIfCurrentView(state, currentView, () => { saved = true; }), true);
  assert.equal(saved, true);
});

test("asset transitions advance generations and reset the active workspace", async () => {
  const { transitionAssetView, captureView } = await import("../frontend/ai-local.js");
  assert.equal(typeof transitionAssetView, "function");
  const aborted = [];
  const loadedAssets = [];
  const state = {
    assetId: "A",
    viewGeneration: 4,
    busy: true,
    abortController: { abort: () => aborted.push("controller") },
    selectedEventId: "event-a",
    analysis: { conclusion: "old" },
    thesisContext: { old: true },
    thesisDraft: { old: true },
    thesisDraftPending: true,
    thesisAcceptedChanges: { core_thesis: "changed" },
    overview: { old: true },
  };

  transitionAssetView(state, "B", {
    cancelGeneration: () => {
      aborted.push("generation");
      state.busy = false;
      state.abortController = null;
    },
    loadLocalAIState: () => loadedAssets.push(state.assetId),
  });
  const viewB = captureView(state);

  state.abortController = { abort: () => aborted.push("controller") };
  transitionAssetView(state, "A", {
    cancelGeneration: () => aborted.push("unexpected-generation-cancel"),
    loadLocalAIState: () => loadedAssets.push(state.assetId),
  });

  assert.equal(state.assetId, "A");
  assert.equal(state.viewGeneration, 6);
  assert.notDeepEqual(captureView(state), viewB);
  assert.deepEqual(loadedAssets, ["B", "A"]);
  assert.deepEqual(aborted, ["generation", "controller"]);
  assert.equal(state.selectedEventId, null);
  assert.equal(state.analysis, null);
  assert.equal(state.thesisContext, null);
  assert.equal(state.thesisDraft, null);
  assert.equal(state.thesisDraftPending, false);
  assert.deepEqual(state.thesisAcceptedChanges, {});
  assert.equal(state.overview, null);
});

test("refresh guard ignores stale completion and toasts after a switch", async () => {
  const { captureView, runCurrentViewRefresh } = await import("../frontend/ai-local.js");
  assert.equal(typeof runCurrentViewRefresh, "function");
  const state = { assetId: "A", viewGeneration: 8 };
  const view = captureView(state);
  let overviewLoads = 0;
  let successToasts = 0;
  let errorToasts = 0;

  const completed = await runCurrentViewRefresh(
    state,
    view,
    async () => {
      state.assetId = "B";
      state.viewGeneration += 1;
    },
    async () => { overviewLoads += 1; },
    () => { successToasts += 1; },
    () => { errorToasts += 1; },
  );

  assert.equal(completed, false);
  assert.equal(overviewLoads, 0);
  assert.equal(successToasts, 0);
  assert.equal(errorToasts, 0);
});

test("null workspace assets fall back to an empty workspace", () => {
  const storage = new MemoryStorage();
  storage.setItem(AI_WORKSPACE_KEY, JSON.stringify({ assets: null }));
  assert.deepEqual(loadAssetAI(1, storage), { messages: [], analyses: [] });
});

test("array workspace assets fall back to an empty workspace", () => {
  const storage = new MemoryStorage();
  storage.setItem(AI_WORKSPACE_KEY, JSON.stringify({
    assets: [{ messages: [{ role: "assistant", content: "unexpected" }] }],
  }));
  assert.deepEqual(loadAssetAI(0, storage), { messages: [], analyses: [] });
});

test("blocked browser storage keeps AI off and reports an actionable error", () => {
  const storage = new BlockedStorage();
  assert.equal(loadAIConfig(storage).enabled, false);
  assert.throws(
    () => saveAIConfig({ enabled: true, apiKey: "key", model: "model", baseUrl: "" }, storage),
    /允许本地存储/,
  );
});
