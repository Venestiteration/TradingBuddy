# AI 投研助手桌面端 HTML 原型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可直接本地打开、以“动态”Chatbot 为主界面的 AI 投研助手桌面端交互原型。

**Architecture:** 使用单文件 HTML 承载语义结构、视觉样式、演示数据与交互逻辑，避免运行时依赖。所有标的数据通过只读 JavaScript 对象驱动；标的切换、快捷追问、展开分析和右侧详情面板共享同一状态控制器。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、内联 SVG 图标、Node.js 静态验收脚本。

## Global Constraints

- 一级入口固定命名为“动态”。
- 主页面必须是 Chatbot，不得改为卡片仪表盘或泛资讯流。
- 个性化内容仅来自用户主动添加的持仓和自选标的。
- 页面只有标的切换器、对话记录、输入框和按需右侧详情面板四类稳定对象。
- HTML 必须可以本地直接打开，不连接远程服务或真实行情。
- 不输出荐股、价格预测、仓位建议或明确交易指令。
- 使用系统字体、轻量半透明材质、即时按压反馈、对称面板路径和无障碍降级。
- 不添加装饰性图片、复杂卡片矩阵、独立资讯流、独立通知中心或独立事件详情页。

---

### Task 1: 建立可识别的对话工作区

**Files:**
- Create: `ai-investment-assistant-desktop.html`
- Create: `tests/prototype.test.mjs`

**Interfaces:**
- Produces: `#asset-switcher`、`#conversation`、`#composer`、`#detail-sheet` 四个稳定界面节点。
- Produces: Node 静态验收脚本，读取 `ai-investment-assistant-desktop.html` 并检查结构、文案与禁止项。

- [x] **Step 1: 写入失败的结构验收脚本**

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../ai-investment-assistant-desktop.html", import.meta.url), "utf8");
for (const id of ["asset-switcher", "conversation", "composer", "detail-sheet"]) {
  assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
}
assert.match(html, />动态</);
assert.match(html, /持仓/);
assert.match(html, /自选/);
assert.doesNotMatch(html, /待复核/);
console.log("prototype structure: ok");
```

- [x] **Step 2: 运行测试并确认因 HTML 尚不存在而失败**

Run: `node tests/prototype.test.mjs`

Expected: FAIL with `ENOENT` for `ai-investment-assistant-desktop.html`.

- [x] **Step 3: 创建最小语义 HTML 骨架**

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>动态 · AI 投研助手</title></head>
<body>
  <header><strong>动态</strong><button id="asset-switcher">腾讯控股 · 持仓</button></header>
  <main id="conversation" aria-live="polite"></main>
  <form id="composer"><textarea aria-label="继续追问"></textarea><button type="submit">发送</button></form>
  <aside id="detail-sheet" aria-hidden="true"></aside>
  <template id="asset-options"><span>腾讯控股 · 持仓</span><span>贵州茅台 · 自选</span></template>
</body>
</html>
```

- [x] **Step 4: 运行结构测试并确认通过**

Run: `node tests/prototype.test.mjs`

Expected: `prototype structure: ok` and exit code 0.

### Task 2: 完成 Apple 风格视觉系统

**Files:**
- Modify: `ai-investment-assistant-desktop.html`
- Modify: `tests/prototype.test.mjs`

**Interfaces:**
- Consumes: Task 1 的四个稳定界面节点。
- Produces: CSS 设计令牌、响应式桌面布局、按下反馈、半透明顶栏与输入区、右侧 Sheet 状态类 `.is-open`。

- [x] **Step 1: 增加视觉与无障碍静态断言**

```js
assert.match(html, /font-family:\s*-apple-system/);
assert.match(html, /backdrop-filter:\s*blur/);
assert.match(html, /prefers-reduced-motion:\s*reduce/);
assert.match(html, /prefers-reduced-transparency:\s*reduce/);
assert.match(html, /prefers-contrast:\s*more/);
assert.match(html, /:focus-visible/);
assert.match(html, /\.pressable:active/);
```

- [x] **Step 2: 运行测试并确认新增断言失败**

Run: `node tests/prototype.test.mjs`

Expected: FAIL on the first missing Apple-style CSS requirement.

- [x] **Step 3: 实现视觉令牌与交互动效**

```css
:root {
  color-scheme: light;
  --ink: #1d1d1f;
  --muted: #6e6e73;
  --blue: #0071e3;
  --surface: rgba(250,250,252,.78);
  --line: rgba(29,29,31,.10);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", system-ui, sans-serif;
}
.chrome { backdrop-filter: blur(24px) saturate(180%); background: var(--surface); }
.pressable:active { transform: scale(.97); transition: transform 100ms ease-out; }
.sheet { transform: translate3d(104%,0,0); transition: transform .38s cubic-bezier(.2,.8,.2,1); }
.sheet.is-open { transform: translate3d(0,0,0); }
:focus-visible { outline: 3px solid color-mix(in srgb,var(--blue) 42%,transparent); outline-offset: 3px; }
@media (prefers-reduced-motion: reduce) { *,*::before,*::after { scroll-behavior:auto!important; transition-duration:.01ms!important; animation-duration:.01ms!important; } }
@media (prefers-reduced-transparency: reduce) { .chrome { backdrop-filter:none; background:#fff; } }
@media (prefers-contrast: more) { :root { --line:#1d1d1f; } .chrome { background:#fff; } }
```

