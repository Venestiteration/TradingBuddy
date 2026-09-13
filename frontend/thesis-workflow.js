const changeLabels = {
  added: "新增",
  modified: "修改",
  removed: "删除",
  unchanged: "保持",
};

function checked(values, value) {
  return (values || []).some((item) => String(item) === String(value));
}

export function thesisContextSheet(model, { sheetHeader, escapeHtml }) {
  const messages = (model.messages || []).map((item) => `
    <label class="thesis-scope-row"><input type="checkbox" data-thesis-message value="${item.id}"
      ${checked(model.selected_message_ids, item.id) ? "checked" : ""}>
      <span><strong>${item.role === "user" ? "我" : "AI"}</strong>${escapeHtml(item.content)}</span></label>`).join("");
  const evidence = (model.evidence || []).map((item) => `
    <label class="thesis-scope-row"><input type="checkbox" data-thesis-evidence
      value="${escapeHtml(item.evidence_id)}" ${checked(model.selected_evidence_ids, item.evidence_id) ? "checked" : ""}>
      <span><strong>证据</strong>${escapeHtml(item.title)}</span></label>`).join("");
  return `${sheetHeader("维护我的判断", `基于 v${model.base_version || 0}`, true)}<div class="sheet-body">
    <div class="thesis-scope-summary">已选择 ${(model.selected_message_ids || []).length} 条对话 · ${(model.selected_evidence_ids || []).length} 条证据</div>
    <section class="detail-section"><span class="detail-eyebrow">对话范围</span>${messages || '<p class="muted">暂无可选对话。</p>'}</section>
    <section class="detail-section"><span class="detail-eyebrow">证据范围</span>${evidence || '<p class="muted">暂无可选证据。</p>'}</section>
    <button class="primary-button pressable" type="button" data-generate-thesis-draft>生成判断草稿</button></div>`;
}

function suggestionPreview(draft, field, escapeHtml) {
  const value = suggestionValue(draft, field);
  if (!value) return '<p class="muted thesis-suggestion">AI 暂未提出可采纳的修改。</p>';
  const source = draft.ai_suggestion?.[field === "core_thesis" ? "core_thesis" : field];
  const type = Array.isArray(source) ? source.map((item) => changeLabels[item.change_type] || item.change_type).join("、") : changeLabels[source?.change_type] || "建议";
  return `<div class="thesis-suggestion"><span>AI 建议 · ${escapeHtml(type)}</span><p>${escapeHtml(value)}</p></div>`;
}

export function thesisReviewSheet(model, { sheetHeader, escapeHtml }) {
  const value = (field) => escapeHtml(model.user_content?.[field] || "");
  return `${sheetHeader("维护我的判断", "AI 整理的修改建议", true)}<div class="sheet-body">
    <div class="archive-tabs"><button class="archive-tab" aria-selected="true">待确认草稿</button>
      <button class="archive-tab" type="button" data-thesis-history>历史记录</button></div>
    <p class="notice">AI 只整理变化，不会自动改写已确认判断。请逐项采纳或手动修改，最后确认保存。</p>
    <form id="thesis-draft-form" class="sheet-form">
      <label>核心判断<textarea name="core_thesis" required>${value("core_thesis")}</textarea>
        ${suggestionPreview(model, "core_thesis", escapeHtml)}
        <button type="button" class="text-button" data-accept-thesis-field="core_thesis">采纳修改</button></label>
      <label>重点观察<textarea name="watch_variables">${value("watch_variables")}</textarea>
        ${suggestionPreview(model, "watch_variables", escapeHtml)}
        <button type="button" class="text-button" data-accept-thesis-field="watch_variables">采纳修改</button></label>
      <label>判断失效条件<textarea name="invalid_conditions">${value("invalid_conditions")}</textarea>
        ${suggestionPreview(model, "invalid_conditions", escapeHtml)}
        <button type="button" class="text-button" data-accept-thesis-field="invalid_conditions">采纳修改</button></label>
      <button class="primary-button pressable" type="submit" data-confirm-thesis-version>确认并保存为 v${Number(model.base_version || 0) + 1}</button>
    </form></div>`;
}

export function thesisHistorySheet(history, { sheetHeader, escapeHtml }) {
  const items = (history || []).map((item) => `<article class="history-item"><strong>v${item.version} · ${escapeHtml(String(item.created_at || "").slice(0, 10))}</strong>
      <p>${escapeHtml(item.core_thesis)}</p><small>${item.creation_method === "ai_assisted" ? "AI 辅助整理" : "手动编辑"}</small>
      ${item.change_summary ? `<span class="history-change">已记录结构化变化</span>` : ""}</article>`).join("");
  return `${sheetHeader("判断历史", "结构化版本", true)}<div class="sheet-body history-list">
    ${items || '<div class="uncertainty-callout"><strong>还没有判断历史</strong><p>确认第一版判断后，版本记录会显示在这里。</p></div>'}</div>`;
}

export function collectThesisForm(root) {
  const form = new FormData(root);
  return {
    core_thesis: String(form.get("core_thesis") || "").trim(),
    watch_variables: String(form.get("watch_variables") || "").trim(),
    invalid_conditions: String(form.get("invalid_conditions") || "").trim(),
  };
}

export function suggestionValue(draft, field) {
  const suggestion = draft?.ai_suggestion || {};
  if (field === "core_thesis") return suggestion.core_thesis?.suggested_text || "";
  return (suggestion[field] || [])
    .filter((item) => item.change_type !== "removed" && !item.insufficient_basis)
    .map((item) => item.text)
    .filter(Boolean)
    .join("\n");
}
