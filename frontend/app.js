const API_ROOT = document.body.dataset.apiRoot || "/api";
const $ = (selector) => document.querySelector(selector);

const state = {
  assets: [],
  assetId: null,
  overview: null,
  selectedEventId: null,
  analysis: null,
  busy: false,
};

const els = {
  status: $("#global-status"),
  select: $("#asset-select"),
  addButton: $("#add-asset-button"),
  toggleButton: $("#toggle-type-button"),
  refreshButton: $("#refresh-button"),
  empty: $("#empty-state"),
  workspace: $("#workspace"),
  loading: $("#overview-loading"),
  meta: $("#asset-meta"),
  title: $("#asset-title"),
  subtitle: $("#asset-subtitle"),
  snapshot: $("#snapshot"),
  notices: $("#data-notices"),
  events: $("#events"),
  eventsMeta: $("#events-meta"),
  analysisState: $("#analysis-state"),
  analysis: $("#analysis"),
  analysisActions: $("#analysis-actions"),
  analyzeButton: $("#analyze-button"),
  sourceButton: $("#open-source-button"),
  messages: $("#messages"),
  chatForm: $("#chat-form"),
  chatInput: $("#chat-input"),
  chart: $("#chart"),
  indicators: $("#indicators"),
  thesisForm: $("#thesis-form"),
  thesisCore: $("#thesis-core"),
  thesisWatch: $("#thesis-watch"),
  thesisInvalid: $("#thesis-invalid"),
  thesisHistory: $("#thesis-history"),
  sources: $("#sources"),
  addModal: $("#add-modal"),
  addForm: $("#add-form"),
  stockQuery: $("#stock-query"),
  searchButton: $("#search-button"),
  searchResults: $("#search-results"),
  evidenceModal: $("#evidence-modal"),
  evidenceDetail: $("#evidence-detail"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function setStatus(message = "", tone = "") {
  els.status.textContent = message;
  els.status.className = `status-bar ${tone}`.trim();
}

async function api(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text }; }
  if (!response.ok) {
    const detail = body.detail || body.message || `请求失败（${response.status}）`;
    throw new Error(detail);
  }
  return body;
}

function selectedAsset() {
  return state.assets.find((asset) => asset.id === state.assetId) || null;
}

function renderAssetSelect() {
  els.select.innerHTML = state.assets.length
    ? state.assets.map((asset) => `<option value="${asset.id}">${escapeHtml(asset.stock_name)} · ${escapeHtml(asset.stock_code)} · ${asset.asset_type === "holding" ? "持仓" : "自选"}</option>`).join("")
    : '<option value="">添加一个标的开始</option>';
  els.select.value = state.assetId ? String(state.assetId) : "";
  const asset = selectedAsset();
  els.toggleButton.hidden = !asset;
  if (asset) {
    els.toggleButton.textContent = asset.asset_type === "holding" ? "改为自选" : "标记持仓";
  }
}

function renderOverviewShell() {
  const overview = state.overview;
  const asset = overview?.asset || selectedAsset();
  if (!asset) {
    els.empty.hidden = false;
    els.workspace.hidden = true;
    return;
  }
  els.empty.hidden = true;
  els.workspace.hidden = false;
  els.meta.textContent = `${asset.stock_code} · ${asset.asset_type === "holding" ? "手动持仓" : "自选标的"}`;
  els.title.textContent = asset.stock_name || asset.stock_code;
  els.subtitle.textContent = overview?.data_time ? `行情数据截至 ${overview.data_time}` : "正在获取行情与事件";
  renderSnapshot(overview?.snapshot);
  renderNotices(overview);
  renderEvents(overview?.events || []);
  renderChart(overview?.history?.rows || []);
  renderThesis(overview?.thesis, overview?.analyses || []);
  renderMessages(overview?.messages || []);
  renderSources(overview?.events || []);
  renderAnalysis(overview?.latest_analysis?.result || state.analysis);
}

