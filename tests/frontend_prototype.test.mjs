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
  assert.ok(app.includes("saveAnalysis(assetId"));
  assert.ok(app.includes("saveConversationTurn(assetId"));
  assert.ok(app.includes("recent_messages"));
  assert.ok(aiLocal.includes("AI_WORKSPACE_KEY"));
});

test("visitor AI settings preserve the current interaction style", () => {
  assert.ok(index.includes("<span>TradingBuddy</span>"));
  assert.ok(index.includes('id="composer-dock"'));
  assert.ok(index.includes('data-tour="settings"'));
  assert.match(index, /app\.js\?v=20260920-visitor-ai-guard/);
  assert.match(app, /from "\.\/api\.js\?v=20260920-visitor-ai-guard"/);
  assert.match(app, /from "\.\/ai-local\.js\?v=20260920-visitor-ai-guard"/);
  assert.match(app, /服务器无法直连 OpenAI 官方/);
  assert.ok(app.includes('id="ai-settings-form"'));
  assert.ok(app.includes('data-api-url-preset'));
  assert.ok(app.includes('data-api-url-custom'));
  assert.ok(aiLocal.includes("deepseek"));
  assert.ok(aiLocal.includes("siliconflow"));
  assert.ok(app.includes('role="switch"'));
  assert.ok(app.includes("清除本地 AI 配置"));
  assert.ok(app.includes("配置和分析结果仅保存在当前浏览器"));
  assert.ok(app.includes("function syncAIMode"));
  assert.ok(styles.includes(".ai-settings"));
  assert.ok(styles.includes(".composer-dock[hidden]"));
  assert.doesNotMatch(styles, /\.brand span:last-child\s*\{\s*display:\s*none/);
});

test("onboarding explains source mode and the first AI enablement", () => {
  assert.ok(app.includes("sourceTourSteps"));
  assert.ok(app.includes("aiTourSteps"));
  assert.ok(app.includes("SOURCE_TOUR_KEY"));
  assert.ok(app.includes("AI_TOUR_KEY"));
  assert.ok(app.includes("打开 AI 设置"));
  assert.ok(app.includes('startTour("ai"'));
  assert.doesNotMatch(app, /tradingbuddy-tour-complete-v1/);
  assert.match(app, /requestAnimationFrame\(\(\) => setTimeout\(\(\) => startTour\(\), 260\)/);
  assert.doesNotMatch(app, /requestAnimationFrame\(\(\) => setTimeout\(\(\) => startTour\(false\), 260\)/);
});

test("AI-off importance details cannot expose thesis-draft actions", () => {
  assert.match(importanceDetail, /aiEnabled/);
  assert.match(app, /dailyImportanceSheet\(body, \{ sheetHeader, escapeHtml, aiEnabled \}\)/);
  assert.match(app, /function addImportanceDayToThesis\(date, trigger\) \{[\s\S]*if \(!aiEnabled\(\)\)/);
});

test("AI-off archive keeps the manual thesis path while defaulting to data", () => {
  assert.match(app, /const tabs = aiEnabled\(\) \? \["thesis", "data", "inferences", "sources"\] : \["thesis", "data", "sources"\]/);
  assert.match(app, /function archiveSheet\(tab = null\)/);
  assert.match(app, /if \(view\.type === "archive"\) els\.sheet\.innerHTML = archiveSheet\(view\.tab\)/);
});

test("settings sheet rerenders restore focus to the triggering control", () => {
  assert.match(app, /function captureSheetFocus/);
  assert.match(app, /function restoreSheetFocus/);
  assert.match(app, /turnOffAI\(aiToggle\)/);
  assert.match(app, /clearAISettings\(clearAIButton\)/);
  assert.match(app, /restoreSheetFocus\(focusTarget\)/);
});

test("AI SSE failures do not announce a successful response", () => {
  assert.match(app, /if \(completed\) \{\s*applyIfCurrentView\(state, view, \(\) => \{\s*loadLocalAIState\(\);/);
  assert.match(app, /if \(completedResult\) \{\s*applyIfCurrentView\(state, view, \(\) => \{\s*loadLocalAIState\(\);/);
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
  assert.match(selectBlock, /transitionAssetView\(state, id,[\s\S]*loadLocalAIState/);

  const draftStart = app.indexOf("async function generateThesisDraft");
  const draftEnd = app.indexOf("\nfunction ", draftStart + 1);
  const draftBlock = app.slice(draftStart, draftEnd);
  assert.ok(draftBlock.includes("state.abortController.signal, aiHeaders(state.aiConfig)"));
});

test("runtime asset switches invalidate out-of-order views and load the selected workspace", async () => {
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  const previousLocalStorage = globalThis.localStorage;
  const previousHTMLElement = globalThis.HTMLElement;
  const previousWindow = globalThis.window;
  const previousRequestAnimationFrame = globalThis.requestAnimationFrame;

  class FakeElement {
    constructor() {
      this.dataset = {};
      this.classList = { add() {}, remove() {}, toggle() {} };
      this.style = { setProperty() {} };
      this.listeners = new Map();
      this.isConnected = true;
      this.hidden = false;
      this.innerHTML = "";
    }

    addEventListener(type, handler) { this.listeners.set(type, handler); }
    setAttribute() {}
    querySelector() { return null; }
    querySelectorAll() { return []; }
    scrollTo() {}
    focus() {}
    closest() { return null; }
    getBoundingClientRect() { return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 }; }
  }

  class TestStorage {
    constructor() { this.values = new Map(); }
    getItem(key) { return this.values.get(key) ?? null; }
    setItem(key, value) { this.values.set(key, String(value)); }
    removeItem(key) { this.values.delete(key); }
  }

  const selectors = [
    ".app-shell", "#conversation", ".conversation-scroll", "#asset-switcher", "#asset-switcher-label",
    "#asset-popover", "#composer-dock", "#composer", "#composer textarea", "#composer .send-button", "#detail-sheet", "#toast",
    "#tour-layer", "#tour-popover", "#tour-focus-ring", "#tour-blocker", ".tour-mask-top", ".tour-mask-left",
    ".tour-mask-right", ".tour-mask-bottom",
  ];
  const elements = new Map(selectors.map((selector) => [selector, new FakeElement()]));
  const documentStub = {
    body: { dataset: { apiRoot: "/api" } },
    activeElement: null,
    querySelector: (selector) => elements.get(selector) || null,
    addEventListener() {},
  };
  const storage = new TestStorage();
  storage.setItem("tradingbuddy.tour.sources.v2", "true");
  storage.setItem("tradingbuddy.tour.ai.v1", "true");
  storage.setItem("tradingbuddy.ai.config.v1", JSON.stringify({ enabled: true, apiKey: "test-key", model: "test-model", baseUrl: "" }));
  storage.setItem("tradingbuddy.ai.workspace.v1", JSON.stringify({ assets: {
    1: { messages: [{ role: "assistant", content: "old-a" }], analyses: [] },
    2: { messages: [{ role: "assistant", content: "new-b" }], analyses: [] },
  } }));

  const overviewRequests = [];
  let assetsRequested = false;
  const response = (body) => ({ ok: true, status: 200, text: async () => JSON.stringify(body) });
  const fetchStub = async (url) => {
    if (url.endsWith("/assets")) {
      assetsRequested = true;
      return response({ assets: [
        { id: 1, stock_name: "A", stock_code: "000001", asset_type: "watchlist" },
        { id: 2, stock_name: "B", stock_code: "000002", asset_type: "watchlist" },
      ] });
    }
    const match = url.match(/\/assets\/(\d+)\/overview$/);
    if (match) {
      const request = {};
      const promise = new Promise((resolve) => { request.resolve = resolve; });
      overviewRequests.push({ assetId: Number(match[1]), resolve: request.resolve });
      return promise;
    }
    if (/\/assets\/\d+\/theses$/.test(url)) return response({ history: [] });
    if (/\/assets\/\d+\/importance\?days=/.test(url)) return response({ rows: [] });
    throw new Error(`unexpected request: ${url}`);
  };

  const waitFor = async (predicate) => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (predicate()) return;
      await new Promise((resolve) => setImmediate(resolve));
    }
    assert.fail("timed out waiting for runtime app request");
  };

  globalThis.document = documentStub;
  globalThis.fetch = fetchStub;
  globalThis.localStorage = storage;
  globalThis.HTMLElement = FakeElement;
  globalThis.window = { innerWidth: 1280, innerHeight: 800, addEventListener() {} };
  globalThis.requestAnimationFrame = (callback) => callback();

  try {
    const { selectAsset } = await import(`../frontend/app.js?runtime=${Date.now()}`);
    await waitFor(() => assetsRequested && overviewRequests.length === 1);

    selectAsset(2);
    await waitFor(() => overviewRequests.length === 2);

    selectAsset(1);
    await waitFor(() => overviewRequests.length === 3);

    overviewRequests[0].resolve(response({ asset: { stock_name: "stale A" }, events: [] }));
    overviewRequests[1].resolve(response({ asset: { stock_name: "stale B" }, events: [] }));
    await new Promise((resolve) => setImmediate(resolve));
    assert.doesNotMatch(elements.get("#conversation").innerHTML, /stale A|stale B/);

    overviewRequests[2].resolve(response({ asset: { stock_name: "current A", stock_code: "000001" }, events: [] }));
    await waitFor(() => elements.get("#conversation").innerHTML.includes("current A"));
    assert.match(elements.get("#conversation").innerHTML, /old-a/);
    assert.doesNotMatch(elements.get("#conversation").innerHTML, /stale A|stale B/);
  } finally {
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
    if (previousLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previousLocalStorage;
    if (previousHTMLElement === undefined) delete globalThis.HTMLElement;
    else globalThis.HTMLElement = previousHTMLElement;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousRequestAnimationFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousRequestAnimationFrame;
  }
});

test("keyboard final source-tour actions open settings and restore focus to the highlighted control", async () => {
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  const previousLocalStorage = globalThis.localStorage;
  const previousHTMLElement = globalThis.HTMLElement;
  const previousWindow = globalThis.window;
  const previousRequestAnimationFrame = globalThis.requestAnimationFrame;

  class FakeElement {
    constructor(name) {
      this.name = name;
      this.dataset = {};
      this.classList = {
        values: new Set(),
        add: (...names) => names.forEach((value) => this.classList.values.add(value)),
        remove: (...names) => names.forEach((value) => this.classList.values.delete(value)),
        toggle: (name, force) => {
          const next = force === undefined ? !this.classList.values.has(name) : force;
          if (next) this.classList.values.add(name);
          else this.classList.values.delete(name);
          return next;
        },
        contains: (name) => this.classList.values.has(name),
      };
      this.style = { setProperty() {} };
      this.isConnected = true;
      this.hidden = false;
      this.innerHTML = "";
      this.scrollIntoViewCalls = [];
    }

    addEventListener() {}
    setAttribute() {}
    querySelector(selector) {
      if (this.name === "tour-popover" && selector === "[data-tour-next]") return elements.get("tour-next");
      if (this.name === "tour-popover" && selector === "[data-tour-skip]") return elements.get("tour-skip");
      if (this.name === "sheet" && selector === "#sheet-title") return elements.get("sheet-title");
      if (this.name === "sheet" && selector === "#ai-settings") return elements.get("ai-settings");
      return null;
    }
    querySelectorAll(selector) {
      if (this.name === "tour-popover" && selector === "button:not([disabled])") {
        return [elements.get("tour-skip"), elements.get("tour-next")];
      }
      return [];
    }
    scrollTo() {}
    focus() { documentStub.activeElement = this; }
    closest() { return null; }
    getBoundingClientRect() { return { left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40 }; }
    scrollIntoView(options) { this.scrollIntoViewCalls.push(options); }
  }

  class TestStorage {
    constructor() { this.values = new Map([["tradingbuddy.tour.sources.v2", "true"]]); }
    getItem(key) { return this.values.get(key) ?? null; }
    setItem(key, value) { this.values.set(key, String(value)); }
    removeItem(key) { this.values.delete(key); }
  }

  const elements = new Map();
  const addElement = (name, ...selectors) => {
    const element = new FakeElement(name);
    elements.set(name, element);
    selectors.forEach((selector) => elements.set(selector, element));
    return element;
  };
  addElement("app-shell", ".app-shell");
  addElement("conversation", "#conversation");
  addElement("conversation-scroll", ".conversation-scroll");
  addElement("asset-switcher", "#asset-switcher", '[data-tour="asset"]');
  addElement("asset-switcher-label", "#asset-switcher-label");
  addElement("asset-popover", "#asset-popover");
  addElement("composer-dock", "#composer-dock");
  addElement("composer", "#composer", '[data-tour="composer"]');
  addElement("prompt-input", "#composer textarea");
  addElement("send-button", "#composer .send-button");
  const sheet = addElement("sheet", "#detail-sheet");
  addElement("toast", "#toast");
  addElement("tour-layer", "#tour-layer");
  addElement("tour-popover", "#tour-popover");
  addElement("tour-focus-ring", "#tour-focus-ring");
  addElement("tour-blocker", "#tour-blocker");
  addElement("start-tour", "[data-start-tour]");
  addElement("close-sheet", "[data-close-sheet]");
  addElement("tour-mask-top", ".tour-mask-top");
  addElement("tour-mask-left", ".tour-mask-left");
  addElement("tour-mask-right", ".tour-mask-right");
  addElement("tour-mask-bottom", ".tour-mask-bottom");
  addElement("dynamic", '[data-tour="dynamic"]');
  addElement("importance-timeline", ".importance-timeline");
  addElement("archive", '[data-tour="archive"]');
  const settingsButton = addElement("settings", '[data-tour="settings"]');
  addElement("ai-settings", "#ai-settings");
  addElement("sheet-title", "#sheet-title");
  addElement("tour-next", "[data-tour-next]");
  addElement("tour-skip");

  const listeners = new Map();
  const documentStub = {
    body: { dataset: { apiRoot: "/api" } },
    activeElement: null,
    querySelector: (selector) => elements.get(selector) || null,
    addEventListener: (type, handler) => listeners.set(type, handler),
  };
  const storage = new TestStorage();
  const response = (body) => ({ ok: true, status: 200, text: async () => JSON.stringify(body) });
  const dispatch = (type, event) => listeners.get(type)?.(event);
  const clickTarget = (matches) => ({ closest: (selector) => matches.has(selector) ? elements.get(selector) : null });
  const clickTourNext = () => dispatch("click", { target: clickTarget(new Set(["[data-tour-next]"])) });
  const nextTourStep = (key) => dispatch("keydown", {
    key,
    target: elements.get("tour-next"),
    preventDefault() {},
    shiftKey: false,
  });
  const startSourceTour = () => {
    documentStub.activeElement = settingsButton;
    dispatch("click", { target: clickTarget(new Set(["[data-start-tour]"])) });
    for (let index = 0; index < 4; index += 1) clickTourNext();
  };
  const assertSettingsOpen = () => {
    assert.equal(sheet.classList.contains("is-open"), true);
    assert.equal(sheet.innerHTML.includes('id="ai-settings"'), true);
    assert.equal(elements.get("app-shell").inert, false);
  };
  const closeSettings = () => {
    dispatch("click", { target: clickTarget(new Set(["[data-close-sheet]"])) });
    assert.equal(documentStub.activeElement, settingsButton);
  };

  globalThis.document = documentStub;
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/assets");
    return response({ assets: [] });
  };
  globalThis.localStorage = storage;
  globalThis.HTMLElement = FakeElement;
  globalThis.window = { innerWidth: 1280, innerHeight: 800, addEventListener() {} };
  globalThis.requestAnimationFrame = (callback) => callback();

  try {
    await import(`../frontend/app.js?keyboard-tour=${Date.now()}-${Math.random()}`);
    await new Promise((resolve) => setImmediate(resolve));

    startSourceTour();
    clickTourNext();
    assertSettingsOpen();
    assert.equal(elements.get("ai-settings").scrollIntoViewCalls.length, 1);
    closeSettings();

    startSourceTour();
    nextTourStep("ArrowRight");
    assertSettingsOpen();
    closeSettings();

    startSourceTour();
    nextTourStep("Enter");
    assertSettingsOpen();
    closeSettings();
  } finally {
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
    if (previousLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previousLocalStorage;
    if (previousHTMLElement === undefined) delete globalThis.HTMLElement;
    else globalThis.HTMLElement = previousHTMLElement;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousRequestAnimationFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousRequestAnimationFrame;
  }
});

test("AI tour scrolls the first analysis action into the visible workspace", async () => {
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  const previousLocalStorage = globalThis.localStorage;
  const previousHTMLElement = globalThis.HTMLElement;
  const previousWindow = globalThis.window;
  const previousRequestAnimationFrame = globalThis.requestAnimationFrame;

  class FakeElement {
    constructor(name, rect = { left: 100, top: 100, right: 180, bottom: 140, width: 80, height: 40 }) {
      this.name = name;
      this.rect = rect;
      this.dataset = {};
      this.classList = {
        values: new Set(),
        add: (...names) => names.forEach((value) => this.classList.values.add(value)),
        remove: (...names) => names.forEach((value) => this.classList.values.delete(value)),
        toggle: (name, force) => {
          const next = force === undefined ? !this.classList.values.has(name) : force;
          if (next) this.classList.values.add(name);
          else this.classList.values.delete(name);
          return next;
        },
      };
      this.style = { setProperty() {} };
      this.isConnected = true;
      this.hidden = false;
      this.innerHTML = "";
      this.scrollIntoViewCalls = [];
    }

    addEventListener() {}
    setAttribute() {}
    querySelector(selector) {
      if (this.name === "tour-popover" && selector === "[data-tour-next]") return elements.get("tour-next");
      return null;
    }
    querySelectorAll() { return []; }
    scrollTo() {}
    focus() { documentStub.activeElement = this; }
    closest() { return null; }
    getBoundingClientRect() { return this.rect; }
    scrollIntoView(options) { this.scrollIntoViewCalls.push(options); }
  }

  class TestStorage {
    constructor() {
      this.values = new Map([
        ["tradingbuddy.ai.config.v1", JSON.stringify({ enabled: true, apiKey: "test-key", model: "test-model", baseUrl: "" })],
        ["tradingbuddy.tour.sources.v2", "true"],
      ]);
    }

    getItem(key) { return this.values.get(key) ?? null; }
    setItem(key, value) { this.values.set(key, String(value)); }
    removeItem(key) { this.values.delete(key); }
  }

  const elements = new Map();
  const addElement = (name, ...selectors) => {
    const element = new FakeElement(name);
    elements.set(name, element);
    selectors.forEach((selector) => elements.set(selector, element));
    return element;
  };
  addElement("app-shell", ".app-shell");
  addElement("conversation", "#conversation");
  addElement("conversation-scroll", ".conversation-scroll");
  addElement("asset-switcher", "#asset-switcher", '[data-tour="asset"]');
  addElement("asset-switcher-label", "#asset-switcher-label");
  addElement("asset-popover", "#asset-popover");
  addElement("composer-dock", "#composer-dock");
  addElement("composer", "#composer", '[data-tour="composer"]');
  addElement("prompt-input", "#composer textarea");
  addElement("send-button", "#composer .send-button");
  addElement("sheet", "#detail-sheet");
  addElement("toast", "#toast");
  addElement("tour-layer", "#tour-layer");
  addElement("tour-popover", "#tour-popover");
  addElement("tour-focus-ring", "#tour-focus-ring");
  addElement("tour-blocker", "#tour-blocker");
  addElement("start-tour", "[data-start-tour]");
  addElement("tour-mask-top", ".tour-mask-top");
  addElement("tour-mask-left", ".tour-mask-left");
  addElement("tour-mask-right", ".tour-mask-right");
  addElement("tour-mask-bottom", ".tour-mask-bottom");
  const runAnalysis = addElement("run-analysis", '[data-action="run-analysis"]');
  runAnalysis.rect = { left: 100, top: 900, right: 220, bottom: 940, width: 120, height: 40 };
  addElement("tour-next", "[data-tour-next]");

  const listeners = new Map();
  const documentStub = {
    body: { dataset: { apiRoot: "/api" } },
    activeElement: null,
    querySelector: (selector) => elements.get(selector) || null,
    addEventListener: (type, handler) => listeners.set(type, handler),
  };
  const dispatch = (type, event) => listeners.get(type)?.(event);
  const clickTarget = (matches) => ({ closest: (selector) => matches.has(selector) ? elements.get(selector) : null });

  globalThis.document = documentStub;
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/assets");
    return { ok: true, status: 200, text: async () => JSON.stringify({ assets: [] }) };
  };
  globalThis.localStorage = new TestStorage();
  globalThis.HTMLElement = FakeElement;
  globalThis.window = { innerWidth: 390, innerHeight: 844, addEventListener() {} };
  globalThis.requestAnimationFrame = (callback) => callback();

  try {
    await import(`../frontend/app.js?ai-tour-scroll=${Date.now()}-${Math.random()}`);
    await new Promise((resolve) => setImmediate(resolve));
    dispatch("click", { target: clickTarget(new Set(["[data-start-tour]"])) });

    assert.equal(runAnalysis.scrollIntoViewCalls.length, 1);
    assert.equal(runAnalysis.scrollIntoViewCalls[0].block, "center");
    assert.equal(runAnalysis.scrollIntoViewCalls[0].behavior, "auto");
    assert.ok(Number.parseInt(elements.get("tour-popover").style.top, 10) <= 804);
  } finally {
    await new Promise((resolve) => setTimeout(resolve, 300));
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
    if (previousLocalStorage === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previousLocalStorage;
    if (previousHTMLElement === undefined) delete globalThis.HTMLElement;
    else globalThis.HTMLElement = previousHTMLElement;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousRequestAnimationFrame === undefined) delete globalThis.requestAnimationFrame;
    else globalThis.requestAnimationFrame = previousRequestAnimationFrame;
  }
});

test("AI and overview work use the view generation guard", () => {
  assert.ok(app.includes("viewGeneration"));
  assert.ok(app.includes("applyIfCurrentView"));
  assert.ok(app.includes("transitionAssetView"));
  assert.ok(app.includes("runCurrentViewRefresh"));
});
