# AI 投研助手产品导览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有桌面端 HTML 原型中增加首次自动出现、可跳过、可重启的五步 Spotlight 产品导览。

**Architecture:** 继续保持单文件 HTML 原型。导览由 `tourSteps` 数据定义、四块遮罩和一个定位气泡组成；控制器负责目标测量、步骤切换、会话状态、键盘行为与焦点恢复。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、`sessionStorage`、Node.js 静态验收脚本。

## Global Constraints

- 保留现有标的切换、对话、详情面板和判断编辑功能。
- 导览固定为 5 步：选择标的、查看动态、继续理解、自由追问、维护判断。
- 每一步只高亮一个真实界面目标，底层操作不可误触。
- 气泡必须包含步骤数、标题、说明、跳过、上一步和下一步；最后一步使用“开始使用”。
- 首次进入自动出现，完成或跳过后当前会话不再自动出现。
- 顶栏提供“使用指引”入口，可重新启动。
- 支持 Esc、左右方向键、焦点进入与返回。
- 支持减少动态效果与减少透明度偏好。

---

### Task 1: 建立导览结构、样式和步骤数据

**Files:**
- Modify: `tests/prototype.test.mjs`
- Modify: `ai-investment-assistant-desktop.html`

**Interfaces:**
- Produces: `[data-tour]` 目标标记。
- Produces: `#tour-layer`、四个 `.tour-mask`、`#tour-focus-ring`、`#tour-blocker`、`#tour-popover`。
- Produces: `tourSteps: Array<{ target: string, title: string, body: string }>`。

- [x] **Step 1: 增加失败的静态验收断言**

```js
for (const target of ["asset", "dynamic", "actions", "composer", "thesis"]) {
  assert.match(html, new RegExp(`data-tour=["']${target}["']`));
}
for (const id of ["tour-layer", "tour-focus-ring", "tour-blocker", "tour-popover"]) {
  assert.match(html, new RegExp(`id=["']${id}["']`));
}
for (const title of ["选择标的", "查看动态", "继续理解", "自由追问", "维护判断"]) {
  assert.match(html, new RegExp(title));
}
assert.match(html, /aria-modal="true"/);
assert.match(html, /使用指引/);
```

- [x] **Step 2: 运行测试并确认缺少导览目标**

Run: `node tests/prototype.test.mjs`

Expected: FAIL on missing `data-tour="asset"`.

- [x] **Step 3: 添加目标标记、帮助按钮和导览层**

```html
<button id="asset-switcher" data-tour="asset">…</button>
<section data-tour="dynamic">…</section>
<div data-tour="actions">…</div>
<form id="composer" data-tour="composer">…</form>
<button data-sheet="thesis" data-tour="thesis" aria-label="我的判断">…</button>
<button aria-label="使用指引" data-start-tour>…</button>
<div id="tour-layer" hidden>
  <div class="tour-mask tour-mask-top"></div>
  <div class="tour-mask tour-mask-left"></div>
  <div class="tour-mask tour-mask-right"></div>
  <div class="tour-mask tour-mask-bottom"></div>
  <div id="tour-focus-ring"></div>
  <div id="tour-blocker"></div>
  <section id="tour-popover" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body"></section>