- [x] **Step 4: 运行视觉静态测试并确认通过**

Run: `node tests/prototype.test.mjs`

Expected: `prototype structure: ok` and exit code 0.

### Task 3: 实现标的驱动的对话交互

**Files:**
- Modify: `ai-investment-assistant-desktop.html`
- Modify: `tests/prototype.test.mjs`

**Interfaces:**
- Produces: `assets: Record<string, Asset>` 演示数据。
- Produces: `selectAsset(assetId: string): void`、`ask(prompt: string): void`、`toggleAnalysis(messageId: string): void`。
- Consumes: `#asset-switcher`、`#conversation`、`#composer`。

- [x] **Step 1: 增加内容和交互接口断言**

```js
for (const symbol of ["TCEHY", "600519"]) assert.match(html, new RegExp(symbol));
for (const fn of ["selectAsset", "ask", "toggleAnalysis"]) assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`));
for (const label of ["已知事实", "当前推断", "尚不确定", "下一步可核验"]) assert.match(html, new RegExp(label));
assert.match(html, /我不能替你决定是否买入或卖出/);
```

- [x] **Step 2: 运行测试并确认新增断言失败**

Run: `node tests/prototype.test.mjs`

Expected: FAIL on missing fixture data or interaction function.

- [x] **Step 3: 实现两组标的数据与对话控制器**

```js
const assets = {
  TCEHY: { id: "TCEHY", name: "腾讯控股", kind: "持仓", impact: "值得留意", prompts: ["为什么重要？", "查看证据", "这会影响我原来的判断吗？"] },
  "600519": { id: "600519", name: "贵州茅台", kind: "自选", impact: "信息不足", prompts: ["为什么不能确认原因？", "查看相关信息", "后续需要观察什么？"] }
};
function selectAsset(assetId) { state.assetId = assetId; renderConversation(); }
function ask(prompt) { appendUserMessage(prompt); appendAssistantMessage(resolveAnswer(prompt)); }
function toggleAnalysis(messageId) { document.querySelector(`[data-analysis="${messageId}"]`)?.toggleAttribute("hidden"); }
```

- [x] **Step 4: 完成发送、快捷追问、展开分析和标的切换事件绑定**

```js
document.querySelector("#composer").addEventListener("submit", event => {
  event.preventDefault();
  const input = event.currentTarget.elements.prompt;
  if (input.value.trim()) ask(input.value.trim());
  input.value = "";
});
document.addEventListener("click", event => {
  const prompt = event.target.closest("[data-prompt]")?.dataset.prompt;
  if (prompt) ask(prompt);
});
```

- [x] **Step 5: 运行测试并确认通过**

Run: `node tests/prototype.test.mjs`

Expected: `prototype structure: ok` and exit code 0.

### Task 4: 实现统一详情面板与最终验收

**Files:**
- Modify: `ai-investment-assistant-desktop.html`
- Modify: `tests/prototype.test.mjs`

**Interfaces:**
- Produces: `openSheet(type: "evidence" | "thesis" | "impact" | "assets" | "settings"): void`。
- Produces: `closeSheet(): void`，关闭后将焦点返回触发控件。
- Consumes: `.sheet.is-open` 视觉状态和当前 `state.assetId`。

- [x] **Step 1: 增加面板、焦点和本地运行断言**

```js
for (const fn of ["openSheet", "closeSheet"]) assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`));
assert.match(html, /aria-modal="false"/);
assert.match(html, /lastTrigger\.focus\(\)/);
assert.match(html, /来源与证据/);
assert.match(html, /我的判断/);
assert.match(html, /管理标的/);
```

- [x] **Step 2: 运行测试并确认新增断言失败**

Run: `node tests/prototype.test.mjs`

Expected: FAIL on the first missing sheet behavior.

- [x] **Step 3: 实现统一详情面板**

```js
let lastTrigger = null;
function openSheet(type, trigger = document.activeElement) {
  lastTrigger = trigger;
  renderSheet(type);
  sheet.classList.add("is-open");
  sheet.setAttribute("aria-hidden", "false");
  sheet.querySelector("button")?.focus();
}
function closeSheet() {
  sheet.classList.remove("is-open");
  sheet.setAttribute("aria-hidden", "true");
  lastTrigger?.focus();
}
```

- [x] **Step 4: 检查内联脚本语法并运行全部静态验收**

Run: `node tests/prototype.test.mjs && node -e 'const h=require("fs").readFileSync("ai-investment-assistant-desktop.html","utf8"); const s=h.match(/<script>([\\s\\S]*?)<\\/script>/)[1]; new Function(s); console.log("inline script syntax: ok")'`

Expected: both `prototype structure: ok` and `inline script syntax: ok`, exit code 0.

- [x] **Step 5: 启动本地静态服务并确认页面可访问**

Run: `python3 -m http.server 4173`

In a second shell run: `curl -I http://127.0.0.1:4173/ai-investment-assistant-desktop.html`

Expected: HTTP status `200 OK`.

- [x] **Step 6: 对照规格逐项检查最终文件**

Run: `rg -n "动态|持仓|自选|已知事实|当前推断|尚不确定|下一步可核验|信息不足|可能影响原判断|来源与证据|我的判断|管理标的|prefers-reduced-motion" ai-investment-assistant-desktop.html`

Expected: every required phrase appears; `rg -n "待复核|推荐买入|推荐卖出" ai-investment-assistant-desktop.html` returns no matches.
