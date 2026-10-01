import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const app = readFileSync(path.join(root, "frontend/app.js"), "utf8");
const details = readFileSync(path.join(root, "frontend/importance-detail.js"), "utf8");
const dynamics = readFileSync(path.join(root, "frontend/public-dynamics.js"), "utf8");
const researchBrief = readFileSync(path.join(root, "frontend/research-brief.js"), "utf8");
const styles = readFileSync(path.join(root, "frontend/styles.css"), "utf8");

test("public category opens a complete rolling 24 hour feed", () => {
  assert.ok(details.includes("recent_count_24h"));
  assert.ok(app.includes('openSheet("publicDynamics"'));
  assert.ok(app.includes("loadPublicDynamics"));
  assert.ok(dynamics.includes('data-public-kind="all"'));
  assert.ok(dynamics.includes('data-public-kind="official"'));
  assert.ok(dynamics.includes('data-public-kind="media"'));
  assert.ok(dynamics.includes("window_start"));
  assert.ok(dynamics.includes("source_status"));
});

test("dynamic detail keeps sources and active analysis action", () => {
  assert.ok(dynamics.includes("data-public-dynamic-id"));
  assert.ok(dynamics.includes("data-extract-dynamic"));
  assert.ok(dynamics.includes("data-analyze-dynamic"));
  assert.ok(styles.includes(".public-dynamics-list"));
  assert.ok(styles.includes(".public-source-status"));
});

test("public dynamics preserves its sheet while rendering progressive research clusters", () => {
  assert.ok(dynamics.includes("renderResearchEvents"));
  assert.ok(dynamics.includes("expandedClusterId"));
  assert.ok(researchBrief.includes("data-research-expand"));
  assert.ok(app.includes("expandedResearchClusterId"));
  assert.match(app, /research-events\/\$\{encodeURIComponent\(clusterId\)\}/);
  assert.ok(styles.includes(".research-event-card"));
});
