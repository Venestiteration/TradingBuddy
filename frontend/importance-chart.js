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

const CHART_LEFT = 42;
const CHART_RIGHT = 732;
const CHART_WIDTH = CHART_RIGHT - CHART_LEFT;
const MIN_IMPORTANCE_ROWS = 7;
const MAX_IMPORTANCE_ROWS = 90;

// Kept as a compatibility hook for older callers. The range controls themselves
// are intentionally no longer rendered; the timeline is now continuously zoomed.
const LEGACY_RANGE_ATTRIBUTE = "data-importance-days";

const finiteNumber = (value, fallback) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};

const normalizeTotal = (total) => Math.max(0, Math.floor(finiteNumber(total, 0)));

const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

const normalizedViewport = (viewport, total = viewport?.total) => {
  const normalizedTotal = normalizeTotal(total);
  const defaultMinVisible = Math.min(MIN_IMPORTANCE_ROWS, normalizedTotal);
  const minVisible = clamp(
    finiteNumber(viewport?.minVisible, defaultMinVisible),
    0,
    normalizedTotal,
  );
  const defaultStart = Math.max(0, normalizedTotal - minVisible);
  const start = clamp(finiteNumber(viewport?.start, defaultStart), 0, normalizedTotal);
  const end = clamp(finiteNumber(viewport?.end, normalizedTotal), start, normalizedTotal);
  return {
    start,
    end,
    minVisible,
    total: normalizedTotal,
  };
};

export function createImportanceViewport(total, initialVisible = 30) {
  const normalizedTotal = normalizeTotal(total);
  const minVisible = Math.min(MIN_IMPORTANCE_ROWS, normalizedTotal);
  const visible = clamp(
    finiteNumber(initialVisible, Math.min(30, normalizedTotal)),
    minVisible,
    normalizedTotal,
  );
  return {
    start: normalizedTotal - visible,
    end: normalizedTotal,
    minVisible,
    total: normalizedTotal,
  };
}

export function zoomImportanceViewport(viewport, scale, anchorRatio) {
  const current = normalizedViewport(viewport);
  const span = current.end - current.start;
  const ratio = clamp(finiteNumber(anchorRatio, 0.5), 0, 1);
  const multiplier = Math.max(0.01, finiteNumber(scale, 1));
  const nextSpan = clamp(span * multiplier, current.minVisible, current.total);
  const anchor = current.start + ratio * span;
  let start = anchor - ratio * nextSpan;
  let end = start + nextSpan;
  if (start < 0) {
    end -= start;
    start = 0;
  }
  if (end > current.total) {
    start -= end - current.total;
    end = current.total;
  }
  return {
    start: clamp(start, 0, current.total),
    end: clamp(end, 0, current.total),
    minVisible: current.minVisible,
    total: current.total,
  };
}

export function panImportanceViewport(viewport, deltaRows) {
  const current = normalizedViewport(viewport);
  const span = current.end - current.start;
  const maxStart = Math.max(0, current.total - span);
  const start = clamp(current.start + finiteNumber(deltaRows, 0), 0, maxStart);
  return {
    start,
    end: start + span,
    minVisible: current.minVisible,
    total: current.total,
  };
}

export function visibleImportanceRows(rows, viewport) {
  if (!Array.isArray(rows) || !rows.length) return [];
  const current = normalizedViewport(viewport, rows.length);
  const start = clamp(Math.floor(current.start), 0, rows.length);
  const end = clamp(Math.ceil(current.end), start, rows.length);
  return rows.slice(start, end);
}

const chartEscape = (escapeHtml) =>
  typeof escapeHtml === "function" ? escapeHtml : (value) => String(value);

