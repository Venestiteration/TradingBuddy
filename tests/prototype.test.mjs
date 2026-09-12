import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(
  new URL("../ai-investment-assistant-desktop.html", import.meta.url),
  "utf8",
);

for (const id of ["asset-switcher", "conversation", "composer", "detail-sheet"]) {
  assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
}

assert.match(html, />动态</);
assert.match(html, /持仓/);
assert.match(html, /自选/);
assert.doesNotMatch(html, /待复核/);

assert.match(html, /font-family:\s*-apple-system/);
assert.match(html, /backdrop-filter:\s*blur/);
assert.match(html, /prefers-reduced-motion:\s*reduce/);
assert.match(html, /prefers-reduced-transparency:\s*reduce/);
assert.match(html, /prefers-contrast:\s*more/);
assert.match(html, /:focus-visible/);
assert.match(html, /\.pressable:active/);

for (const symbol of ["TCEHY", "600519"]) {
  assert.match(html, new RegExp(symbol), `missing fixture ${symbol}`);
}
for (const fn of ["selectAsset", "ask", "toggleAnalysis"]) {
  assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`), `missing ${fn}()`);
}
for (const label of ["已知事实", "当前推断", "尚不确定", "下一步可核验"]) {
  assert.match(html, new RegExp(label), `missing answer layer ${label}`);
}
assert.match(html, /我不能替你决定是否买入或卖出/);

for (const fn of ["openSheet", "closeSheet"]) {
  assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`), `missing ${fn}()`);
}
assert.match(html, /aria-modal="false"/);
assert.match(html, /lastTrigger\.focus\(\)/);
assert.match(html, /来源与证据/);
assert.match(html, /我的判断/);
assert.match(html, /管理标的/);

for (const target of ["asset", "dynamic", "actions", "composer", "thesis"]) {
  assert.match(html, new RegExp(`data-tour=["']${target}["']`), `missing tour target ${target}`);
}
for (const id of ["tour-layer", "tour-focus-ring", "tour-blocker", "tour-popover"]) {
  assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
}
for (const title of ["选择标的", "查看动态", "继续理解", "自由追问", "维护判断"]) {
  assert.match(html, new RegExp(title), `missing tour step ${title}`);
}
assert.match(html, /aria-modal="true"/);
assert.match(html, /使用指引/);

for (const fn of ["startTour", "showTourStep", "positionTour", "finishTour"]) {
  assert.match(html, new RegExp(`function\\s+${fn}\\s*\\(`), `missing ${fn}()`);
}
assert.match(html, /sessionStorage/);
assert.match(html, /event\.key === "ArrowRight"/);
assert.match(html, /event\.key === "ArrowLeft"/);
assert.match(html, /event\.key === "Escape"/);
assert.match(html, /开始使用/);
assert.match(html, /跳过/);

console.log("prototype structure: ok");
