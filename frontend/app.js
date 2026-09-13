import { API_ROOT, api } from "./api.js";
import { bindImportanceChart, renderImportanceChart } from "./importance-chart.js";
import { categoryImportanceSheet, dailyImportanceSheet } from "./importance-detail.js";

const $ = (selector) => document.querySelector(selector);

const state = {
  assets: [],
  assetId: null,
  overview: null,
  selectedEventId: null,
  analysis: null,
  pending: null,
  busy: false,
  abortController: null,
  popoverOpen: false,
  sheetView: null,
  sheetHistory: [],
  sheetData: null,
  archiveTab: "thesis",
  chartPeriod: "day",
  importanceRows: [],
  importanceDays: 30,
  importanceError: "",
  readEvents: new Set(),
  tourIndex: 0,
  tourActive: false,
  tourReturnFocus: null,
  tourCloseTimer: null,
  toastTimer: null,
};

const els = {
  appShell: $(".app-shell"),
  conversation: $("#conversation"),
  conversationScroll: $(".conversation-scroll"),
  assetSwitcher: $("#asset-switcher"),
  assetSwitcherLabel: $("#asset-switcher-label"),
  assetPopover: $("#asset-popover"),
  composer: $("#composer"),
  promptInput: $("#composer textarea"),
  sendButton: $("#composer .send-button"),
  sheet: $("#detail-sheet"),
  toast: $("#toast"),
  tourLayer: $("#tour-layer"),
  tourPopover: $("#tour-popover"),
  tourFocusRing: $("#tour-focus-ring"),
  tourBlocker: $("#tour-blocker"),
  tourMasks: {
    top: $(".tour-mask-top"),
    left: $(".tour-mask-left"),
    right: $(".tour-mask-right"),
    bottom: $(".tour-mask-bottom"),
  },
};

const tourSteps = [
  { target: '[data-tour="asset"]', title: "选择标的", body: "这里只显示你的持仓和自选。点击可切换当前研究标的。" },
  { target: '[data-tour="dynamic"]', title: "查看动态", body: "先看当前最重要的变化，以及它是否影响你原来的判断。" },
  { target: '[data-tour="actions"]', title: "继续理解", body: "点击快捷问题继续追问；展开分析可区分事实、推断和未知。" },
  { target: '[data-tour="composer"]', title: "自由追问", body: "有其他问题，直接在这里输入。回答会继承当前标的和证据。" },
  { target: '[data-tour="archive"]', title: "研究档案", body: "在这里核验判断、数据、推断与来源。页面里的数值和结论也能直接定位到对应依据。" },
];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  }[character]));
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function formatDate(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "时间未知";
}

