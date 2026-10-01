import { renderResearchEvents } from "./research-brief.js";

const KIND_LABELS = { announcement: "官方", news: "媒体" };

function statusCopy(status) {
  const current = status?.status || status?.last_status;
  if (current === "complete") return "本次采集通道完整";
  if (current === "partial") return "部分来源更新失败";
  return "当前展示本地缓存";
}

function researchCounts(events) {
  return {
    all: events.length,
    official: events.filter((item) => item.kinds?.includes("announcement")).length,
    media: events.filter((item) => item.kinds?.includes("news")).length,
  };
}

function filteredResearchEvents(events, kind) {
  if (kind === "official") return events.filter((item) => item.kinds?.includes("announcement"));
  if (kind === "media") return events.filter((item) => item.kinds?.includes("news"));
  return events;
}

export function publicDynamicsSheet(data, {
  sheetHeader,
  escapeHtml,
  aiEnabled = false,
  activeKind = "all",
  expandedClusterId = null,
  analysisByCluster = {},
  aiPendingClusterId = null,
  aiErrorByCluster = {},
  detailLoadingClusterId = null,
  detailErrorByCluster = {},
} = {}) {
  if (Array.isArray(data.events)) {
    const counts = researchCounts(data.events);
    const events = filteredResearchEvents(data.events, activeKind);
    const window = data.window || {};
    return `${sheetHeader("公开动态", "最近 24 小时", true)}
      <div class="sheet-body research-events-sheet">
        <div class="public-source-status"><strong>${data.status === "degraded" ? "部分来源存在差异" : "已按事件合并重复报道"}</strong>
          <span>${escapeHtml(window.start || "")} ${window.end ? `—${escapeHtml(window.end)}` : ""}</span></div>
        <div class="public-dynamics-counts"><span><strong>${escapeHtml(counts.all)}</strong>全部</span>
          <span><strong>${escapeHtml(counts.official)}</strong>官方</span><span><strong>${escapeHtml(counts.media)}</strong>媒体</span></div>
        <div class="public-kind-tabs">
          <button type="button" class="${activeKind === "all" ? "is-active" : ""}" data-public-kind="all">全部 ${escapeHtml(counts.all)}</button>
          <button type="button" class="${activeKind === "official" ? "is-active" : ""}" data-public-kind="official">官方 ${escapeHtml(counts.official)}</button>
          <button type="button" class="${activeKind === "media" ? "is-active" : ""}" data-public-kind="media">媒体 ${escapeHtml(counts.media)}</button>
        </div>
        ${renderResearchEvents(events, {
          escapeHtml,
          aiEnabled,
          expandedClusterId,
          analysisByCluster,
          aiPendingClusterId,
          aiErrorByCluster,
          detailLoadingClusterId,
          detailErrorByCluster,
        })}
        <p class="public-completeness-note">事件簇会合并重复报道；完整仅表示已配置通道本次成功，并非覆盖互联网全部信息。</p>
      </div>`;
  }
  const counts = data.counts || { all: 0, official: 0, media: 0 };
  const items = (data.items || []).map((item) => `
    <button class="public-dynamic-item pressable" type="button"
      data-public-dynamic-id="${escapeHtml(item.id)}">
      <span class="public-kind public-kind-${escapeHtml(item.kind)}">${escapeHtml(KIND_LABELS[item.kind] || item.kind)}</span>
      <time>${escapeHtml(item.published_at)}</time>
      <strong>${escapeHtml(item.canonical_title)}</strong>
      <span>${escapeHtml(item.summary || "当前仅有标题")}</span>
      <small>${escapeHtml(String(item.source_count ?? item.evidence_count ?? 1))} 个来源 · ${escapeHtml(item.content_status)} · 重要性 ${Math.round(item.importance_score)}</small>
    </button>`).join("");
  return `${sheetHeader("公开动态", "最近 24 小时", true)}
    <div class="sheet-body">
      <div class="public-source-status"><strong>${escapeHtml(statusCopy(data.source_status))}</strong>
        <span>${escapeHtml(data.window_start)}—${escapeHtml(data.window_end)}</span></div>
      <div class="public-dynamics-counts"><span><strong>${escapeHtml(counts.all)}</strong>全部</span>
        <span><strong>${escapeHtml(counts.official)}</strong>官方</span><span><strong>${escapeHtml(counts.media)}</strong>媒体</span></div>
      <div class="public-kind-tabs">
        <button type="button" class="${activeKind === "all" ? "is-active" : ""}" data-public-kind="all">全部 ${escapeHtml(counts.all)}</button>
        <button type="button" class="${activeKind === "official" ? "is-active" : ""}" data-public-kind="official">官方 ${escapeHtml(counts.official)}</button>
        <button type="button" class="${activeKind === "media" ? "is-active" : ""}" data-public-kind="media">媒体 ${escapeHtml(counts.media)}</button>
      </div>
      <div class="public-dynamics-list">${items || '<p class="muted">最近 24 小时没有采集到相关动态。</p>'}</div>
      <p class="public-completeness-note">完整表示已配置通道本次成功，并非覆盖互联网全部信息。</p>
    </div>`;
}

export function publicDynamicDetailSheet(data, { sheetHeader, escapeHtml, aiEnabled = false }) {
  const item = data.dynamic;
  const sources = (item.evidence || []).map((source) => `
    <button type="button" class="public-source-row pressable" data-source-id="${escapeHtml(source.evidence_id)}">
      <strong>${escapeHtml(source.raw?.publisher || source.title)}</strong>
      <span>${escapeHtml(source.content_status)} · ${escapeHtml(source.published_at || source.fetched_at)}</span>
    </button>`).join("");
  return `${sheetHeader("动态详情", KIND_LABELS[item.kind] || item.kind, true)}
    <div class="sheet-body"><span class="detail-eyebrow">${escapeHtml(item.category)}</span>
      <h2>${escapeHtml(item.canonical_title)}</h2><p>${escapeHtml(item.summary || "当前仅有标题")}</p>
      <section class="detail-section"><span class="detail-eyebrow">来源与追溯</span>${sources}</section>
      <section class="detail-section"><span class="detail-eyebrow">重要性依据</span>
        <p>分数表示研究注意力，不代表利好或利空。</p></section>
      <div class="button-row">
        ${item.kind === "announcement" && item.content_status !== "full" ? `<button class="secondary-button" type="button" data-extract-dynamic="${escapeHtml(item.id)}">读取公告正文</button>` : ""}
        ${aiEnabled ? `<button class="primary-button" type="button" data-analyze-dynamic="${escapeHtml(item.id)}">基于此动态分析</button>` : ""}
      </div></div>`;
}
