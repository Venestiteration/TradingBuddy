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