function formatCompactVolume(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(0)}万`;
  return String(Math.round(number));
}

function selectedAsset() {
  return state.assets.find((asset) => asset.id === state.assetId) || null;
}

function assetKind(asset) {
  return asset?.asset_type === "holding" ? "持仓" : "自选";
}

function assetAvatar(asset) {
  const name = asset?.stock_name || asset?.stock_code || "标的";
  const avatarClass = /腾讯/.test(name) ? "tencent" : /茅台/.test(name) ? "moutai" : "default";
  return `<span class="asset-avatar ${avatarClass}">${escapeHtml(name.slice(0, 2))}</span>`;
}

function showToast(message, tone = "") {
  if (!message) return;
  els.toast.textContent = message;
  els.toast.className = `toast is-visible ${tone}`.trim();
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    els.toast.classList.remove("is-visible");
  }, 2800);
}

function setGenerating(generating) {
  state.busy = generating;
  els.sendButton.classList.toggle("is-generating", generating);
  els.sendButton.setAttribute("aria-label", generating ? "停止生成" : "发送");
  els.sendButton.innerHTML = generating
    ? '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 12 7-7 7 7M12 5v14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}

function metricInfo(metricKey) {
  const snapshot = state.overview?.snapshot || {};
  const metrics = {
    price: { label: "最新价", value: snapshot.price, display: formatNumber(snapshot.price) },
    change: { label: "涨跌幅", value: snapshot.change_pct, display: snapshot.change_pct == null ? "—" : `${formatNumber(snapshot.change_pct)}%` },
    volume: { label: "成交量", value: snapshot.volume, display: formatCompactVolume(snapshot.volume) },
    amount: { label: "成交额", value: snapshot.amount, display: formatCompactVolume(snapshot.amount) },
    pe: { label: "动态市盈率", value: snapshot.pe_dynamic, display: formatNumber(snapshot.pe_dynamic) },
    pb: { label: "市净率", value: snapshot.pb, display: formatNumber(snapshot.pb) },
  };
  return metrics[metricKey] || { label: metricKey, value: null, display: "—" };
}

function metricButton(metricKey, text = null, className = "data-link") {
  const metric = metricInfo(metricKey);
  if (metric.value == null && !text) return "—";
  return `<button class="${className} pressable" type="button" data-metric="${escapeHtml(metricKey)}" aria-label="查看${escapeHtml(metric.label)}的数据详情">${escapeHtml(text || metric.display)}</button>`;
}

function impactLabel(result) {
  return result?.impact_label || ({
    unaffected: "暂未影响",
    watch: "值得留意",
    may_affect: "可能影响原判断",
    insufficient: "信息不足",
  }[result?.impact_state] || "信息不足");
}

function impactClass(result) {
  if (result?.impact_state === "may_affect") return "";
  if (result?.impact_state === "unaffected") return "support";
  return result?.impact_state === "insufficient" ? "uncertain" : "";
}

function claimsMarkup(items, includeUncertainty = false) {
  if (!Array.isArray(items) || !items.length) return '<span class="muted">暂无记录</span>';
  return `<ul class="claim-list">${items.map((item) => {
    const claim = typeof item === "object" ? item.claim : item;
    const refs = typeof item === "object" ? item.evidence_ids || [] : [];
    const uncertainty = typeof item === "object" ? item.uncertainty : "";
    return `<li>${escapeHtml(claim || "")}${includeUncertainty && uncertainty ? `<div class="muted small">不确定性：${escapeHtml(uncertainty)}</div>` : ""}${refs.map((id) => `<button type="button" data-source-id="${escapeHtml(id)}">证据 ${escapeHtml(id.slice(0, 8))}</button>`).join("")}</li>`;
  }).join("")}</ul>`;
}

function analysisMarkup(result) {
  if (!result) return '<div class="analysis-row"><div class="analysis-value muted">选择一条动态后生成分析。</div></div>';
  return `
    <div class="analysis-row"><div class="analysis-label">已知事实</div><div class="analysis-value">${claimsMarkup(result.facts)}</div></div>
    <div class="analysis-row"><div class="analysis-label">当前推断</div><div class="analysis-value">${claimsMarkup(result.inferences, true)}</div></div>
    <div class="analysis-row"><div class="analysis-label">尚不确定</div><div class="analysis-value">${claimsMarkup(result.unknowns)}</div></div>
    <div class="analysis-row"><div class="analysis-label">下一步可核验</div><div class="analysis-value">${claimsMarkup(result.next_checks)}</div></div>
    <div class="notice">${escapeHtml(result.safety_boundary || "以上为研究信息整理，不构成投资建议。")}</div>
  `;
}

function renderAssetPopover() {
  const options = state.assets.map((asset) => `
    <button class="asset-option pressable" type="button" role="option" data-asset="${asset.id}" aria-checked="${asset.id === state.assetId}">
      ${assetAvatar(asset)}
      <span><span class="asset-name">${escapeHtml(asset.stock_name || asset.stock_code)}</span><span class="asset-kind">${assetKind(asset)} · ${escapeHtml(asset.stock_code)}</span></span>
      <svg class="checkmark" width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m4.5 10.5 3.2 3.2 7.8-7.8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
  `).join("");
  els.assetPopover.innerHTML = options + `
    <div class="popover-divider"></div>
    <button class="manage-assets pressable" type="button" data-sheet="assets">管理标的</button>
  `;
}

function renderEmptyState() {
  els.assetSwitcherLabel.textContent = "添加一个标的开始";
  els.conversation.innerHTML = `
    <article class="message assistant empty-state" data-tour="thesis">
      <div class="assistant-kicker"><span class="status-dot support"></span>本地研究工作区</div>
      <h1>先选择一个标的，再开始理解变化。</h1>
      <p>TradingBuddy 会把行情、公开事件和你的判断放在同一条研究主线上。没有标的时，不展示泛市场资讯。</p>
      <div class="message-actions"><button class="primary-button pressable" type="button" data-sheet="assets">添加自选或持仓</button></div>
      <div class="source-line"><span>仅整理公开研究信息</span><span>·</span><span>不连接券商账户</span></div>
    </article>
  `;
}

function renderLoading() {
  els.conversation.innerHTML = `
    <article class="message assistant empty-state">
      <div class="assistant-kicker"><span class="status-dot support"></span>正在准备研究工作区</div>
      <div class="loading-state">正在获取行情、事件和本地判断…</div>
    </article>
  `;
}

function eventSourceLabel(event) {
  return event?.source_type === "announcement" ? "公司公告" : event?.source_type === "news" ? "新闻" : "行情事实";
}

function eventFreshness(event) {
  return event?.content_status === "title_only" ? "仅标题" : event?.source_level === "primary" ? "一级来源" : "公开线索";
}

function renderEventPush(event, index) {
  const unread = !state.readEvents.has(event.event_id);
  const selected = event.event_id === state.selectedEventId;
  return `
    <article class="push-message ${selected ? "selected-push" : ""}" data-push-id="${escapeHtml(event.event_id)}">
      <div class="push-meta">${unread ? '<i class="unread-dot" aria-label="未读"></i>' : ""}<span>${escapeHtml(eventSourceLabel(event))}</span><span>·</span><span>${escapeHtml(formatDate(event.published_at))}</span><span class="push-priority">${escapeHtml(eventFreshness(event))}</span></div>
      <h2>${escapeHtml(event.title || "未命名动态")}</h2>
      <p class="push-summary">${escapeHtml(event.excerpt || "当前仅有标题，无法核验正文细节。")}</p>
      <p class="push-reason"><strong>为什么保留：</strong>${event.source_level === "primary" ? "一级来源优先进入研究范围。" : "作为公开线索保留，不能单独推出原因结论。"}</p>
      <div class="message-actions">
        <button class="prompt-chip pressable" type="button" data-action="select-event" data-event-id="${escapeHtml(event.event_id)}">${selected ? "已选择分析" : "选择分析"}</button>
        <button class="text-button pressable" type="button" data-source-id="${escapeHtml(event.event_id)}">查看来源</button>
      </div>
    </article>
  `;
}

function renderMessage(message) {
  if (message.role === "user") {
    return `<article class="message user"><div class="user-message">${escapeHtml(message.content || "")}</div></article>`;
  }
  let text = message.content || "";
  try {
    const parsed = JSON.parse(text);
    text = parsed.result?.conclusion || parsed.conclusion || text;
  } catch {
    // 兼容旧版本保存的普通文本消息。
  }
  return `<article class="message assistant"><div class="assistant-kicker"><span class="status-dot support"></span>AI 投研助手</div><div class="answer-copy">${escapeHtml(text)}</div></article>`;
}

function renderContextLine(asset, event) {
  const snapshot = state.overview?.snapshot || {};
  const updated = snapshot.price_time || snapshot.fetched_at || state.overview?.fetched_at;
  return `
    <div class="context-line">
      <strong>${escapeHtml(asset.stock_name || asset.stock_code)}</strong>
      <span>${metricButton("price")}</span><span class="context-dot">·</span><span>${metricButton("change")}</span>
      <span class="context-dot">·</span><span>更新于 ${escapeHtml(formatDate(updated))}</span>
    </div>
    <div class="feed-toolbar" aria-label="研究数据状态">
      <span class="feed-status"><i class="feed-pulse" aria-hidden="true"></i>已接入 ${state.overview?.events?.length || 0} 条公开动态与行情数据</span>
      <button class="simulate-button pressable" type="button" data-action="refresh">刷新数据</button>
    </div>
  `;
}

function renderDynamicMessage(asset, event) {
  const result = state.analysis;
  const status = result ? impactLabel(result) : event ? "信息待核验" : "暂无动态";
  const statusClass = result ? impactClass(result) : "uncertain";
  const headline = event?.title || "今天暂时没有需要解释的新动态";
  const lede = event?.excerpt || "当前没有可确认的事件。你可以先查看行情，或在研究档案中保存自己的判断。";
  const promptList = ["这条动态影响我的判断吗？", "只说已知事实", "还有哪些信息要核验？"];
  return `
    <article class="message assistant" data-tour="thesis">
      <div data-tour="dynamic">
        <div class="assistant-kicker"><span class="status-dot ${statusClass}"></span>今日最重要的变化 · ${event ? escapeHtml(eventSourceLabel(event)) : "数据状态"}</div>
        <h1>${escapeHtml(headline)}</h1>
        <p class="lede">${escapeHtml(lede)}</p>
        <div class="conclusion-row"><div class="impact-line"><span class="impact-pill ${statusClass}">${escapeHtml(status)}</span><span>相对于研究档案中的判断</span></div><button class="detail-link pressable" type="button" data-trace="primary">详情</button></div>
      </div>
      <div class="message-actions" data-tour="actions">
        ${promptList.map((prompt) => `<button class="prompt-chip pressable" type="button" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`).join("")}
        ${result ? '<button class="text-button pressable" type="button" data-analysis-toggle="latest" aria-expanded="false">展开分析</button>' : event ? '<button class="text-button pressable" type="button" data-action="run-analysis">生成分析</button>' : ""}
      </div>
      ${result ? `<div class="analysis" data-analysis="latest" hidden><p class="analysis-conclusion">${escapeHtml(result.conclusion || "未形成结论")}</p>${analysisMarkup(result)}</div>` : ""}
      <div class="source-line"><span>${state.overview?.events?.length || 0} 个来源</span><span>·</span><button type="button" data-archive-tab="sources">查看来源记录</button></div>
    </article>
  `;
}

function renderConversation() {
  renderAssetPopover();
  const asset = state.overview?.asset || selectedAsset();
  if (!asset) {
    renderEmptyState();
    return;
  }
  els.assetSwitcherLabel.textContent = `${asset.stock_name || asset.stock_code} · ${assetKind(asset)}`;
  if (state.pending) {
    const pendingLabel = state.pending.type === "research" ? "正在核验事件与研究判断" : "正在回答当前问题";
    els.conversation.innerHTML = renderContextLine(asset, state.overview?.events?.[0])
      + renderImportanceChart(state.importanceRows, { escapeHtml })
      + renderDynamicMessage(asset, state.overview?.events?.[0])
      + (state.pending.question ? `<article class="message user"><div class="user-message">${escapeHtml(state.pending.question)}</div></article>` : "")
      + `<article class="message assistant"><div class="assistant-kicker"><span class="status-dot support"></span>AI 正在工作</div><div class="thinking-state"><span>${pendingLabel}</span><span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span></div></article>`;
    bindImportance();
    return;
  }
  const events = state.overview?.events || [];
  const event = events.find((item) => item.event_id === state.selectedEventId) || events[0] || null;
  if (event) state.selectedEventId = event.event_id;
  const olderEvents = event ? events.filter((item) => item.event_id !== event.event_id).slice(0, 8) : [];
  const messages = state.overview?.messages || [];
  els.conversation.innerHTML = renderContextLine(asset, event)
    + renderImportanceChart(state.importanceRows, { escapeHtml })
    + renderDynamicMessage(asset, event)
    + olderEvents.map(renderEventPush).join("")
    + messages.map(renderMessage).join("");
  bindImportance();
}

function bindImportance() {
  const chart = els.conversation.querySelector(".importance-timeline");
  if (!chart) return;
  bindImportanceChart(chart, {
    rows: state.importanceRows,
    escapeHtml,
    onOpen: (date, trigger) => openSheet("importanceDay", trigger, { date }),
    onRange: async (days) => {
      if (days === state.importanceDays) return;
      state.importanceDays = days;
      try {
        const payload = await api(`/assets/${state.assetId}/importance?days=${days}`);
        state.importanceRows = payload.rows || [];
        renderConversation();
      } catch (error) {
        showToast(error.message, "error");
      }
    },
  });
}

function aggregateSeries(series, period = "day") {
  const groupSize = period === "week" ? 5 : period === "month" ? 20 : 1;
  const grouped = [];
  for (let index = 0; index < series.length; index += groupSize) {
    const group = series.slice(index, index + groupSize);
    if (!group.length) continue;
    grouped.push({
      date: group.at(-1).date,
      open: Number(group[0].open),
      high: Math.max(...group.map((point) => Number(point.high))),
      low: Math.min(...group.map((point) => Number(point.low))),
      close: Number(group.at(-1).close),
      volume: group.reduce((sum, point) => sum + Number(point.volume || 0), 0),
    });
  }
  return grouped.slice(-(period === "day" ? 38 : period === "week" ? 20 : 12));
}

function renderCandlestickChart(period = "day") {
  const rows = (state.overview?.history?.rows || []).filter((row) => Number.isFinite(Number(row.close)));
  const data = aggregateSeries(rows, period);
  if (data.length < 2) return '<div class="detail-section"><p>当前周期的数据点不足，指标摘要仍可查看。</p></div>';
  const width = 500;
  const height = 300;
  const plotLeft = 10;
  const plotRight = 450;
  const priceTop = 16;
  const priceBottom = 202;
  const volumeTop = 224;
  const volumeBottom = 276;
  const minPrice = Math.min(...data.map((point) => point.low));
  const maxPrice = Math.max(...data.map((point) => point.high));
  const maxVolume = Math.max(...data.map((point) => point.volume), 1);
  const priceRange = Math.max(0.01, maxPrice - minPrice);
  const xStep = (plotRight - plotLeft) / data.length;
  const candleWidth = Math.max(3, Math.min(9, xStep * 0.58));
  const xAt = (index) => plotLeft + xStep * index + xStep / 2;
  const yAt = (value) => priceBottom - ((value - minPrice) / priceRange) * (priceBottom - priceTop);
  const grid = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    const y = priceTop + ratio * (priceBottom - priceTop);
    const price = maxPrice - ratio * priceRange;
    return `<line class="chart-grid-line" x1="${plotLeft}" y1="${y}" x2="${plotRight}" y2="${y}"/><text class="chart-axis-label" x="458" y="${y + 3}">${price.toFixed(1)}</text>`;
  }).join("");
  const candles = data.map((point, index) => {
    const x = xAt(index);
    const openY = yAt(point.open);
    const closeY = yAt(point.close);
    const highY = yAt(point.high);
    const lowY = yAt(point.low);
    const up = point.close >= point.open;
    const className = up ? "chart-candle-up" : "chart-candle-down";
    const bodyY = Math.min(openY, closeY);
    const bodyHeight = Math.max(1.5, Math.abs(closeY - openY));
    const volumeHeight = point.volume / maxVolume * (volumeBottom - volumeTop);
    return `<g><title>${escapeHtml(point.date)} 开 ${point.open.toFixed(2)} 高 ${point.high.toFixed(2)} 低 ${point.low.toFixed(2)} 收 ${point.close.toFixed(2)} 量 ${escapeHtml(formatCompactVolume(point.volume))}</title><line class="${className}" x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}"/><rect class="${className}" x="${x - candleWidth / 2}" y="${bodyY}" width="${candleWidth}" height="${bodyHeight}" rx=".7"/><rect class="chart-volume" x="${x - candleWidth / 2}" y="${volumeBottom - volumeHeight}" width="${candleWidth}" height="${volumeHeight}" rx="1"/></g>`;
  }).join("");
  const average = data.map((point, index) => {
    const window = data.slice(Math.max(0, index - 4), index + 1);
    return { x: xAt(index), y: yAt(window.reduce((sum, item) => sum + item.close, 0) / window.length) };
  });
  const maPath = average.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const eventDates = new Set((state.overview?.events || []).map((event) => String(event.published_at || "").slice(0, 10)));
  const eventMarks = data.map((point, index) => {
    if (!eventDates.has(String(point.date).slice(0, 10))) return "";
    const x = xAt(index);
    return `<g><title>关键事件 ${escapeHtml(point.date)}</title><line class="chart-event-line" x1="${x}" y1="31" x2="${x}" y2="${priceBottom}"/><circle class="chart-event-dot" cx="${x}" cy="24" r="4"/></g>`;
  }).join("");
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="日线 K 线、成交量、五期均线与事件标记">
      ${grid}<line class="chart-grid-line" x1="${plotLeft}" y1="${volumeTop}" x2="${plotRight}" y2="${volumeTop}"/>${candles}<path class="chart-ma" d="${maPath}"/>${eventMarks}
      <text class="chart-axis-label" x="${plotLeft}" y="294">${escapeHtml(String(data[0].date).slice(5))}</text>
      <text class="chart-axis-label" x="${plotRight}" y="294" text-anchor="end">${escapeHtml(String(data.at(-1).date).slice(5))}</text>
    </svg>
    <div class="chart-legend"><span class="legend-item"><i class="legend-swatch"></i>五期均线</span><span class="legend-item"><i class="legend-swatch volume"></i>成交量</span><span class="legend-item"><i class="legend-swatch event"></i>关键事件</span></div>
  `;
}

function sheetHeader(title, context = "", back = false) {
  return `
    <div class="sheet-header chrome">
      <div class="sheet-heading-group"><h2 class="sheet-title" id="sheet-title" tabindex="-1">${escapeHtml(title)}</h2>${context ? `<span class="sheet-context">${escapeHtml(context)}</span>` : ""}</div>
      <div class="sheet-header-actions">${back ? '<button class="sheet-back pressable" type="button" data-sheet-back aria-label="返回上一层"><svg viewBox="0 0 24 24" fill="none"><path d="m14.5 5-7 7 7 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>' : ""}<button class="icon-button pressable" type="button" data-close-sheet aria-label="关闭"><svg viewBox="0 0 24 24" fill="none"><path d="m7 7 10 10M17 7 7 17" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg></button></div>
    </div>
  `;
}

function archiveSheet(tab = state.archiveTab) {
  state.archiveTab = tab;
  const thesis = state.overview?.thesis;
  const result = state.analysis;
  let panel = "";
  if (tab === "thesis") {
    panel = thesis ? `
      <div class="archive-summary"><div><strong>当前判断 · 版本 ${escapeHtml(thesis.version)}</strong><p>这是你主动确认的研究前提，AI 只提供复核信息，不会自动改写。</p></div><div><span class="confidence-value">已确认</span><span class="confidence-label">本地版本</span></div></div>
      <section class="detail-section"><span class="detail-eyebrow">核心判断</span><p>${escapeHtml(thesis.core_thesis)}</p></section>
      <section class="detail-section"><span class="detail-eyebrow">重点观察</span><p>${escapeHtml(thesis.watch_variables || "尚未填写")}</p></section>
      <section class="detail-section"><span class="detail-eyebrow">判断失效条件</span><p>${escapeHtml(thesis.invalid_conditions || "尚未填写")}</p></section>
      <div class="button-row"><button class="primary-button pressable" type="button" data-edit-thesis>编辑我的判断</button></div>
    ` : `
      <div class="uncertainty-callout"><strong>还没有已确认的判断</strong><p>先写下你为什么关注这个标的、准备观察什么，以及什么情况会让判断失效。</p></div>
      <div class="button-row"><button class="primary-button pressable" type="button" data-edit-thesis>建立我的判断</button></div>
    `;
  } else if (tab === "data") {
    const metrics = ["price", "change", "volume", "amount", "pe", "pb"];
    panel = `
      <div class="chart-hero"><div class="chart-hero-label">最新价</div><div class="chart-hero-value">${escapeHtml(metricInfo("price").display)}</div><div class="chart-hero-meta">${escapeHtml(state.overview?.snapshot?.price_time || state.overview?.data_time || "时间未知")}</div></div>
      <div class="chart-toolbar"><div class="period-control">${["day", "week", "month"].map((period) => `<button class="period-button pressable" type="button" data-chart-period="${period}" data-metric-key="price" aria-pressed="${state.chartPeriod === period}">${period === "day" ? "日" : period === "week" ? "周" : "月"}</button>`).join("")}</div><span class="chart-status">真实行情 · ${escapeHtml(state.overview?.history?.data_time || "时间未知")}</span></div>
      <div class="chart-shell">${renderCandlestickChart(state.chartPeriod)}</div>
      <div class="metric-grid">${metrics.map((key) => `<button class="metric-card pressable" type="button" data-metric="${key}"><span class="metric-card-label">${escapeHtml(metricInfo(key).label)}</span><span class="metric-card-value">${escapeHtml(metricInfo(key).display)}</span><span class="metric-card-delta">${key === "change" ? "相对上一交易日" : "查看数据口径"}</span></button>`).join("")}</div>
    `;
  } else if (tab === "inferences") {
    panel = result ? `
      <div class="detail-section"><span class="detail-eyebrow">当前分析</span><h3>${escapeHtml(result.conclusion || "未形成结论")}</h3><p>所有事实和推断都必须从当前证据范围中核验。</p></div>
      <div class="reasoning-chain">${(result.facts || []).concat(result.inferences || []).map((item, index) => `<section class="reasoning-node"><div class="reasoning-rail"><span class="reasoning-index">${index + 1}</span></div><div class="reasoning-content"><span class="reasoning-kind">${index < (result.facts || []).length ? "已知事实" : "当前推断"}</span><h3>${escapeHtml(item.claim || "")}</h3>${item.uncertainty ? `<p>${escapeHtml(item.uncertainty)}</p>` : ""}<div class="citation-row">${(item.evidence_ids || []).map((id) => `<button class="citation-button pressable" type="button" data-source-id="${escapeHtml(id)}">证据 ${escapeHtml(id.slice(0, 8))}</button>`).join("")}</div></div></section>`).join("")}</div>
    ` : '<div class="uncertainty-callout"><strong>还没有可核验的推断</strong><p>选择一条动态并生成分析后，这里会展示事实、推断与引用关系。</p></div>';
  } else {
    const events = state.overview?.events || [];
    panel = events.length ? events.slice(0, 12).map((event) => `
      <section class="source-card"><div class="source-card-head"><div><div class="source-meta"><span>${escapeHtml(eventSourceLabel(event))}</span><span>·</span><span>${escapeHtml(formatDate(event.published_at))}</span></div><h3><button class="text-button pressable" type="button" data-source-id="${escapeHtml(event.event_id)}">${escapeHtml(event.title)}</button></h3></div><span class="source-state ${event.content_status === "title_only" ? "offline" : ""}">${escapeHtml(eventFreshness(event))}</span></div><p class="source-related">${escapeHtml(event.excerpt || "当前无正文摘录。")}</p></section>
    `).join("") : '<div class="uncertainty-callout"><strong>暂无已保存来源</strong><p>刷新数据后，公开事件会出现在这里。</p></div>';
  }
  return `${sheetHeader("研究档案", selectedAsset()?.stock_code || "")}<div class="sheet-body"><div class="archive-tabs">${["thesis", "data", "inferences", "sources"].map((item) => `<button class="archive-tab pressable" type="button" data-archive-tab="${item}" aria-selected="${tab === item}">${item === "thesis" ? "判断" : item === "data" ? "数据" : item === "inferences" ? "推断" : "来源"}</button>`).join("")}</div><div class="archive-panel">${panel}</div></div>`;
}

function traceSheet() {
  const result = state.analysis;
  return `${sheetHeader("推断链", "当前分析", true)}<div class="sheet-body">${result ? `<section class="detail-section"><span class="detail-eyebrow">结论</span><h3>${escapeHtml(result.conclusion || "未形成结论")}</h3><p>影响状态：${escapeHtml(impactLabel(result))}</p></section><div class="reasoning-chain">${(result.facts || []).concat(result.inferences || []).map((item, index) => `<section class="reasoning-node"><div class="reasoning-rail"><span class="reasoning-index">${index + 1}</span></div><div class="reasoning-content"><span class="reasoning-kind">${index < (result.facts || []).length ? "已知事实" : "当前推断"}</span><h3>${escapeHtml(item.claim || "")}</h3><div class="citation-row">${(item.evidence_ids || []).map((id) => `<button class="citation-button pressable" type="button" data-source-id="${escapeHtml(id)}">查看证据 ${escapeHtml(id.slice(0, 8))}</button>`).join("")}</div></div></section>`).join("")}</div>` : '<div class="uncertainty-callout"><strong>尚未生成分析</strong><p>选择动态后生成分析，系统会在这里展示它如何连接到证据。</p></div>'}</div>`;
}

function metricSheet(metricKey = "price") {
  const metric = metricInfo(metricKey);
  return `${sheetHeader(metric.label, selectedAsset()?.stock_code || "", true)}<div class="sheet-body"><div class="chart-hero"><div class="chart-hero-label">${escapeHtml(metric.label)}</div><div class="chart-hero-value">${escapeHtml(metric.display)}</div><div class="chart-hero-meta">数据时间：${escapeHtml(state.overview?.snapshot?.price_time || state.overview?.data_time || "时间未知")}</div></div><div class="chart-toolbar"><div class="period-control">${["day", "week", "month"].map((period) => `<button class="period-button pressable" type="button" data-chart-period="${period}" data-metric-key="${escapeHtml(metricKey)}" aria-pressed="${state.chartPeriod === period}">${period === "day" ? "日" : period === "week" ? "周" : "月"}</button>`).join("")}</div><span class="chart-status">腾讯 / 新浪 / AkShare</span></div><div class="chart-shell">${renderCandlestickChart(state.chartPeriod)}</div><section class="detail-section"><span class="detail-eyebrow">数据说明</span><p>图表展示本地缓存的真实公开行情；抓取时间、数据时间和降级状态以页面状态为准。</p></section></div>`;
}

function sourceSheet(sourceId) {
  const source = state.sheetData || (state.overview?.events || []).find((event) => event.event_id === sourceId);
  if (!source) return `${sheetHeader("证据详情", "正在读取", true)}<div class="sheet-body"><div class="loading-state">正在读取来源详情…</div></div>`;
  return `${sheetHeader("证据详情", eventSourceLabel(source), true)}<div class="sheet-body"><section class="detail-section"><span class="detail-eyebrow">${escapeHtml(source.source_level || eventFreshness(source))} · ${escapeHtml(formatDate(source.published_at))}</span><h3>${escapeHtml(source.title)}</h3><p class="evidence-quote">${escapeHtml(source.excerpt || "当前仅保留标题，无法核验正文细节。")}</p><div class="evidence-meta"><span>${escapeHtml(source.publisher || "公开来源")}</span><span>·</span><span>${escapeHtml(source.content_status || "excerpt")}</span></div></section><section class="detail-section"><span class="detail-eyebrow">证据编号</span><p>${escapeHtml(source.evidence_id || source.event_id || sourceId)}</p><div class="button-row">${source.source_url ? `<a class="secondary-button pressable" href="${escapeHtml(source.source_url)}" target="_blank" rel="noreferrer">打开原始来源</a>` : '<span class="muted">当前没有外部链接。</span>'}</div></section></div>`;
}

function thesisEditSheet() {
  const thesis = state.overview?.thesis || {};
  return `${sheetHeader("维护我的判断", "保存后形成新版本", true)}<div class="sheet-body"><form id="thesis-edit-form" class="sheet-form"><label>核心判断<textarea name="core_thesis" required>${escapeHtml(thesis.core_thesis || "")}</textarea></label><label>重点观察<textarea name="watch_variables">${escapeHtml(thesis.watch_variables || "")}</textarea></label><label>判断失效条件<textarea name="invalid_conditions">${escapeHtml(thesis.invalid_conditions || "")}</textarea></label><div class="button-row"><button class="primary-button pressable" type="submit">保存新版本</button></div></form></div>`;
}

function assetsSheet() {
  const rows = state.assets.length ? state.assets.map((asset) => `
    <div class="managed-asset"><span>${assetAvatar(asset)}</span><span><strong>${escapeHtml(asset.stock_name || asset.stock_code)}</strong><small>${assetKind(asset)} · ${escapeHtml(asset.stock_code)}</small></span><button class="text-button pressable" type="button" data-asset="${asset.id}">查看</button></div>
  `).join("") : '<div class="uncertainty-callout"><strong>还没有标的</strong><p>添加一个六位 A 股代码即可开始。</p></div>';
  return `${sheetHeader("管理标的", "本地保存") }<div class="sheet-body"><div class="managed-assets">${rows}</div><div class="button-row"><button class="primary-button pressable" type="button" data-sheet="add">添加标的</button></div></div>`;
}

function addAssetSheet() {
  return `${sheetHeader("添加标的", "自选或手动持仓", true)}<div class="sheet-body"><form id="add-asset-form" class="sheet-form"><label>六位股票代码<input name="stock_code" inputmode="numeric" pattern="[0-9]{6}" placeholder="例如 600519" required></label><div class="button-row"><button class="primary-button pressable" type="submit">直接添加代码</button></div></form><form id="stock-search-form" class="sheet-form" style="margin-top:24px"><label>搜索股票名称或代码<input name="query" placeholder="例如 茅台"></label><div class="button-row"><button class="secondary-button pressable" type="submit">搜索</button></div></form><div id="search-results" class="search-results"></div><div class="notice">搜索依赖股票清单接口；若接口暂不可用，可以直接输入六位代码添加。</div></div>`;
}

function settingsSheet() {
  const configured = Boolean(state.overview && state.overview.fetched_at);
  return `${sheetHeader("设置", "当前本机实例") }<div class="sheet-body"><section class="detail-section"><span class="detail-eyebrow">产品边界</span><p>TradingBuddy 只整理研究信息，不连接券商、不执行交易，也不提供买卖指令。</p></section><section class="detail-section"><span class="detail-eyebrow">数据状态</span><p>${configured ? "当前标的的本地数据已加载。" : "添加标的后加载本地数据。"}</p></section><section class="detail-section"><span class="detail-eyebrow">AI 配置</span><p>模型配置保存在仓库根目录的 .env 中。API Key 不在页面展示，也不会写入仓库。</p></section></div>`;
}

function renderSheet() {
  if (!state.sheetView) return;
  const view = state.sheetView;
  if (view.type === "archive") els.sheet.innerHTML = archiveSheet(view.tab || state.archiveTab);
  if (view.type === "trace") els.sheet.innerHTML = traceSheet();
  if (view.type === "metric") els.sheet.innerHTML = metricSheet(view.metricKey);
  if (view.type === "source") els.sheet.innerHTML = sourceSheet(view.sourceId);
  if (view.type === "thesis") els.sheet.innerHTML = archiveSheet("thesis");
  if (view.type === "editThesis") els.sheet.innerHTML = thesisEditSheet();
  if (view.type === "assets") els.sheet.innerHTML = assetsSheet();
  if (view.type === "add") els.sheet.innerHTML = addAssetSheet();
  if (view.type === "settings") els.sheet.innerHTML = settingsSheet();
  if (view.type === "importanceDay") {
    els.sheet.innerHTML = `${sheetHeader("研究重要性", view.date || "", true)}<div class="sheet-body"><div class="loading-state">正在读取当日评分…</div></div>`;
  }
  if (view.type === "importanceCategory") {
    els.sheet.innerHTML = `${sheetHeader(view.category || "评分详情", view.date || "", true)}<div class="sheet-body"><div class="loading-state">正在读取评分因子…</div></div>`;
  }
}

function openSheet(type, trigger = null, options = {}, pushHistory = true) {
  closeAssetPopover();
  if (state.sheetView && pushHistory) state.sheetHistory.push({ ...state.sheetView });
  state.sheetView = { type, ...options };
  state.sheetData = null;
  if (trigger) state.lastTrigger = trigger;
  els.sheet.classList.add("is-open");
  els.sheet.setAttribute("aria-hidden", "false");
  renderSheet();
  requestAnimationFrame(() => els.sheet.querySelector("#sheet-title")?.focus());
  if (type === "source" && options.sourceId) loadSourceDetail(options.sourceId);
  if (type === "importanceDay" && options.date) loadImportanceDay(options.date);
  if (type === "importanceCategory" && options.date && options.category) loadImportanceCategory(options.date, options.category);
}

async function loadImportanceDay(date) {
  try {
    const body = await api(`/assets/${state.assetId}/importance/${encodeURIComponent(date)}`);
    if (state.sheetView?.type === "importanceDay" && state.sheetView.date === date) {
      state.sheetData = body;
      els.sheet.innerHTML = dailyImportanceSheet(body, { sheetHeader, escapeHtml });
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function loadImportanceCategory(date, category) {
  try {
    const body = await api(`/assets/${state.assetId}/importance/${encodeURIComponent(date)}/${encodeURIComponent(category)}`);
    if (state.sheetView?.type === "importanceCategory" && state.sheetView.date === date && state.sheetView.category === category) {
      state.sheetData = body;
      els.sheet.innerHTML = categoryImportanceSheet(body, { sheetHeader, escapeHtml });
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function loadSourceDetail(sourceId) {
  try {
    const body = await api(`/evidence/${encodeURIComponent(sourceId)}`);
    if (state.sheetView?.type === "source" && state.sheetView.sourceId === sourceId) {
      state.sheetData = body.evidence;
      renderSheet();
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

function closeSheet() {
  if (!state.sheetView) return;
  state.sheetView = null;
  state.sheetHistory = [];
  state.sheetData = null;
  els.sheet.classList.remove("is-open");
  els.sheet.setAttribute("aria-hidden", "true");
  if (state.lastTrigger?.isConnected) state.lastTrigger.focus();
}

function backSheet() {
  const previous = state.sheetHistory.pop();
  if (!previous) {
    closeSheet();
    return;
  }
  state.sheetView = previous;
  state.sheetData = null;
  renderSheet();
  requestAnimationFrame(() => els.sheet.querySelector("#sheet-title")?.focus());
}

function toggleAnalysis(id) {
  const panel = document.querySelector(`[data-analysis="${id}"]`);
  const trigger = document.querySelector(`[data-analysis-toggle="${id}"]`);
  if (!panel || !trigger) return;
  const willOpen = panel.hidden;
  panel.hidden = !willOpen;
  trigger.setAttribute("aria-expanded", String(willOpen));
  trigger.textContent = willOpen ? "收起分析" : "展开分析";
}

function abortGeneration() {
  if (state.abortController) state.abortController.abort();
  state.abortController = null;
  state.pending = null;
  setGenerating(false);
  renderConversation();
}

function parseSSEBlock(block) {
  const lines = block.split(/\r?\n/);
  const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
  try { return { event, data: JSON.parse(data || "{}") }; } catch { return { event, data: { message: data } }; }
}

async function stream(path, payload, onEvent) {
  state.abortController = new AbortController();
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal: state.abortController.signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败（${response.status}）`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    blocks.filter(Boolean).forEach((block) => onEvent(parseSSEBlock(block)));
    if (done) break;
  }
  if (buffer.trim()) onEvent(parseSSEBlock(buffer));
}