export function renderImportanceChart(rows, { escapeHtml, viewport } = {}) {
  if (!rows.length) return '<div class="importance-empty">暂时没有可计算的时间线。</div>';

  const encode = chartEscape(escapeHtml);
  const current = normalizedViewport(viewport || createImportanceViewport(rows.length), rows.length);
  const visibleRows = visibleImportanceRows(rows, current);
  const startIndex = clamp(Math.floor(current.start), 0, rows.length);
  const entries = visibleRows.map((row, offset) => ({
    row,
    index: startIndex + offset,
    offset,
  }));
  const span = Math.max(current.end - current.start, 1);
  // Viewport edges describe the first and last visible data points, while `end`
  // remains exclusive for slicing and viewport transforms.
  const pointSpan = Math.max(span - 1, 1);
  const xAt = (index) => clamp(
    CHART_LEFT + ((index - current.start) / pointSpan) * CHART_WIDTH,
    CHART_LEFT,
    CHART_RIGHT,
  );
  const yAt = (score) => 190 - Number(score) * 1.5;
  const radius = clamp(
    6 - ((span - MIN_IMPORTANCE_ROWS) / (MAX_IMPORTANCE_ROWS - MIN_IMPORTANCE_ROWS)) * 3,
    3,
    6,
  );
  const labelStride = Math.max(1, Math.ceil(span / 8));
  const segments = [];
  let segment = [];
  entries.forEach(({ row, index }) => {
    if (row.status === "incomplete" || row.composite_score == null || Number.isNaN(Number(row.composite_score))) {
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
  const nodes = entries.map(({ row, index }) => {
    if (row.status === "incomplete" || row.composite_score == null || Number.isNaN(Number(row.composite_score))) return "";
    const label = `${row.date}，综合重要性 ${Math.round(row.composite_score)}，主导类别 ${LABELS[row.dominant_category] || "暂无"}`;
    return `<circle class="importance-node ${row.status === "cached" ? "is-cached" : ""}"
      cx="${xAt(index)}" cy="${yAt(row.composite_score)}" r="${radius}"
      fill="${COLORS[row.dominant_category] || "#1d1d1f"}" role="button" tabindex="0"
      aria-label="${encode(label)}" data-importance-day="${encode(row.date)}" />`;
  }).join("");
  const dateLabels = entries.map(({ row, index, offset }) => {
    if (offset % labelStride !== 0) return "";
    return `<text class="importance-date-label" x="${xAt(index)}" y="218" text-anchor="middle">${encode(row.date)}</text>`;
  }).join("");
  const firstVisible = visibleRows[0]?.date || rows[0].date;
  const lastVisible = visibleRows.at(-1)?.date || rows.at(-1).date;
  const loadedFirst = rows[0].date;
  const loadedLast = rows.at(-1).date;
  const chartLabel = `研究重要性时间线，显示 ${firstVisible} 至 ${lastVisible}，已加载边界 ${loadedFirst} 至 ${loadedLast}`;
  return `<section class="importance-timeline" aria-label="研究重要性时间线">
    <div class="importance-heading"><div><span>研究重要性</span><strong>显示 ${Math.round(span)} / 已加载 ${rows.length} 个交易日</strong></div>
      <div class="chart-controls" aria-label="时间线缩放控制">
        <button type="button" data-chart-action="zoom-out" aria-label="缩小时间线">−</button>
        <button type="button" data-chart-action="zoom-in" aria-label="放大时间线">＋</button>
        <button type="button" data-chart-action="reset" aria-label="重置时间线">重置</button>
      </div>
      <div class="importance-legend">${Object.entries(LABELS).map(([key, label]) =>
        `<span><i style="background:${COLORS[key]}"></i>${label}</span>`).join("")}</div></div>
    <div class="importance-chart-wrap"><svg viewBox="0 0 760 230" role="img" aria-label="${encode(chartLabel)}">
      <line class="importance-grid" x1="42" y1="40" x2="732" y2="40" />
      <line class="importance-grid" x1="42" y1="115" x2="732" y2="115" />
      <line class="importance-grid" x1="42" y1="190" x2="732" y2="190" />
      ${paths}${nodes}${dateLabels}</svg><div class="importance-tooltip" hidden></div></div>
  </section>`;
}

export function bindImportanceChart(
  container,
  { rows, viewport, onOpen, onRange, onViewport, onBoundary, escapeHtml },
) {
  const tooltip = container.querySelector(".importance-tooltip");
  let currentViewport = viewport || createImportanceViewport(rows.length);
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
  const sameViewport = (left, right) => left.start === right.start
    && left.end === right.end && left.total === right.total;
  const chartAction = (action) => {
    const previousViewport = currentViewport;
    let nextViewport;
    if (action === "zoom-in") {
      nextViewport = zoomImportanceViewport(currentViewport, 0.5, 0.5);
    } else if (action === "zoom-out") {
      nextViewport = zoomImportanceViewport(currentViewport, 2, 0.5);
    } else if (action === "reset") {
      nextViewport = createImportanceViewport(currentViewport.total);
    }
    if (!nextViewport) return;
    currentViewport = nextViewport;
    if (action === "reset" || !sameViewport(nextViewport, previousViewport)) {
      onViewport?.(nextViewport, action);
    } else {
      onBoundary?.(action, nextViewport);
    }
  };
  const click = (event) => {
    const action = event.target.closest("[data-chart-action]");
    if (action) {
      chartAction(action.dataset.chartAction);
      return;
    }
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
