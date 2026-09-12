# AI 投研助手研究档案与溯源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有单文件桌面原型中，将“我的判断”升级为“研究档案”，并为结构化数值和非结构化结论提供完整、可交互的溯源路径。

**Architecture:** 保留当前单个 HTML 和唯一右侧 Sheet。以扩展后的本地 `assets` 数据模型驱动研究档案四个视图；通过 `data-metric` 和 `data-trace` 两类入口分别打开行情图表与推断链，并在 Sheet 内通过分段控件和历史栈完成站内跳转。

**Tech Stack:** HTML5、CSS、原生 JavaScript、内嵌 SVG；无远程依赖、无构建步骤。

## Global Constraints

- 修改文件仅为 `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`。
- 模拟数据以交互完整性为目标，不声明真实或实时准确性。
- 顶部入口统一命名为“研究档案”，内部保留“我的判断”。
- 结构化数据点击后必须打开多周期 K 线详情。
- 结论“详情”必须打开事实、信号、推断、结论、不确定性与待验证条件。
- 所有引用必须区分站内结构化数据与站外来源。
- 原型继续支持键盘焦点、减少动态效果、减少透明度和增强对比度。
- 当前目录不是 Git 仓库，不执行提交步骤。

---

### Task 1: 扩展研究档案数据模型

**Files:**
- Modify: `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: 现有 `assets` 对象及 `state.assetId`。
- Produces: 每个资产的 `metrics`、`marketSeries`、`events`、`reasoning` 和带 `url/type/status` 的 `sources`。

- [ ] **Step 1: 增加确定性行情生成函数**

在 `assets` 前定义 `buildMarketSeries(seed, basePrice, count = 72)`，返回：

```js
Array<{ date: string, open: number, high: number, low: number, close: number, volume: number }>
```

函数使用本地确定性正弦与余弦序列生成 OHLCV，保证刷新后图表一致。

- [ ] **Step 2: 扩展两个资产的数据**

每个资产加入以下字段：

```js
metrics: {
  price: { label, value, delta, unit, sourceId },
  change: { label, value, delta, unit, sourceId },
  volume: { label, value, delta, unit, sourceId },
  turnover: { label, value, delta, unit, sourceId },
  valuation: { label, value, delta, unit, sourceId }
},
marketSeries: buildMarketSeries(...),
events: [{ index, title, tone, sourceId }],
reasoning: {
  conclusion: { title, summary, confidence },
  nodes: [{ id, kind, title, detail, citations: [{ type, target, label }] }]
}
```

- [ ] **Step 3: 验证数据模型**

运行：

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html','utf8');const js=s.match(/<script>([\\s\\S]*)<\\/script>/)[1];new Function(js);console.log('JS syntax OK')"
```

预期输出：`JS syntax OK`。

### Task 2: 构建研究档案与多维 K 线

**Files:**
- Modify: `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: `assets[state.assetId].metrics/marketSeries/events`。
- Produces: `researchArchiveSheet(asset, tab)`、`marketSheet(asset, metricKey, period)`、`renderCandlestickChart(asset, period)`。

- [ ] **Step 1: 添加研究档案视觉组件**

新增 `.archive-tabs`、`.metric-grid`、`.metric-card`、`.chart-shell`、`.chart-toolbar`、`.chart-legend`、`.chart-svg`、`.source-chip` 等样式；交互控件最小高度 36px，数字使用 `font-variant-numeric: tabular-nums`。

- [ ] **Step 2: 添加日/周/月数据聚合与 SVG 绘制**

实现：

```js
aggregateSeries(series, period) // period: "day" | "week" | "month"
renderCandlestickChart(asset, period)
```

SVG 同时绘制网格、蜡烛、成交量、收盘均线、最高/最低标签和事件标记；数据不足时返回明确空状态。

- [ ] **Step 3: 添加研究档案分段视图**

实现 `researchArchiveSheet(asset, tab = "thesis")`，分段为“判断 / 数据 / 推断 / 来源”。顶部入口默认进入“判断”，数据入口直接进入详细图表。

- [ ] **Step 4: 验证 HTML 和脚本语法**

运行 Task 1 的 `node -e` 语法检查，预期输出 `JS syntax OK`。

### Task 3: 构建推断链与双向站内溯源

**Files:**
- Modify: `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: `assets[state.assetId].reasoning`、`sources`、`metrics`。
- Produces: `reasoningSheet(asset)`、`sourceRecordMarkup(asset)`、Sheet 内导航历史 `state.sheetHistory`。