async function runAnalysis() {
  if (!state.assetId || !state.selectedEventId || state.busy) return;
  const question = "请分析当前事件对我的研究判断有什么意义。";
  state.pending = { type: "research" };
  setGenerating(true);
  renderConversation();
  try {
    await stream("/research/stream", { asset_id: state.assetId, event_id: state.selectedEventId }, ({ event, data }) => {
      if (event === "failed") showToast(data.message || "分析失败；原始来源仍可查看。", "error");
    });
    await loadOverview(state.assetId);
    showToast("分析完成", "success");
  } catch (error) {
    if (error.name !== "AbortError") showToast(error.message, "error");
  } finally {
    state.pending = null;
    state.abortController = null;
    setGenerating(false);
    renderConversation();
  }
}

async function runChat(question) {
  if (!state.assetId || state.busy || !question.trim()) return;
  state.pending = { type: "chat", question };
  setGenerating(true);
  renderConversation();
  requestAnimationFrame(() => els.conversationScroll.scrollTo({ top: els.conversationScroll.scrollHeight, behavior: "smooth" }));
  try {
    await stream("/chat/stream", { asset_id: state.assetId, event_id: state.selectedEventId, question }, ({ event, data }) => {
      if (event === "failed") showToast(data.message || "回答失败；没有生成替代结论。", "error");
    });
    await loadOverview(state.assetId);
    showToast("回答完成", "success");
  } catch (error) {
    if (error.name !== "AbortError") showToast(error.message, "error");
  } finally {
    state.pending = null;
    state.abortController = null;
    setGenerating(false);
    renderConversation();
    requestAnimationFrame(() => els.conversationScroll.scrollTo({ top: els.conversationScroll.scrollHeight, behavior: "smooth" }));
  }
}

