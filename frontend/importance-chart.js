const COLORS = {
  public: "#0071e3",
  upstream: "#ff9f0a",
  market: "#af52de",
  cross_asset: "#00a6a6",
};

const LABELS = {
  public: "公开动态",
  upstream: "上下游",
  market: "行情",
  cross_asset: "跨资产",
};

export function renderImportanceChart(rows, { escapeHtml }) {
  if (!rows.length) return '<div class="importance-empty">暂时没有可计算的时间线。</div>';
  const xAt = (index) => 42 + index * (690 / Math.max(rows.length - 1, 1));
  const yAt = (score) => 190 - Number(score) * 1.5;
  const segments = [];
  let segment = [];
  rows.forEach((row, index) => {
    if (row.status === "incomplete" || row.composite_score == null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else {
      segment.push(`${xAt(index)},${yAt(row.composite_score)}`);
    }
  });
  if (segment.length) segments.push(segment);
  const paths = segments.map((points) =>
    `<polyline class="importance-line" points="${points.join(" ")}" />`
  ).join("");
  const nodes = rows.map((row, index) => {
    if (row.status === "incomplete" || row.composite_score == null) return "";
    const label = `${row.date}，综合重要性 ${Math.round(row.composite_score)}，主导类别 ${LABELS[row.dominant_category] || "暂无"}`;
    return `<circle class="importance-node ${row.status === "cached" ? "is-cached" : ""}"
      cx="${xAt(index)}" cy="${yAt(row.composite_score)}" r="5"
      fill="${COLORS[row.dominant_category] || "#1d1d1f"}" role="button" tabindex="0"
      aria-label="${escapeHtml(label)}" data-importance-day="${escapeHtml(row.date)}" />`;
  }).join("");
  return `<section class="importance-timeline" aria-label="研究重要性时间线">
    <div class="importance-heading"><div><span>研究重要性</span><strong>最近 ${rows.length} 个交易日</strong></div>
      <div class="period-control"><button type="button" data-importance-days="30">30 日</button>
        <button type="button" data-importance-days="90">90 日</button></div>
      <div class="importance-legend">${Object.entries(LABELS).map(([key, label]) =>
        `<span><i style="background:${COLORS[key]}"></i>${label}</span>`).join("")}</div></div>
    <div class="importance-chart-wrap"><svg viewBox="0 0 760 230" role="img" aria-label="每日综合重要性折线">
      <line class="importance-grid" x1="42" y1="40" x2="732" y2="40" />
      <line class="importance-grid" x1="42" y1="115" x2="732" y2="115" />
      <line class="importance-grid" x1="42" y1="190" x2="732" y2="190" />
      ${paths}${nodes}</svg><div class="importance-tooltip" hidden></div></div>
  </section>`;
}

export function bindImportanceChart(container, { rows, onOpen, onRange, escapeHtml }) {
  const tooltip = container.querySelector(".importance-tooltip");
  const show = (node) => {
    const row = rows.find((item) => item.date === node.dataset.importanceDay);
    if (!row || !tooltip) return;
    tooltip.innerHTML = `<strong>${escapeHtml(row.date)} · ${Math.round(row.composite_score)}</strong>
      <span>${escapeHtml(row.summary || "暂无新信息")}</span>
      <small>${Object.entries(row.category_scores || {}).map(([key, value]) =>
        `${LABELS[key]} ${Math.round(value)}`).join(" · ")}</small>`;
    tooltip.hidden = false;
  };
  const hide = () => { if (tooltip) tooltip.hidden = true; };
  const click = (event) => {
    const range = event.target.closest("[data-importance-days]");
    if (range) {
      onRange(Number(range.dataset.importanceDays));
      return;
    }
    const node = event.target.closest("[data-importance-day]");
    if (node) onOpen(node.dataset.importanceDay, node);
  };
  const keydown = (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-importance-day]")) {
      event.preventDefault();
      onOpen(event.target.dataset.importanceDay, event.target);
    }
  };
  container.addEventListener("mouseover", (event) => {
    const node = event.target.closest("[data-importance-day]");
    if (node) show(node);
  });
  container.addEventListener("focusin", (event) => {
    const node = event.target.closest("[data-importance-day]");
    if (node) show(node);
  });
  container.addEventListener("mouseleave", hide);
  container.addEventListener("focusout", hide);
  container.addEventListener("click", click);
  container.addEventListener("keydown", keydown);
  return () => {
    container.removeEventListener("click", click);
    container.removeEventListener("keydown", keydown);
  };
}
