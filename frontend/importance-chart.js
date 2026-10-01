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
  })).filter(({ index }) => {
    const center = index + 0.5;
    return center >= current.start && center <= current.end;
  });
  const span = Math.max(current.end - current.start, 1);
  // Rows are unit-width bins. Their centers are mapped against the fractional
  // viewport boundaries, so edge rows remain inside without hiding an overflow.
  const xAt = (index) => CHART_LEFT + (((index + 0.5) - current.start) / span) * CHART_WIDTH;
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
    <div class="importance-chart-wrap"><svg viewBox="0 0 760 230" role="img" tabindex="0" aria-label="${encode(chartLabel)}">
      <line class="importance-grid" x1="42" y1="40" x2="732" y2="40" />
      <line class="importance-grid" x1="42" y1="115" x2="732" y2="115" />
      <line class="importance-grid" x1="42" y1="190" x2="732" y2="190" />
      ${paths}${nodes}${dateLabels}</svg><div class="importance-tooltip" hidden></div><div class="importance-live-region" aria-live="polite" aria-atomic="true"></div></div>
  </section>`;
}

export function bindImportanceChart(
  container,
  { rows, viewport, onOpen, onRange, onViewport, onBoundary, escapeHtml },
) {
  rows = Array.isArray(rows) ? rows : [];
  const tooltip = container.querySelector(".importance-tooltip");
  const plotSurface = container.querySelector(".importance-chart-wrap") || container;
  const liveRegion = container.querySelector(".importance-live-region");
  const viewportTotal = rows.length || viewport?.total || 0;
  let currentViewport = normalizedViewport(viewport || createImportanceViewport(viewportTotal), viewportTotal);
  const activePointers = new Map();
  let primaryPointerId = null;
  let dragging = false;
  let dragLastX = 0;
  let dragLastY = 0;
  let pinchStartDistance = 0;
  let pinchStartMidpoint = null;
  let pinchStartViewport = null;

  const plotRect = () => {
    const rect = plotSurface?.getBoundingClientRect?.();
    return {
      left: finiteNumber(rect?.left, 0),
      top: finiteNumber(rect?.top, 0),
      width: Math.max(1, finiteNumber(rect?.width, CHART_WIDTH)),
      height: Math.max(1, finiteNumber(rect?.height, 230)),
    };
  };
  const sameViewport = (left, right) => left.start === right.start
    && left.end === right.end && left.total === right.total;
  const announce = () => {
    if (!liveRegion || !rows.length) return;
    const visible = visibleImportanceRows(rows, currentViewport);
    const first = visible[0]?.date || rows[0].date;
    const last = visible.at(-1)?.date || rows.at(-1).date;
    liveRegion.textContent = `显示 ${first} 至 ${last}，已加载 ${rows[0].date} 至 ${rows.at(-1).date}`;
  };
  const setDragging = (value) => {
    dragging = value;
    plotSurface?.classList?.toggle?.("is-dragging", value);
  };
  const boundaryDirection = (start, end) => {
    if (start < 0) return "start";
    if (end > currentViewport.total) return "end";
    return null;
  };
  const publish = (nextViewport, action, boundary = null) => {
    const previous = currentViewport;
    currentViewport = nextViewport;
    announce();
    if (!sameViewport(nextViewport, previous) || action === "reset") onViewport?.(nextViewport, action);
    if (boundary) onBoundary?.(boundary);
  };
  const applyZoom = (scale, anchorRatio, action, baseViewport = currentViewport) => {
    const current = baseViewport;
    const span = current.end - current.start;
    const ratio = clamp(finiteNumber(anchorRatio, 0.5), 0, 1);
    const nextSpan = clamp(span * Math.max(0.01, finiteNumber(scale, 1)), current.minVisible, current.total);
    const anchor = current.start + ratio * span;
    const rawStart = anchor - ratio * nextSpan;
    const rawEnd = rawStart + nextSpan;
    const next = zoomImportanceViewport(current, scale, ratio);
    publish(next, action, boundaryDirection(rawStart, rawEnd));
  };
  const applyPan = (deltaRows, action) => {
    const current = currentViewport;
    const span = current.end - current.start;
    const rawStart = current.start + finiteNumber(deltaRows, 0);
    const next = panImportanceViewport(current, deltaRows);
    publish(next, action, boundaryDirection(rawStart, rawStart + span));
  };
  const action = (name) => {
    if (name === "zoom-in") applyZoom(0.5, 0.5, name);
    else if (name === "zoom-out") applyZoom(2, 0.5, name);
    else if (name === "reset") publish(createImportanceViewport(currentViewport.total), name);
  };
  const show = (node) => {
    const row = rows.find((item) => item.date === node.dataset.importanceDay);
    if (!row || !tooltip) return;
    const encode = typeof escapeHtml === "function" ? escapeHtml : String;
    tooltip.innerHTML = `<strong>${encode(row.date)} · ${Math.round(row.composite_score)}</strong>
      <span>${encode(row.summary || "暂无新信息")}</span>
      <small>${Object.entries(row.category_scores || {}).map(([key, value]) =>
        `${LABELS[key]} ${Math.round(value)}`).join(" · ")}</small>`;
    tooltip.hidden = false;
  };
  const hide = () => { if (tooltip) tooltip.hidden = true; };
  const click = (event) => {
    const target = event.target;
    const chartAction = target?.closest?.("[data-chart-action]");
    if (chartAction) {
      action(chartAction.dataset.chartAction);
      return;
    }
    const range = target?.closest?.("[data-importance-days]");
    if (range && onRange) {
      onRange(Number(range.dataset.importanceDays));
      return;
    }
    const node = target?.closest?.("[data-importance-day]");
    if (node) onOpen(node.dataset.importanceDay, node);
  };
  const keydown = (event) => {
    if (event.key === "+" || event.key === "=") {
      event.preventDefault?.();
      action("zoom-in");
      return;
    }
    if (event.key === "-") {
      event.preventDefault?.();
      action("zoom-out");
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault?.();
      const span = currentViewport.end - currentViewport.start;
      const amount = Math.max(1, span * 0.8) * (event.key === "ArrowLeft" ? -1 : 1);
      applyPan(amount, event.key === "ArrowLeft" ? "pan-left" : "pan-right");
      return;
    }
    if (event.key === "Home") {
      event.preventDefault?.();
      action("reset");
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && event.target?.matches?.("[data-importance-day]")) {
      event.preventDefault();
      onOpen(event.target.dataset.importanceDay, event.target);
    }
  };
  const mouseover = (event) => {
    const node = event.target?.closest?.("[data-importance-day]");
    if (node) show(node);
  };
  const focusin = (event) => {
    const node = event.target?.closest?.("[data-importance-day]");
    if (node) show(node);
  };
  const focusout = () => hide();
  const mouseleave = () => hide();

  const pointerPosition = (event) => ({ x: finiteNumber(event.clientX, 0), y: finiteNumber(event.clientY, 0) });
  const pointerCapture = (event, method) => {
    const target = event.target || plotSurface;
    if (typeof target?.[method] === "function") target[method](event.pointerId);
    else if (typeof event.currentTarget?.[method] === "function") event.currentTarget[method](event.pointerId);
    else if (typeof plotSurface?.[method] === "function") plotSurface[method](event.pointerId);
  };
  const distanceAndMidpoint = () => {
    const points = [...activePointers.values()];
    if (points.length < 2) return null;
    const [first, second] = points;
    return {
      distance: Math.hypot(second.x - first.x, second.y - first.y),
      midpoint: { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 },
    };
  };
  const beginPinch = () => {
    const measure = distanceAndMidpoint();
    if (!measure || measure.distance <= 0) return;
    pinchStartDistance = measure.distance;
    pinchStartMidpoint = measure.midpoint;
    pinchStartViewport = currentViewport;
  };
  const pointerdown = (event) => {
    if (event.pointerId == null) return;
    const point = pointerPosition(event);
    activePointers.set(event.pointerId, { ...point, startX: point.x, startY: point.y });
    pointerCapture(event, "setPointerCapture");
    if (activePointers.size === 1 && (event.isPrimary !== false) && (event.button == null || event.button === 0)) {
      primaryPointerId = event.pointerId;
      dragLastX = point.x;
      dragLastY = point.y;
    }
    if (activePointers.size === 2) {
      beginPinch();
      setDragging(true);
    }
  };
  const pointermove = (event) => {
    const pointer = activePointers.get(event.pointerId);
    if (!pointer) return;
    const point = pointerPosition(event);
    pointer.x = point.x;
    pointer.y = point.y;
    if (activePointers.size >= 2 && pinchStartDistance > 0 && pinchStartViewport) {
      const measure = distanceAndMidpoint();
      if (!measure || measure.distance <= 0) return;
      const rect = plotRect();
      const anchorRatio = clamp((measure.midpoint.x - rect.left) / rect.width, 0, 1);
      applyZoom(pinchStartDistance / measure.distance, anchorRatio, "pinch-zoom", pinchStartViewport);
      event.preventDefault?.();
      return;
    }
    if (activePointers.size !== 1 || event.pointerId !== primaryPointerId) return;
    const distance = Math.hypot(point.x - pointer.startX, point.y - pointer.startY);
    const deltaX = point.x - dragLastX;
    const deltaY = point.y - dragLastY;
    if (!dragging) {
      if (distance <= 4) return;
      if (Math.abs(point.x - pointer.startX) <= Math.abs(point.y - pointer.startY)) return;
      setDragging(true);
      dragLastX = point.x;
      dragLastY = point.y;
      const rect = plotRect();
      const span = currentViewport.end - currentViewport.start;
      if (deltaX) applyPan(-deltaX * span / rect.width, "drag-pan");
      event.preventDefault?.();
      return;
    }
    dragLastX = point.x;
    dragLastY = point.y;
    if (Math.abs(deltaX) <= Math.abs(deltaY)) return;
    const rect = plotRect();
    const span = currentViewport.end - currentViewport.start;
    if (deltaX) applyPan(-deltaX * span / rect.width, "drag-pan");
    event.preventDefault?.();
  };
  const pointerend = (event) => {
    if (event.pointerId == null) return;
    const wasPinching = pinchStartDistance > 0 || activePointers.size >= 2;
    activePointers.delete(event.pointerId);
    pointerCapture(event, "releasePointerCapture");
    if (wasPinching) {
      setDragging(false);
      primaryPointerId = null;
    }
    if (activePointers.size < 2) {
      pinchStartDistance = 0;
      pinchStartMidpoint = null;
      pinchStartViewport = null;
    }
    if (!activePointers.size) {
      primaryPointerId = null;
      setDragging(false);
    }
  };
  announce();
  container.addEventListener("mouseover", mouseover);
  container.addEventListener("focusin", focusin);
  container.addEventListener("mouseleave", mouseleave);
  container.addEventListener("focusout", focusout);
  container.addEventListener("click", click);
  container.addEventListener("keydown", keydown);
  const wheel = (event) => {
    const rect = plotRect();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? rect.height : 1;
    const deltaX = finiteNumber(event.deltaX, 0) * unit;
    const deltaY = finiteNumber(event.deltaY, 0) * unit;
    const horizontal = Math.abs(deltaX) > Math.abs(deltaY) && deltaX !== 0;
    if (event.ctrlKey || event.metaKey) {
      const anchorRatio = clamp((finiteNumber(event.clientX, rect.left + rect.width / 2) - rect.left) / rect.width, 0, 1);
      applyZoom(Math.exp(deltaY * 0.002), anchorRatio, "wheel-zoom");
      event.preventDefault?.();
    } else if (horizontal || event.shiftKey) {
      const horizontalDelta = horizontal ? deltaX : deltaY;
      applyPan(-horizontalDelta * (currentViewport.end - currentViewport.start) / rect.width, "wheel-pan");
      event.preventDefault?.();
    }
  };
  container.addEventListener("wheel", wheel);
  container.addEventListener("pointerdown", pointerdown);
  container.addEventListener("pointermove", pointermove);
  container.addEventListener("pointerup", pointerend);
  container.addEventListener("pointercancel", pointerend);
  container.addEventListener("lostpointercapture", pointerend);
  return () => {
    activePointers.clear();
    primaryPointerId = null;
    pinchStartDistance = 0;
    pinchStartMidpoint = null;
    pinchStartViewport = null;
    dragLastX = 0;
    dragLastY = 0;
    setDragging(false);
    container.removeEventListener("mouseover", mouseover);
    container.removeEventListener("focusin", focusin);
    container.removeEventListener("mouseleave", mouseleave);
    container.removeEventListener("focusout", focusout);
    container.removeEventListener("click", click);
    container.removeEventListener("keydown", keydown);
    container.removeEventListener("wheel", wheel);
    container.removeEventListener("pointerdown", pointerdown);
    container.removeEventListener("pointermove", pointermove);
    container.removeEventListener("pointerup", pointerend);
    container.removeEventListener("pointercancel", pointerend);
    container.removeEventListener("lostpointercapture", pointerend);
  };
}
