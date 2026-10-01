const identity = (value) => String(value ?? "");

function list(items, renderItem, emptyCopy) {
  if (!Array.isArray(items) || !items.length) return `<p class="research-empty-copy">${emptyCopy}</p>`;
  return `<ul>${items.map(renderItem).join("")}</ul>`;
}

function textOf(item) {
  if (typeof item === "string") return item;
  return item?.text || item?.claim || item?.path || item?.body || "";
}

function formatTime(value) {
  if (!value) return "时间未知";
  return String(value).replace("T", " ").slice(0, 16);
}

function statusLabel(status) {
  if (status === "title_only") return "仅标题";
  if (status === "full") return "已读取全文";
  return "已读取摘要";
}

function conflictMarkup(claims, escapeHtml) {
  return `<section class="research-conflicts"><h2>各方陈述 · 尚待核验</h2>${list(claims, (claim) =>
    `<li><strong>${escapeHtml(claim.title || "来源陈述")}</strong>${claim.summary ? `<p>${escapeHtml(claim.summary)}</p>` : ""}${(claim.evidence_ids || []).map((id) => `<button class="research-citation pressable" type="button" data-research-source="${escapeHtml(id)}">查看来源 ${escapeHtml(id)}</button>`).join("")}</li>`,
  "来源存在冲突，请查看原始取证记录，暂不采用任何单方结论。")}</section>`;
}

function safeSourceUrl(value) {
  if (!value) return "";
  try {
    const parsed = new URL(String(value));
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : "";
  } catch {
    return "";
  }
}

function analysisMarkup(analysis, escapeHtml) {
  const result = analysis?.result || analysis;
  if (!result) return "";
  const conclusion = result.core_conclusion || result.conclusion || "AI 未形成额外结论。";
  const facts = result.facts || result.known_facts || [];
  const impactPaths = result.impact_paths || result.inferences || [];
  const unknowns = result.unknowns || [];
  const nextChecks = result.next_checks || result.watch_signals || [];
  return `<div class="research-ai-result">
    <strong>${escapeHtml(conclusion)}</strong>
    ${list(facts, (item) => `<li>${escapeHtml(textOf(item))}</li>`, "")}
    ${impactPaths.length ? `<p><span>影响与推断</span>${escapeHtml(impactPaths.map(textOf).filter(Boolean).join("；"))}</p>` : ""}
    ${unknowns.length ? `<p><span>尚不确定</span>${escapeHtml(unknowns.map(textOf).filter(Boolean).join("；"))}</p>` : ""}
    ${nextChecks.length ? `<p><span>继续核验</span>${escapeHtml(nextChecks.map(textOf).filter(Boolean).join("；"))}</p>` : ""}
    <small>${escapeHtml(result.safety_boundary || "AI 解读是基于现有证据的研究辅助，不构成投资建议。")}</small>
  </div>`;
}

function stateMessage({ loading, error }, escapeHtml) {
  if (loading) {
    return `<article class="message assistant research-brief research-brief-loading" aria-busy="true">
      <div class="assistant-kicker"><span class="status-dot support"></span>每日研究报告</div>
      <div class="research-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>
      <p role="status" aria-live="polite">正在整理最近 24 小时的事件与来源…</p>
    </article>`;
  }
  return `<article class="message assistant research-brief research-brief-error">
    <div class="assistant-kicker"><span class="status-dot uncertain"></span>每日研究报告</div>
    <h1>日报暂时无法生成</h1>
    <p>行情、原始动态和时间线仍可继续查看。</p>
    ${error ? `<p class="research-inline-error" role="status">${escapeHtml(error)}</p>` : ""}
    <div class="message-actions"><button class="secondary-button pressable" type="button" data-sheet="publicDynamics">查看公开动态</button></div>
  </article>`;
}