function renderSnapshot(snapshot) {
  const change = snapshot?.change_pct;
  const changeClass = Number(change) > 0 ? "positive" : Number(change) < 0 ? "negative" : "";
  const cells = [
    ["最新价", snapshot?.price, ""],
    ["涨跌幅", change === null || change === undefined ? null : `${formatNumber(change)}%`, changeClass],
    ["成交量", snapshot?.volume, ""],
    ["更新时间", snapshot?.price_time || snapshot?.fetched_at, ""],
  ];
  els.snapshot.innerHTML = cells.map(([label, value, cls]) => `<dl class="metric"><dt>${label}</dt><dd class="${cls}">${escapeHtml(value ?? "—")}</dd></dl>`).join("");
}

function renderNotices(overview) {
  const notices = [];
  if (overview?.stale) notices.push("当前展示的是最近一次成功获取的数据，页面已标记为缓存降级状态。");
  Object.entries(overview?.errors || {}).forEach(([key, value]) => notices.push(`${key}：${value}`));
  (overview?.event_errors || []).forEach((message) => notices.push(message));
  els.notices.innerHTML = notices.map((notice) => `<div class="notice">${escapeHtml(notice)}</div>`).join("");
}

function renderEvents(events) {
  els.eventsMeta.textContent = events.length ? `${events.length} 条记录` : "暂无可确认事件";
  if (!events.length) {
    els.events.innerHTML = '<div class="analysis-empty">暂无事件。若行情可用，系统会在变化明显且没有高质量资讯时只展示行情事实，不生成原因解释。</div>';
    state.selectedEventId = null;
    els.analysisActions.hidden = true;
    return;
  }
  if (!events.some((event) => event.event_id === state.selectedEventId)) state.selectedEventId = events[0].event_id;
  els.events.innerHTML = events.map((event) => {
    const selected = event.event_id === state.selectedEventId;
    const time = event.published_at ? event.published_at.replace("T", " ") : "时间未知";
    return `<article class="event-card ${selected ? "selected" : ""}" data-event-card="${escapeHtml(event.event_id)}">
      <div class="event-meta"><span>${escapeHtml(event.source_type === "announcement" ? "公司公告" : event.source_type === "news" ? "新闻" : "行情事实")}</span><span>·</span><span>${escapeHtml(time)}</span><span>·</span><span>${escapeHtml(event.source_level === "primary" ? "一级来源" : "二级来源")}</span></div>
      <h3>${escapeHtml(event.title)}</h3>
      <p>${escapeHtml(event.excerpt || "当前仅有标题，无法核验正文细节。")}</p>
      <div class="event-actions"><button class="text-button" type="button" data-action="select-event" data-event-id="${escapeHtml(event.event_id)}">${selected ? "已选择" : "选择分析"}</button><button class="text-button" type="button" data-action="evidence" data-evidence-id="${escapeHtml(event.event_id)}">查看来源</button></div>
    </article>`;
  }).join("");
  els.analysisActions.hidden = false;
}

function renderAnalysis(result) {
  state.analysis = result || null;
  if (!result) {
    els.analysisState.textContent = "尚未分析";
    els.analysisState.className = "status-pill neutral";
    els.analysis.innerHTML = "选择一条动态后生成分析。切换标的或刷新页面不会自动调用模型。";
    return;
  }
  const stateClass = result.impact_state === "may_affect" ? "red" : result.impact_state === "watch" ? "amber" : result.impact_state === "unaffected" ? "green" : "neutral";
  els.analysisState.textContent = result.impact_label || ({ unaffected: "暂未影响", watch: "值得留意", may_affect: "可能影响原判断", insufficient: "信息不足" }[result.impact_state] || "信息不足");
  els.analysisState.className = `status-pill ${stateClass}`;
  const claims = (items, includeUncertainty = false) => (items || []).length
    ? `<ul class="claim-list">${items.map((item) => `<li>${escapeHtml(item.claim || item)}${includeUncertainty && item.uncertainty ? `<div class="muted small">不确定性：${escapeHtml(item.uncertainty)}</div>` : ""}${item.evidence_ids ? item.evidence_ids.map((id) => `<button type="button" data-action="evidence" data-evidence-id="${escapeHtml(id)}">证据 ${escapeHtml(id.slice(0, 8))}</button>`).join("") : ""}</li>`).join("")}</ul>`
    : '<span class="muted">暂无记录</span>';
  els.analysis.innerHTML = `<div class="analysis-result">
    <p class="analysis-conclusion">${escapeHtml(result.conclusion || "未形成结论")}</p>
    <div class="analysis-row"><div class="analysis-label">已知事实</div><div class="analysis-value">${claims(result.facts)}</div></div>
    <div class="analysis-row"><div class="analysis-label">当前推断</div><div class="analysis-value">${claims(result.inferences, true)}</div></div>
    <div class="analysis-row"><div class="analysis-label">尚不确定</div><div class="analysis-value">${claims(result.unknowns)}</div></div>
    <div class="analysis-row"><div class="analysis-label">下一步可核验</div><div class="analysis-value">${claims(result.next_checks)}</div></div>
    <div class="notice">${escapeHtml(result.safety_boundary || "以上为研究信息整理，不构成投资建议。")}</div>
  </div>`;
}

