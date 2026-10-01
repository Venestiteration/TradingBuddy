import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bindResearchBrief,
  renderResearchBrief,
  renderResearchEvents,
} from "../frontend/research-brief.js";

const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "'": "&#39;",
  '"': "&quot;",
}[character]));

const sampleEvent = (overrides = {}) => ({
  cluster_id: "1:10",
  title: "公司签署重大供货合同",
  summary: "公司披露已签署供货合同。",
  published_at: "2026-09-28T01:00:00+00:00",
  source_count: 2,
  content_status: "excerpt",
  conflict_status: "none",
  kinds: ["announcement", "news"],
  evidence: [{
    evidence_id: "e1",
    title: "交易所公告",
    published_at: "2026-09-28T01:00:00+00:00",
    content_status: "full",
    source_url: "https://example.test/e1",
  }],
  ...overrides,
});

const sampleBrief = (overrides = {}) => ({
  status: "ready",
  core_conclusion: "公司今日披露了新的合同事件。",
  known_facts: [{ claim: "已签署合同", evidence_ids: ["e1"] }],
  why_it_matters: [{ text: "可能影响未来订单转化", basis: "rule" }],
  impact_paths: [{ text: "订单→履约→收入确认", basis: "rule" }],
  unknowns: ["履约时间未确认"],
  watch_signals: [{ text: "后续履约公告", basis: "rule" }],
  coverage: { event_count: 1, source_count: 2 },
  events: [sampleEvent()],
  ...overrides,
});

test("daily report renders synthesis before the public-dynamics entry", () => {
  const html = renderResearchBrief(sampleBrief(), { escapeHtml, aiEnabled: true });
  assert.ok(html.indexOf("今天真正发生了什么") < html.indexOf("查看来源"));
  assert.match(html, /为什么重要/);
  assert.match(html, /影响路径/);
  assert.match(html, /还有什么不确定/);
  assert.match(html, /data-sheet="publicDynamics"/);
  assert.match(html, />展开 AI 解读</);
  assert.doesNotMatch(html, /data-research-cluster=/, "the landing report must not become the event feed");
});

test("daily report escapes API content and renders loading, empty, and deterministic-error states", () => {
  assert.match(renderResearchBrief(null, { escapeHtml, loading: true }), /正在整理最近 24 小时/);
  assert.match(renderResearchBrief(sampleBrief({ status: "empty", events: [], coverage: { event_count: 0, source_count: 0 } }), { escapeHtml }), /最近 24 小时暂无/);
  assert.match(renderResearchBrief(null, { escapeHtml, error: "<script>bad</script>" }), /日报暂时无法生成/);
  assert.doesNotMatch(renderResearchBrief(null, { escapeHtml, error: "<script>bad</script>" }), /<script>/);
});

test("duplicate source reports remain one expandable cluster", () => {
  const html = renderResearchEvents([sampleEvent({ source_count: 3 })], { escapeHtml });
  assert.equal((html.match(/data-research-cluster=/g) || []).length, 1);
  assert.match(html, /3 个来源/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /aria-controls="research-cluster-1-10"/);
  assert.match(html, /id="research-cluster-1-10-ai" hidden/);
});

test("only the selected cluster expands with readable source links and local drilldown", () => {
  const html = renderResearchEvents([
    sampleEvent(),
    sampleEvent({ cluster_id: "1:12", title: "第二件事", evidence: [] }),
  ], { escapeHtml, expandedClusterId: "1:10" });
  assert.equal((html.match(/aria-expanded="true"/g) || []).length, 1);
  assert.match(html, /href="https:\/\/example\.test\/e1"[^>]+rel="noreferrer"/);
  assert.match(html, /data-research-source="e1"/);
  assert.match(html, /id="research-cluster-1-10"/);
});

test("title-only, conflict, unavailable URL, and AI failure states remain explicit", () => {
  const html = renderResearchEvents([
    sampleEvent({
      content_status: "title_only",
      conflict_status: "possible",
      evidence: [{ evidence_id: "e2", title: "来源标题", source_url: "javascript:alert(1)" }],
    }),
  ], {
    escapeHtml,
    expandedClusterId: "1:10",
    aiErrorByCluster: { "1:10": "生成失败" },
  });
  assert.match(html, /仅标题/);
  assert.match(html, /来源存在差异/);
  assert.match(html, /来源地址暂不可用/);
  assert.match(html, /AI 解读暂时失败/);
  assert.match(html, /公司签署重大供货合同/);
  assert.doesNotMatch(html, /href="javascript:/);
});

test("binder delegates expand, source, and AI actions and cleanup removes the listener", () => {
  const listeners = new Map();
  const container = {
    addEventListener: (type, handler) => listeners.set(type, handler),
    removeEventListener: (type, handler) => {
      if (listeners.get(type) === handler) listeners.delete(type);
    },
  };
  const calls = [];
  const cleanup = bindResearchBrief(container, {
    onExpand: (clusterId, trigger) => calls.push(["expand", clusterId, trigger]),
    onSource: (sourceId, trigger) => calls.push(["source", sourceId, trigger]),
    onAI: (clusterId, trigger) => calls.push(["ai", clusterId, trigger]),
  });
  const target = (attributes) => {
    const element = {
      getAttribute: (name) => attributes[name] ?? null,
      closest: (selector) => {
        if (selector === "[data-research-expand]" && "data-research-expand" in attributes) return element;
        if (selector === "[data-research-source]" && "data-research-source" in attributes) return element;
        if (selector === "[data-research-ai]" && "data-research-ai" in attributes) return element;
        return null;
      },
    };
    return element;
  };

  const expand = target({ "data-research-expand": "1:10" });
  const source = target({ "data-research-source": "e1" });
  const ai = target({ "data-research-ai": "1:10" });
  listeners.get("click")({ target: expand });
  listeners.get("click")({ target: source });
  listeners.get("click")({ target: ai });

  assert.deepEqual(calls, [
    ["expand", "1:10", expand],
    ["source", "e1", source],
    ["ai", "1:10", ai],
  ]);
  cleanup();
  assert.equal(listeners.has("click"), false);
});