export function renderResearchBrief(brief, options = {}) {
  const escapeHtml = options.escapeHtml || identity;
  if (!brief) return stateMessage(options, escapeHtml);
  const coverage = brief.coverage || {};
  if (brief.status === "empty") {
    return `<article class="message assistant research-brief research-brief-empty">
      <div class="assistant-kicker"><span class="status-dot support"></span>每日研究报告 · 最近 24 小时</div>
      <h1>最近 24 小时暂无可核验的新事件</h1>
      <p>这只表示已配置的来源在当前窗口内没有新内容，不代表公司没有变化。</p>
      <div class="message-actions"><button class="secondary-button pressable" type="button" data-sheet="publicDynamics">查看公开动态</button></div>
    </article>`;
  }

  const conflict = brief.conflict_status === "possible";
  const aiEnabled = options.aiEnabled === true;
  const claims = brief.conflicting_claims || (brief.events || []).flatMap((event) => event.conflicts || []);
  const disputedClusters = new Set((brief.events || []).filter((event) => event.conflict_status === "possible").map((event) => event.cluster_id));
  const knownFacts = (brief.known_facts || []).filter((fact) => !conflict || (fact.cluster_id && !disputedClusters.has(fact.cluster_id)));
  const aiAnalysis = options.aiAnalysis || null;
  const aiExpanded = options.aiExpanded === true;
  const aiPending = options.aiPending === true;
  const analysisId = "research-brief-ai-daily";
  const sourceButtons = (item) => {
    const ids = Array.isArray(item?.evidence_ids) ? item.evidence_ids : [];
    return ids.map((id) => `<button class="research-citation pressable" type="button" data-research-source="${escapeHtml(id)}">来源 ${escapeHtml(String(id).slice(0, 8))}</button>`).join("");
  };
  return `<article class="message assistant research-brief" data-tour="thesis">
    <div class="assistant-kicker"><span class="status-dot ${conflict ? "uncertain" : "support"}"></span>每日研究报告 · 最近 24 小时</div>
    <div class="research-coverage"><span>${escapeHtml(coverage.event_count ?? brief.events?.length ?? 0)} 个事件簇</span><span>${escapeHtml(coverage.source_count ?? brief.sources?.length ?? 0)} 个来源</span>${conflict ? "<strong>来源存在差异</strong>" : ""}</div>
    <section class="research-primary" data-tour="dynamic"><span>今天真正发生了什么</span><h1>${escapeHtml(conflict ? "来源陈述存在冲突，尚不能确认一致结论。" : brief.core_conclusion || "暂无可确认结论")}</h1></section>
    <div class="research-brief-grid">
      <section><h2>已知事实</h2>${list(knownFacts, (item) => `<li><span>${escapeHtml(textOf(item))}</span>${sourceButtons(item)}</li>`, "暂无可核验事实。")}</section>
      ${conflict ? conflictMarkup(claims, escapeHtml) : ""}
      <section><h2>为什么重要</h2>${list(brief.why_it_matters, (item) => `<li>${escapeHtml(textOf(item))}</li>`, "现有信息不足以形成重要性判断。")}</section>
      <section><h2>影响路径</h2>${list(brief.impact_paths, (item) => `<li>${escapeHtml(textOf(item))}</li>`, "暂无可核验的影响路径。")}</section>
      <section><h2>还有什么不确定</h2>${list(brief.unknowns, (item) => `<li>${escapeHtml(textOf(item))}</li>`, "暂无额外不确定项。")}</section>
      <section class="research-watch"><h2>接下来看什么</h2>${list(brief.watch_signals, (item) => `<li>${escapeHtml(textOf(item))}</li>`, "等待后续权威披露。")}</section>
    </div>
    <div class="message-actions research-brief-actions">
      <button class="secondary-button pressable" type="button" data-sheet="publicDynamics">查看来源与公开动态</button>
      ${aiEnabled ? `<button class="text-button pressable" type="button" data-research-ai="" aria-expanded="${aiExpanded}" aria-controls="${analysisId}">${aiPending ? "AI 正在解读…" : aiExpanded ? "收起 AI 解读" : "展开 AI 解读"}</button>` : ""}
    </div>
    ${aiEnabled ? `<div id="${analysisId}" class="research-ai-panel" ${aiExpanded ? "" : "hidden"} aria-live="polite">
      ${aiPending ? '<div class="research-ai-pending" role="status">AI 正在基于当前证据生成解读…</div>' : ""}
      ${options.aiError ? `<div class="research-inline-error" role="status">AI 解读暂时失败：${escapeHtml(options.aiError)}。确定性日报和来源仍可使用。</div>` : ""}
      ${analysisMarkup(aiAnalysis, escapeHtml)}
    </div>` : ""}
  </article>`;
}