async function loadAssets(preferredId = null) {
  const body = await api("/assets");
  state.assets = body.assets || [];
  state.assetId = preferredId || state.assetId || state.assets[0]?.id || null;
  renderAssetPopover();
  if (state.assetId) await loadOverview(state.assetId);
  else renderConversation();
}

async function loadOverview(assetId) {
  state.assetId = Number(assetId);
  state.overview = null;
  renderLoading();
  try {
    const overview = await api(`/assets/${state.assetId}/overview`);
    const theses = await api(`/assets/${state.assetId}/theses`).catch(() => ({ history: [] }));
    const importance = await api(`/assets/${state.assetId}/importance?days=${state.importanceDays}`)
      .catch((error) => ({ rows: [], error: error.message }));
    overview.thesis_history = theses.history || [];
    state.overview = overview;
    state.importanceRows = importance.rows || [];
    state.importanceError = importance.error || "";
    state.analysis = overview.latest_analysis?.result || null;
    if (!overview.events?.some((event) => event.event_id === state.selectedEventId)) state.selectedEventId = overview.events?.[0]?.event_id || null;
    renderConversation();
  } catch (error) {
    state.overview = { asset: selectedAsset(), events: [] };
    els.conversation.innerHTML = `<article class="message assistant empty-state"><div class="assistant-kicker"><span class="status-dot uncertain"></span>数据暂时不可用</div><h1>仍可继续维护这个标的。</h1><p>行情或事件接口返回了错误，原始错误如下：</p><div class="error-callout message-error">${escapeHtml(error.message)}</div><div class="message-actions"><button class="primary-button pressable" type="button" data-action="refresh">重试</button></div></article>`;
  }
}