function renderMessages(messages) {
  els.messages.innerHTML = messages.length ? messages.map((message) => {
    let text = message.content || "";
    if (message.role === "assistant") {
      try { text = JSON.parse(text).result?.conclusion || text; } catch { /* legacy text */ }
    }
    return `<div class="message ${message.role === "user" ? "user" : "assistant"}"><div class="role">${message.role === "user" ? "你" : "AI 投研助手"}</div>${escapeHtml(text)}</div>`;
  }).join("") : '<div class="muted small">分析或追问完成后，对话会保存在当前标的下。</div>';
}

function renderChart(rows) {
  const valid = rows.filter((row) => Number.isFinite(Number(row.close)));
  if (valid.length < 2) {
    els.chart.innerHTML = '<div class="analysis-empty">暂无足够日线数据。</div>';
    els.indicators.innerHTML = "";
    return;
  }
  const recent = valid.slice(-80);
  const values = recent.map((row) => Number(row.close));
  const min = Math.min(...values), max = Math.max(...values), range = max - min || 1;
  const points = recent.map((row, index) => `${(index / (recent.length - 1)) * 100},${98 - ((Number(row.close) - min) / range) * 86}`).join(" ");
  const last = recent.at(-1);
  els.chart.innerHTML = `<svg viewBox="0 0 100 100" role="img" aria-label="最近日线价格走势" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="#1769e0" stroke-width="1.8" vector-effect="non-scaling-stroke"/><line x1="0" y1="98" x2="100" y2="98" stroke="#e4e7eb" stroke-width=".8" vector-effect="non-scaling-stroke"/></svg><div class="muted small">${escapeHtml(recent[0].date)} 至 ${escapeHtml(last.date)} · 收盘 ${formatNumber(last.close)}</div>`;
  const fields = [["MA5", last.MA5], ["MA20", last.MA20], ["MACD", last.MACD], ["RSI", last.RSI], ["KDJ", last.KDJ_J], ["BOLL 中轨", last.BOLL_MID]];
  els.indicators.innerHTML = fields.map(([label, value]) => `<div class="indicator"><span>${label}</span><strong>${formatNumber(value, 4)}</strong></div>`).join("");
}

function renderThesis(thesis, analyses) {
  els.thesisCore.value = thesis?.core_thesis || "";
  els.thesisWatch.value = thesis?.watch_variables || "";
  els.thesisInvalid.value = thesis?.invalid_conditions || "";
  const history = (state.overview?.thesis_history || state.overview?.theses || []).length ? (state.overview.thesis_history || state.overview.theses) : [];
  const rows = history.length ? history : (thesis ? [thesis] : []);
  els.thesisHistory.innerHTML = rows.map((item) => `<div class="history-item"><strong>版本 ${item.version} · ${escapeHtml(item.status || "已确认")}</strong>${escapeHtml(item.core_thesis)}<div class="muted small">${escapeHtml(item.created_at || "")}</div></div>`).join("");
}

function renderSources(events) {
  els.sources.innerHTML = events.length ? events.slice(0, 12).map((event) => `<article class="source-card"><div class="source-meta"><span>${escapeHtml(event.source_type)}</span><span>·</span><span>${escapeHtml(event.published_at || "时间未知")}</span></div><h3><button class="text-button" type="button" data-action="evidence" data-evidence-id="${escapeHtml(event.event_id)}">${escapeHtml(event.title)}</button></h3><p>${escapeHtml(event.source_url || "当前无外部链接，详见站内结构化数据")}</p></article>`).join("") : '<div class="muted small">暂无已保存证据。</div>';
}