function sourceMarkup(source, escapeHtml) {
  const evidenceId = source.evidence_id || "";
  const url = safeSourceUrl(source.source_url);
  return `<li class="research-source-item">
    <div><strong>${escapeHtml(source.title || "未命名来源")}</strong><span>${escapeHtml(formatTime(source.published_at))} · ${escapeHtml(statusLabel(source.content_status))}</span></div>
    <div class="research-source-actions">
      ${evidenceId ? `<button class="text-button pressable" type="button" data-research-source="${escapeHtml(evidenceId)}">查看取证记录</button>` : ""}
      ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开原文</a>` : '<span class="research-source-unavailable">来源地址暂不可用</span>'}
    </div>
  </li>`;
}

export function renderResearchEvents(events, options = {}) {
  const escapeHtml = options.escapeHtml || identity;
  if (options.loading) return '<div class="research-events-loading" role="status" aria-live="polite">正在读取事件簇与来源…</div>';
  if (options.error) return `<div class="research-inline-error" role="status">${escapeHtml(options.error)}</div>`;
  if (!Array.isArray(events) || !events.length) return '<p class="research-events-empty">最近 24 小时没有可展开的公开事件。</p>';
  return `<div class="research-events" aria-live="polite">${events.map((event) => {
    const clusterId = String(event.cluster_id || "");
    const expanded = clusterId === String(options.expandedClusterId || "");
    const controlId = `research-cluster-${clusterId.replace(/[^a-zA-Z0-9_-]/g, "-") || "unknown"}`;
    const evidence = Array.isArray(event.evidence) ? event.evidence : [];
    const aiAnalysis = options.analysisByCluster?.[clusterId] || null;
    const aiError = options.aiErrorByCluster?.[clusterId] || "";
    const aiPending = options.aiPendingClusterId === clusterId;
    const aiExpanded = Boolean(aiAnalysis || aiPending || aiError);
    return `<article class="research-event-card${expanded ? " is-expanded" : ""}" data-research-cluster="${escapeHtml(clusterId)}">
      <div class="research-event-meta"><time>${escapeHtml(formatTime(event.published_at))}</time><span>${escapeHtml(statusLabel(event.content_status))}</span>${event.conflict_status === "possible" ? "<strong>来源存在差异</strong>" : ""}</div>
      <h3>${escapeHtml(event.conflict_status === "possible" ? "来源陈述存在冲突" : event.title || "未命名事件")}</h3>
      <p class="research-event-summary">${escapeHtml(event.conflict_status === "possible" ? "各方陈述尚未统一，请对照来源核验。" : event.summary || (event.content_status === "title_only" ? "当前仅有标题，暂无可核验正文。" : "暂无摘要。"))}</p>
      ${event.conflict_status === "possible" ? conflictMarkup(event.conflicts || [], escapeHtml) : ""}
      <button class="research-disclosure pressable" type="button" data-research-expand="${escapeHtml(clusterId)}" aria-expanded="${expanded}" aria-controls="${controlId}">
        <span>${escapeHtml(event.source_count ?? evidence.length)} 个来源</span><span>${expanded ? "收起" : "查看来源"}</span>
      </button>
      <div class="research-event-disclosure" id="${controlId}" ${expanded ? "" : "hidden"}>
        ${options.detailLoadingClusterId === clusterId ? '<div class="research-events-loading" role="status">正在更新事件详情…</div>' : ""}
        ${options.detailErrorByCluster?.[clusterId] ? `<div class="research-inline-error" role="status">${escapeHtml(options.detailErrorByCluster[clusterId])}</div>` : ""}
        <h4>来源与追溯</h4>
        ${evidence.length ? `<ul class="research-source-list">${evidence.map((source) => sourceMarkup(source, escapeHtml)).join("")}</ul>` : '<p class="research-source-unavailable">暂无可用的取证记录或原文链接。</p>'}
        ${options.aiEnabled === true ? `<div class="research-cluster-ai">
          <button class="secondary-button pressable" type="button" data-research-ai="${escapeHtml(clusterId)}" aria-expanded="${aiExpanded}" aria-controls="${controlId}-ai">${aiPending ? "AI 正在解读…" : aiAnalysis ? "重新生成 AI 解读" : "展开 AI 解读"}</button>
          <div id="${controlId}-ai" ${aiExpanded ? "" : "hidden"} aria-live="polite">
            ${aiPending ? '<div class="research-ai-pending" role="status">正在基于该事件簇生成解读…</div>' : ""}
            ${aiError ? `<div class="research-inline-error" role="status">AI 解读暂时失败：${escapeHtml(aiError)}。事件摘要、证据与原文链接仍可使用。</div>` : ""}
            ${analysisMarkup(aiAnalysis, escapeHtml)}
          </div>
        </div>` : ""}
      </div>
    </article>`;
  }).join("")}</div>`;
}

export function bindResearchBrief(container, handlers = {}) {
  if (!container?.addEventListener) return () => {};
  const onClick = (event) => {
    const expand = event.target?.closest?.("[data-research-expand]");
    if (expand) {
      handlers.onExpand?.(expand.getAttribute("data-research-expand"), expand);
      return;
    }
    const source = event.target?.closest?.("[data-research-source]");
    if (source) {
      handlers.onSource?.(source.getAttribute("data-research-source"), source);
      return;
    }
    const ai = event.target?.closest?.("[data-research-ai]");
    if (ai) handlers.onAI?.(ai.getAttribute("data-research-ai") || null, ai);
  };
  container.addEventListener("click", onClick);
  return () => container.removeEventListener("click", onClick);
}