</div>
```

- [x] **Step 4: 添加定位视觉样式和无障碍降级**

```css
.tour-layer { position: fixed; inset: 0; z-index: 100; }
.tour-mask { position: fixed; background: rgba(0,0,0,.58); }
.tour-focus-ring { position: fixed; border: 2px solid rgba(255,255,255,.92); border-radius: 16px; box-shadow: 0 0 0 5px rgba(255,255,255,.16); pointer-events: none; }
.tour-blocker { position: fixed; background: transparent; }
.tour-popover { position: fixed; width: min(320px,calc(100vw - 32px)); padding: 18px; border-radius: 18px; background: rgba(255,255,255,.96); backdrop-filter: blur(24px) saturate(160%); }
@media (prefers-reduced-motion: reduce) { .tour-popover,.tour-focus-ring,.tour-mask { transition-property: opacity; transform: none; } }
@media (prefers-reduced-transparency: reduce) { .tour-popover { background:#fff; backdrop-filter:none; } }
```

- [x] **Step 5: 定义五步数据**

```js
const tourSteps = [
  { target: '[data-tour="asset"]', title: "选择标的", body: "这里只显示你的持仓和自选。点击可切换当前研究标的。" },
  { target: '[data-tour="dynamic"]', title: "查看动态", body: "先看今天最重要的变化，以及它是否影响你原来的判断。" },
  { target: '[data-tour="actions"]', title: "继续理解", body: "点击快捷问题继续追问；展开分析可区分事实、推断和未知。" },
  { target: '[data-tour="composer"]', title: "自由追问", body: "有其他问题，直接在这里输入。回答会继承当前标的和证据。" },
  { target: '[data-tour="thesis"]', title: "维护判断", body: "在这里记录你的投资判断。新证据只会提醒，不会自动修改。" }
];
```

- [x] **Step 6: 运行静态测试并确认通过**

Run: `node tests/prototype.test.mjs`

Expected: `prototype structure: ok` and exit code 0.

### Task 2: 实现步骤控制、自动触发与键盘操作

**Files:**
- Modify: `tests/prototype.test.mjs`
- Modify: `ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: `tourSteps`、导览 DOM 节点与 `[data-tour]` 目标。
- Produces: `startTour(force?: boolean): void`、`showTourStep(index: number): void`、`positionTour(): void`、`finishTour(completed?: boolean): void`。

- [x] **Step 1: 增加控制器和行为静态断言**

```js
for (const fn of ["startTour", "showTourStep", "positionTour", "finishTour"]) {
  assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`));
}
assert.match(html, /sessionStorage/);
assert.match(html, /event\.key === "ArrowRight"/);
assert.match(html, /event\.key === "ArrowLeft"/);
assert.match(html, /event\.key === "Escape"/);
assert.match(html, /开始使用/);
assert.match(html, /跳过/);
```

- [x] **Step 2: 运行测试并确认缺少 `startTour()`**

Run: `node tests/prototype.test.mjs`

Expected: FAIL on missing `startTour()`.

- [x] **Step 3: 实现会话状态与步骤控制器**

```js
let tourIndex = 0;
let tourActive = false;
let tourReturnFocus = null;
const tourStorageKey = "ai-invest-tour-complete-v1";
function getTourComplete() { try { return sessionStorage.getItem(tourStorageKey) === "1"; } catch { return false; } }
function setTourComplete() { try { sessionStorage.setItem(tourStorageKey, "1"); } catch {} }
function startTour(force = false) {
  if (!force && getTourComplete()) return;
  tourReturnFocus = document.activeElement;
  tourActive = true;
  tourIndex = 0;
  tourLayer.hidden = false;
  showTourStep(0);
}
function showTourStep(index) {
  tourIndex = Math.max(0, Math.min(index, tourSteps.length - 1));
  renderTourPopover();
  positionTour();
  tourPopover.querySelector("[data-tour-next]")?.focus();
}
function finishTour(completed = true) {
  tourActive = false;
  tourLayer.hidden = true;
  if (completed) setTourComplete();
  if (tourReturnFocus?.isConnected) tourReturnFocus.focus();
}
```

- [x] **Step 4: 实现四块遮罩、焦点环和气泡自动定位**

```js
function positionTour() {
  if (!tourActive) return;
  const target = document.querySelector(tourSteps[tourIndex].target);
  const rect = target.getBoundingClientRect();
  const gap = 9;
  const hole = { left: Math.max(8,rect.left-gap), top: Math.max(8,rect.top-gap), right: Math.min(innerWidth-8,rect.right+gap), bottom: Math.min(innerHeight-8,rect.bottom+gap) };
  positionMasks(hole);
  positionFocusRing(hole);
  positionBlocker(hole);
  positionPopover(hole);
}
```

- [x] **Step 5: 绑定按钮、首次启动、窗口变化与键盘事件**

```js
document.addEventListener("click", event => {
  if (event.target.closest("[data-start-tour]")) startTour(true);
  if (event.target.closest("[data-tour-skip]")) finishTour(true);
  if (event.target.closest("[data-tour-prev]")) showTourStep(tourIndex - 1);
  if (event.target.closest("[data-tour-next]")) tourIndex === tourSteps.length - 1 ? finishTour(true) : showTourStep(tourIndex + 1);
});
window.addEventListener("resize", () => requestAnimationFrame(positionTour));
document.addEventListener("keydown", event => {
  if (!tourActive) return;
  if (event.key === "Escape") finishTour(true);
  if (event.key === "ArrowRight") tourIndex === tourSteps.length - 1 ? finishTour(true) : showTourStep(tourIndex + 1);
  if (event.key === "ArrowLeft") showTourStep(tourIndex - 1);
});
requestAnimationFrame(() => startTour(false));
```

- [x] **Step 6: 运行完整静态测试与脚本语法验证**

Run: `node tests/prototype.test.mjs && node -e 'const h=require("fs").readFileSync("ai-investment-assistant-desktop.html","utf8"); const s=h.match(/<script>([\\s\\S]*?)<\\/script>/)[1]; new Function(s); console.log("inline script syntax: ok")'`

Expected: `prototype structure: ok` and `inline script syntax: ok`, exit code 0.

- [x] **Step 7: 验证本地文件可访问且原功能标记仍存在**

Run: `python3 -m http.server 4173` and `curl --fail http://127.0.0.1:4173/ai-investment-assistant-desktop.html`

Expected: HTTP 200; `node tests/prototype.test.mjs` remains passing.