- [ ] **Step 1: 添加推断链组件**

新增 `.reasoning-chain`、`.reasoning-node`、`.reasoning-rail`、`.confidence-meter`、`.citation-button` 和 `.uncertainty-callout`。节点按事实、信号、推断、结论、未知、验证条件分层展示。

- [ ] **Step 2: 添加引用路由**

点击：

```html
<button data-metric="price">HK$ 625.50</button>
<button data-trace="primary">详情</button>
<button data-citation-type="metric" data-citation-target="volume">成交量</button>
<a href="https://example.com/..." target="_blank" rel="noopener noreferrer">查看站外原文</a>
```

站内引用切换到相应图表并记录上一层；面板返回按钮恢复推断链位置。

- [ ] **Step 3: 升级来源记录**

来源列表显示来源层级、发布时间、引用片段、关联结论和可用状态；不可用站外原文使用禁用按钮与明确说明。

- [ ] **Step 4: 验证闭环**

在浏览器逐项验证：结论详情 → 推断节点 → 成交量图表 → 返回推断链；价格 → K 线 → 来源记录 → 站外来源。

### Task 4: 接入现有对话并完成可访问性验证

**Files:**
- Modify: `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: 现有 `initialMessage`、`analysisMarkup`、`renderConversation`、事件委托。
- Produces: 完整可操作的单文件原型。

- [ ] **Step 1: 更新文案与入口**

顶栏 `aria-label/title`、导览第五步、相关回答和面板标题统一使用“研究档案”；内部编辑模块仍使用“我的判断”。

- [ ] **Step 2: 将数值和结论接入新路由**

首屏价格、涨跌幅和分析中的结构化指标改为 `data-metric` 按钮；核心结论和回答结论旁增加 `data-trace` 的“详情”。

- [ ] **Step 3: 完善焦点与动效**

Sheet 内容切换后将焦点移动至视图标题；关闭后返回原触发控件。保留现有 reduced-motion/transparency/contrast 媒体查询，并为新增组件增加对应降级。

- [ ] **Step 4: 自动与人工验收**

执行脚本语法检查；本地打开 HTML 后验证两个标的、三个周期、四个研究档案分段、所有站内引用、关闭返回、Esc 和窄屏布局。浏览器控制台预期无异常。

### Task 5: 完整演示 AI 推送与流式回复

**Files:**
- Modify: `/Users/venest/秋招/腾讯/ai实战/ai-investment-assistant-desktop.html`

**Interfaces:**
- Consumes: `assets[state.assetId].pushes`、现有消息数组、`resolveAnswer(prompt)`。
- Produces: `triggerPush(assetId, manual)`、`startStreamingAnswer(answer)`、`stopStreamingAnswer()`。

- [ ] **Step 1: 增加丰富动态数据**

每个标的加入至少 6 条 `pushes`，覆盖 `earnings`、`market`、`valuation`、`management`、`industry`、`uncertain`。每条动态包含 `id/title/summary/time/reason/priority/metricKey/traceId/prompts`。

- [ ] **Step 2: 增加自动和手动推送入口**

首屏显示“AI 动态”状态与“模拟新动态”按钮；页面加载后以短延时模拟一次自动推送，手动按钮从未展示数据中循环加入新消息。推送显示未读蓝点、推送原因、时间和溯源操作。

- [ ] **Step 3: 增加完整回复状态**

提交问题后先显示 `正在理解问题`，再显示 `正在检索研究档案`，最后逐段写入回答。生成过程中发送按钮变为停止按钮；停止后保留已生成内容并标记“已停止生成”。

- [ ] **Step 4: 验证推送与回答**

在浏览器中验证自动推送、连续三次手动推送、快捷问题、自由问题、停止生成、切换标的后独立消息历史，以及回答中的指标和结论溯源。