async function loadAssets(preferredId = null) {
  const body = await api("/assets");
  state.assets = body.assets || [];
  state.assetId = preferredId || state.assetId || state.assets[0]?.id || null;
  renderAssetSelect();
  if (state.assetId) await loadOverview(state.assetId);
  else renderOverviewShell();
}

async function loadOverview(assetId, path = "") {
  state.assetId = Number(assetId);
  els.loading.hidden = false;
  renderAssetSelect();
  try {
    const overview = await api(`/assets/${state.assetId}/overview${path}`);
    const theses = await api(`/assets/${state.assetId}/theses`).catch(() => ({ history: [] }));
    overview.thesis_history = theses.history || [];
    state.overview = overview;
    state.analysis = state.overview.latest_analysis?.result || null;
    renderOverviewShell();
  } catch (error) {
    state.overview = { asset: selectedAsset(), errors: { overview: error.message }, events: [], messages: [] };
    renderOverviewShell();
    setStatus(error.message, "error");
  } finally {
    els.loading.hidden = true;
  }
}

async function addAsset(code) {
  const normalized = String(code || "").trim();
  if (!normalized) return;
  setStatus("正在添加标的…");
  try {
    const asset = await api("/assets", { method: "POST", body: JSON.stringify({ stock_code: normalized, asset_type: "watchlist" }) });
    closeModal(els.addModal);
    await loadAssets(asset.id);
    setStatus("标的已添加", "success");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function searchStocks() {
  const query = els.stockQuery.value.trim();
  if (!query) return;
  els.searchResults.innerHTML = '<div class="muted small">正在搜索…</div>';
  try {
    const body = await api(`/stocks/search?q=${encodeURIComponent(query)}`);
    els.searchResults.innerHTML = (body.results || []).map((item) => `<div class="search-result"><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.code)}</small></div><button class="button secondary" type="button" data-action="add-search-result" data-code="${escapeHtml(item.code)}">添加</button></div>`).join("") || '<div class="muted small">没有找到匹配标的。可以直接添加六位代码。</div>';
  } catch (error) {
    els.searchResults.innerHTML = `<div class="notice">${escapeHtml(error.message)}。可以直接添加六位代码。</div>`;
  }
}

function openModal(modal) { modal.hidden = false; }
function closeModal(modal) { modal.hidden = true; }

async function openEvidence(id) {
  try {
    const body = await api(`/evidence/${encodeURIComponent(id)}`);
    const evidence = body.evidence;
    els.evidenceDetail.innerHTML = `<div class="source-meta"><span>${escapeHtml(evidence.source_type)}</span><span>·</span><span>${escapeHtml(evidence.source_level)}</span><span>·</span><span>${escapeHtml(evidence.published_at || "时间未知")}</span></div><h3>${escapeHtml(evidence.title)}</h3><p>${escapeHtml(evidence.excerpt || "当前仅保留标题，无法核验正文细节。")}</p>${evidence.source_url ? `<a href="${escapeHtml(evidence.source_url)}" target="_blank" rel="noreferrer">打开原始来源</a>` : ""}<div class="muted small">证据编号：${escapeHtml(evidence.evidence_id)} · 获取于 ${escapeHtml(evidence.fetched_at || "")}</div>`;
    openModal(els.evidenceModal);
  } catch (error) { setStatus(error.message, "error"); }
}

function parseSSEBlock(block) {
  const lines = block.split(/\r?\n/);
  const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
  try { return { event, data: JSON.parse(data || "{}") }; } catch { return { event, data: { message: data } }; }
}

async function stream(path, payload, onEvent) {
  const response = await fetch(`${API_ROOT}${path}`, { method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" }, body: JSON.stringify(payload) });
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
  state.busy = true;
  els.analyzeButton.disabled = true;
  setStatus("正在准备证据…");
  try {
    await stream("/research/stream", { asset_id: state.assetId, event_id: state.selectedEventId }, ({ event, data }) => {
      if (event === "status") setStatus({ context_ready: "证据已准备", model_running: "模型正在分析…", validating: "正在核验引用…" }[data.state] || data.state);
      if (event === "completed") {
        state.analysis = data.result;
        renderAnalysis(data.result);
        setStatus("分析完成", "success");
      }
      if (event === "failed") {
        setStatus(data.message || "分析失败；原始行情和来源仍可查看。", "error");
        renderAnalysis(null);
      }
    });
    await loadOverview(state.assetId);
  } catch (error) { setStatus(error.message, "error"); }
  finally { state.busy = false; els.analyzeButton.disabled = false; }
}

async function runChat(question) {
  if (!state.assetId || state.busy) return;
  state.busy = true;
  setStatus("正在准备追问上下文…");
  try {
    await stream("/chat/stream", { asset_id: state.assetId, event_id: state.selectedEventId, question }, ({ event, data }) => {
      if (event === "status") setStatus({ context_ready: "上下文已准备", model_running: "模型正在回答…", validating: "正在核验引用…" }[data.state] || data.state);
      if (event === "completed") { state.analysis = data.result; renderAnalysis(data.result); setStatus("回答完成", "success"); }
      if (event === "failed") setStatus(data.message || "回答失败；没有生成替代结论。", "error");
    });
    await loadOverview(state.assetId);
  } catch (error) { setStatus(error.message, "error"); }
  finally { state.busy = false; }
}

async function saveThesis(event) {
  event.preventDefault();
  if (!state.assetId || !els.thesisCore.value.trim()) { setStatus("请先填写核心判断", "error"); return; }
  try {
    await api(`/assets/${state.assetId}/theses`, { method: "POST", body: JSON.stringify({ core_thesis: els.thesisCore.value.trim(), watch_variables: els.thesisWatch.value.trim(), invalid_conditions: els.thesisInvalid.value.trim() }) });
    await loadOverview(state.assetId);
    setStatus("已保存新的判断版本", "success");
  } catch (error) { setStatus(error.message, "error"); }
}

async function toggleHolding() {
  const asset = selectedAsset();
  if (!asset) return;
  try {
    await api(`/assets/${asset.id}`, { method: "PATCH", body: JSON.stringify({ asset_type: asset.asset_type === "holding" ? "watchlist" : "holding" }) });
    await loadAssets(asset.id);
  } catch (error) { setStatus(error.message, "error"); }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (action === "open-add") openModal(els.addModal);
  if (action === "select-event") { state.selectedEventId = target.dataset.eventId; renderEvents(state.overview?.events || []); }
  if (action === "evidence") openEvidence(target.dataset.evidenceId);
  if (action === "add-search-result") addAsset(target.dataset.code);
});

els.select.addEventListener("change", () => { if (els.select.value) loadOverview(Number(els.select.value)); });
els.addButton.addEventListener("click", () => openModal(els.addModal));
els.toggleButton.addEventListener("click", toggleHolding);
els.refreshButton.addEventListener("click", async () => {
  if (!state.assetId) return;
  try {
    setStatus("正在刷新行情与事件…");
    await api(`/assets/${state.assetId}/refresh`, { method: "POST" });
    await loadOverview(state.assetId);
    setStatus("刷新完成", "success");
  } catch (error) { setStatus(error.message, "error"); }
});
els.analyzeButton.addEventListener("click", runAnalysis);
els.sourceButton.addEventListener("click", () => { const id = state.selectedEventId; if (id) openEvidence(id); });
els.searchButton.addEventListener("click", searchStocks);
els.addForm.addEventListener("submit", (event) => { event.preventDefault(); addAsset(els.stockQuery.value); });
els.chatForm.addEventListener("submit", (event) => { event.preventDefault(); const question = els.chatInput.value.trim(); if (!question) return; els.chatInput.value = ""; runChat(question); });
els.thesisForm.addEventListener("submit", saveThesis);
document.querySelectorAll(".close-modal").forEach((button) => button.addEventListener("click", () => closeModal(els.addModal)));
document.querySelectorAll(".close-evidence").forEach((button) => button.addEventListener("click", () => closeModal(els.evidenceModal)));
[els.addModal, els.evidenceModal].forEach((modal) => modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(modal); }));
document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeModal(els.addModal); closeModal(els.evidenceModal); } });

loadAssets().catch((error) => setStatus(error.message, "error"));
