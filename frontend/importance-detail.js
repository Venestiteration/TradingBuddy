const LABELS = { public: "公开动态", upstream: "上下游", market: "行情", cross_asset: "跨资产" };

export function dailyImportanceSheet(data, { sheetHeader, escapeHtml }) {
  const cards = (data.categories || []).map((item) => `
    <button class="importance-category-card pressable" type="button"
      data-importance-category="${escapeHtml(item.category)}" data-importance-date="${escapeHtml(data.date)}">
      <span>${LABELS[item.category]}</span><strong>${Math.round(item.score)}</strong>
      <small>${escapeHtml(item.summary || "暂无新信息")}</small>
    </button>`).join("");
  const signals = (data.signals || []).map((signal) => `
    <button class="importance-signal-row pressable" type="button"
      data-importance-category="${escapeHtml(signal.category)}" data-importance-date="${escapeHtml(data.date)}">
      <strong>${escapeHtml(signal.title)}</strong><span>${escapeHtml(signal.summary)}</span></button>`).join("");
  return `${sheetHeader("研究重要性", `${data.date} · ${Math.round(data.composite_score)}`, true)}
    <div class="sheet-body"><div class="importance-category-grid">${cards}</div>
    <section class="detail-section"><span class="detail-eyebrow">当日关键内容</span>
      ${signals || '<p class="muted">暂无新内容，分数来自行情或历史衰减。</p>'}
    </section><button class="secondary-button pressable" type="button" data-add-day-to-thesis="${escapeHtml(data.date)}">用于判断草稿</button></div>`;
}

export function categoryImportanceSheet(data, { sheetHeader, escapeHtml }) {
  const factors = Object.entries(data.factors || {}).map(([name, item]) => `
    <div class="importance-factor"><span>${escapeHtml(name)}</span><strong>${item.score == null ? "—" : Math.round(item.score)}</strong>
      <small>权重 ${Math.round(item.weight * 100)}% · 贡献 ${Number(item.contribution || 0).toFixed(1)}</small></div>`).join("");
  const evidence = (data.evidence || []).map((item) => `
    <button class="importance-evidence-row pressable" type="button" data-source-id="${escapeHtml(item.evidence_id)}">
      <strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.excerpt || "当前仅有标题")}</span></button>`).join("");
  const signal = data.signal;
  const calibration = signal?.calibrated_confidence == null ? "尚未校准" : `${Math.round(signal.calibrated_confidence)} 分`;
  return `${sheetHeader(LABELS[data.category], `${data.date} · ${Math.round(data.score)}`, true)}
    <div class="sheet-body"><div class="importance-formula">公式版本：${escapeHtml(data.formula_version)}</div>
      <div class="importance-factor-list">${factors}</div>
      <section class="detail-section"><span class="detail-eyebrow">证据置信度</span><p>实时置信度：${signal?.factor_scores?.factors?.C == null ? "—" : `${Math.round(signal.factor_scores.factors.C)} 分`} · 事后校准：${calibration}</p></section>
      <section class="detail-section"><span class="detail-eyebrow">内容与证据</span>${evidence || '<p class="muted">暂无新证据；这是基线或衰减值。</p>'}</section></div>`;
}