async function refreshData() {
  if (!state.assetId || state.busy) return;
  try {
    await api(`/assets/${state.assetId}/refresh`, { method: "POST" });
    await loadOverview(state.assetId);
    showToast("数据已刷新", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function addAsset(code) {
  const stockCode = String(code || "").trim();
  if (!stockCode) return;
  try {
    const asset = await api("/assets", { method: "POST", body: JSON.stringify({ stock_code: stockCode, asset_type: "watchlist" }) });
    await loadAssets(asset.id);
    closeSheet();
    showToast("标的已添加", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function searchStocks(form) {
  const query = new FormData(form).get("query")?.toString().trim();
  const results = $("#search-results");
  if (!query || !results) return;
  results.innerHTML = '<div class="loading-state">正在搜索…</div>';
  try {
    const body = await api(`/stocks/search?q=${encodeURIComponent(query)}`);
    results.innerHTML = (body.results || []).map((item) => `<div class="search-result"><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)}</small></div><button class="secondary-button pressable" type="button" data-action="add-search-result" data-code="${escapeHtml(item.code)}">添加</button></div>`).join("") || '<div class="muted small">没有找到匹配标的，可以直接输入六位代码。</div>';
  } catch (error) {
    results.innerHTML = `<div class="error-callout message-error">${escapeHtml(error.message)}</div>`;
  }
}

async function saveThesis(form) {
  const values = Object.fromEntries(new FormData(form).entries());
  if (!state.assetId || !String(values.core_thesis || "").trim()) {
    showToast("请先填写核心判断", "error");
    return;
  }
  try {
    await api(`/assets/${state.assetId}/theses`, { method: "POST", body: JSON.stringify({
      core_thesis: String(values.core_thesis).trim(),
      watch_variables: String(values.watch_variables || "").trim(),
      invalid_conditions: String(values.invalid_conditions || "").trim(),
    }) });
    await loadOverview(state.assetId);
    openSheet("archive", form, { tab: "thesis" }, false);
    showToast("已保存新的判断版本", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function selectAsset(assetId) {
  const id = Number(assetId);
  if (!state.assets.some((asset) => asset.id === id)) return;
  if (state.busy) abortGeneration();
  state.assetId = id;
  state.selectedEventId = null;
  state.analysis = null;
  state.overview = null;
  state.popoverOpen = false;
  els.assetPopover.classList.remove("is-open");
  els.assetSwitcher.setAttribute("aria-expanded", "false");
  closeSheet();
  renderConversation();
  els.conversationScroll.scrollTo({ top: 0, behavior: "smooth" });
  loadOverview(id).catch((error) => showToast(error.message, "error"));
}

function openAssetPopover() {
  renderAssetPopover();
  state.popoverOpen = true;
  els.assetPopover.classList.add("is-open");
  els.assetSwitcher.setAttribute("aria-expanded", "true");
}

function closeAssetPopover() {
  state.popoverOpen = false;
  els.assetPopover.classList.remove("is-open");
  els.assetSwitcher.setAttribute("aria-expanded", "false");
}

function setFixedRect(element, left, top, width, height) {
  element.style.left = `${Math.round(left)}px`;
  element.style.top = `${Math.round(top)}px`;
  element.style.width = `${Math.max(0, Math.round(width))}px`;
  element.style.height = `${Math.max(0, Math.round(height))}px`;
}

function renderTourPopover() {
  const step = tourSteps[state.tourIndex];
  const isLast = state.tourIndex === tourSteps.length - 1;
  els.tourPopover.innerHTML = `
    <div class="tour-step">${state.tourIndex + 1} / ${tourSteps.length}</div>
    <h2 class="tour-title" id="tour-title">${step.title}</h2>
    <p class="tour-body" id="tour-body">${step.body}</p>
    <div class="tour-actions"><button class="tour-skip pressable" type="button" data-tour-skip>跳过</button>${state.tourIndex > 0 ? '<button class="tour-back pressable" type="button" data-tour-prev>上一步</button>' : '<span aria-hidden="true"></span>'}<button class="tour-next pressable" type="button" data-tour-next>${isLast ? "开始使用" : "下一步"}</button></div>
  `;
}

function positionTour() {
  if (!state.tourActive) return;
  const step = tourSteps[state.tourIndex];
  const target = document.querySelector(step.target);
  if (!target) return;
  const rect = target.getBoundingClientRect();
  const gap = 10;
  const left = Math.max(8, rect.left - gap);
  const top = Math.max(8, rect.top - gap);
  const right = Math.min(window.innerWidth - 8, rect.right + gap);
  const bottom = Math.min(window.innerHeight - 8, rect.bottom + gap);
  setFixedRect(els.tourMasks.top, 0, 0, window.innerWidth, top);
  setFixedRect(els.tourMasks.left, 0, top, left, bottom - top);
  setFixedRect(els.tourMasks.right, right, top, window.innerWidth - right, bottom - top);
  setFixedRect(els.tourMasks.bottom, 0, bottom, window.innerWidth, window.innerHeight - bottom);
  setFixedRect(els.tourFocusRing, left, top, right - left, bottom - top);
  setFixedRect(els.tourBlocker, left, top, right - left, bottom - top);
  const bubbleRect = els.tourPopover.getBoundingClientRect();
  const bubbleWidth = bubbleRect.width || Math.min(324, window.innerWidth - 32);
  const bubbleHeight = bubbleRect.height || 190;
  const edge = 16;
  const spacing = 18;
  const canPlaceBelow = bottom + spacing + bubbleHeight <= window.innerHeight - edge;
  const placement = canPlaceBelow ? "bottom" : "top";
  const bubbleTop = canPlaceBelow ? bottom + spacing : Math.max(edge, top - spacing - bubbleHeight);
  const idealLeft = left + (right - left) / 2 - bubbleWidth / 2;
  const bubbleLeft = Math.max(edge, Math.min(idealLeft, window.innerWidth - bubbleWidth - edge));
  const arrowLeft = Math.max(26, Math.min(left + (right - left) / 2 - bubbleLeft, bubbleWidth - 26));
  els.tourPopover.style.left = `${Math.round(bubbleLeft)}px`;
  els.tourPopover.style.top = `${Math.round(bubbleTop)}px`;
  els.tourPopover.style.setProperty("--tour-arrow-left", `${Math.round(arrowLeft)}px`);
  els.tourPopover.dataset.placement = placement;
}

function showTourStep(index) {
  if (!state.tourActive) return;
  state.tourIndex = Math.max(0, Math.min(index, tourSteps.length - 1));
  const target = document.querySelector(tourSteps[state.tourIndex].target);
  if (!target) {
    if (state.tourIndex < tourSteps.length - 1) showTourStep(state.tourIndex + 1);
    else finishTour(false);
    return;
  }
  const rect = target.getBoundingClientRect();
  if ((rect.top < 8 || rect.bottom > window.innerHeight - 8) && !target.closest(".topbar") && !target.closest(".composer-dock")) {
    target.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  renderTourPopover();
  requestAnimationFrame(() => {
    positionTour();
    els.tourPopover.querySelector("[data-tour-next]")?.focus();
  });
}

function startTour(force = false) {
  const storageKey = "tradingbuddy-tour-complete-v1";
  if (state.tourActive || (!force && localStorage.getItem(storageKey) === "true")) return;
  clearTimeout(state.tourCloseTimer);
  state.tourReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  closeAssetPopover();
  closeSheet();
  state.tourActive = true;
  state.tourIndex = 0;
  els.tourLayer.hidden = false;
  els.appShell.inert = true;
  renderTourPopover();
  requestAnimationFrame(() => {
    els.tourLayer.classList.add("is-active");
    positionTour();
    els.tourPopover.querySelector("[data-tour-next]")?.focus();
  });
}

function finishTour(completed = true) {
  if (!state.tourActive) return;
  state.tourActive = false;
  els.appShell.inert = false;
  els.tourLayer.classList.remove("is-active");
  if (completed) localStorage.setItem("tradingbuddy-tour-complete-v1", "true");
  state.tourCloseTimer = setTimeout(() => {
    els.tourLayer.hidden = true;
    if (state.tourReturnFocus?.isConnected) state.tourReturnFocus.focus();
  }, 190);
}

function trapTourFocus(event) {
  if (event.key !== "Tab") return;
  const controls = [...els.tourPopover.querySelectorAll("button:not([disabled])")];
  if (!controls.length) return;
  const first = controls[0];
  const last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

els.assetSwitcher.addEventListener("click", () => state.popoverOpen ? closeAssetPopover() : openAssetPopover());

els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy) {
    abortGeneration();
    showToast("已停止生成");
    return;
  }
  const question = els.promptInput.value.trim();
  if (!question) return;
  els.promptInput.value = "";
  els.promptInput.style.height = "auto";
  runChat(question);
});

els.promptInput.addEventListener("input", () => {
  els.promptInput.style.height = "auto";
  els.promptInput.style.height = `${Math.min(els.promptInput.scrollHeight, 128)}px`;
});

els.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});

document.addEventListener("click", (event) => {
  const assetButton = event.target.closest("[data-asset]");
  const promptButton = event.target.closest("[data-prompt]");
  const sheetButton = event.target.closest("[data-sheet]");
  const metricLink = event.target.closest("[data-metric]");
  const traceLink = event.target.closest("[data-trace]");
  const archiveTab = event.target.closest("[data-archive-tab]");
  const sourceLink = event.target.closest("[data-source-id]");
  const periodButton = event.target.closest("[data-chart-period]");
  const action = event.target.closest("[data-action]");

  if (event.target.closest("[data-start-tour]")) startTour(true);
  if (event.target.closest("[data-tour-skip]")) finishTour(true);
  if (event.target.closest("[data-tour-prev]")) showTourStep(state.tourIndex - 1);
  if (event.target.closest("[data-tour-next]")) state.tourIndex === tourSteps.length - 1 ? finishTour(true) : showTourStep(state.tourIndex + 1);
  if (assetButton) {
    selectAsset(assetButton.dataset.asset);
    closeAssetPopover();
  }
  if (promptButton) runChat(promptButton.dataset.prompt);
  if (sheetButton) openSheet(sheetButton.dataset.sheet, sheetButton);
  if (metricLink) openSheet("metric", metricLink, { metricKey: metricLink.dataset.metric });
  if (traceLink) openSheet("trace", traceLink, {}, state.sheetView?.type !== "trace");
  if (archiveTab) openSheet("archive", archiveTab, { tab: archiveTab.dataset.archiveTab }, false);
  if (sourceLink) openSheet("source", sourceLink, { sourceId: sourceLink.dataset.sourceId });
  if (periodButton) {
    state.chartPeriod = periodButton.dataset.chartPeriod;
    openSheet("metric", periodButton, { metricKey: periodButton.dataset.metricKey }, false);
  }
  if (event.target.closest("[data-analysis-toggle]")) toggleAnalysis(event.target.closest("[data-analysis-toggle]").dataset.analysisToggle);
  if (event.target.closest("[data-edit-thesis]")) openSheet("editThesis", event.target.closest("[data-edit-thesis]"));
  if (event.target.closest("[data-close-sheet]")) closeSheet();
  if (event.target.closest("[data-sheet-back]")) backSheet();
  const importanceDay = event.target.closest("[data-importance-day]");
  const importanceCategory = event.target.closest("[data-importance-category]");
  if (importanceDay && !event.target.closest(".importance-chart-wrap")) {
    openSheet("importanceDay", importanceDay, { date: importanceDay.dataset.importanceDay });
  }
  if (importanceCategory && state.sheetView?.type === "importanceDay") {
    openSheet("importanceCategory", importanceCategory, {
      date: importanceCategory.dataset.importanceDate || state.sheetView.date,
      category: importanceCategory.dataset.importanceCategory,
    });
  }
  if (event.target.closest("[data-action='run-analysis']")) runAnalysis();
  if (event.target.closest("[data-action='select-event']")) {
    state.selectedEventId = event.target.closest("[data-action='select-event']").dataset.eventId;
    state.readEvents.add(state.selectedEventId);
    renderConversation();
  }
  if (event.target.closest("[data-action='refresh']")) refreshData();
  if (event.target.closest("[data-action='add-search-result']")) addAsset(event.target.closest("[data-action='add-search-result']").dataset.code);
  if (action?.dataset.action === "open-add") openSheet("add", action);
  if (event.target.closest(".asset-control") === null) closeAssetPopover();
});

document.addEventListener("submit", (event) => {
  if (event.target.id === "add-asset-form") {
    event.preventDefault();
    addAsset(new FormData(event.target).get("stock_code"));
  }
  if (event.target.id === "stock-search-form") {
    event.preventDefault();
    searchStocks(event.target);
  }
  if (event.target.id === "thesis-edit-form") {
    event.preventDefault();
    saveThesis(event.target);
  }
});

document.addEventListener("keydown", (event) => {
  if (state.tourActive) {
    trapTourFocus(event);
    if (event.key === "Escape") finishTour(true);
    if (event.key === "ArrowRight") {
      event.preventDefault();
      state.tourIndex === tourSteps.length - 1 ? finishTour(true) : showTourStep(state.tourIndex + 1);
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      showTourStep(state.tourIndex - 1);
    }
    return;
  }
  if (event.key === "Escape") {
    if (state.sheetView) closeSheet();
    else closeAssetPopover();
  }
});

window.addEventListener("resize", () => requestAnimationFrame(positionTour));
els.conversationScroll.addEventListener("scroll", () => requestAnimationFrame(positionTour), { passive: true });

loadAssets().then(() => {
  requestAnimationFrame(() => setTimeout(() => startTour(false), 260));
}).catch((error) => {
  els.conversation.innerHTML = `<article class="message assistant empty-state"><div class="assistant-kicker"><span class="status-dot uncertain"></span>启动失败</div><h1>研究工作区暂时无法加载。</h1><p class="error-callout message-error">${escapeHtml(error.message)}</p></article>`;
});
