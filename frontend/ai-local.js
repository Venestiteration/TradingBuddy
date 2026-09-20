export const AI_CONFIG_KEY = "tradingbuddy.ai.config.v1";
export const AI_WORKSPACE_KEY = "tradingbuddy.ai.workspace.v1";
export const SOURCE_TOUR_KEY = "tradingbuddy.tour.sources.v2";
export const AI_TOUR_KEY = "tradingbuddy.tour.ai.v1";
export const DEFAULT_BASE_URL = "https://api.openai.com/v1";

export const AI_API_PRESETS = [
  { id: "openai", label: "OpenAI 官方", url: DEFAULT_BASE_URL, mode: "responses" },
  { id: "zhipu", label: "智谱 AI", url: "https://open.bigmodel.cn/api/paas/v4", mode: "chat" },
  { id: "deepseek", label: "DeepSeek", url: "https://api.deepseek.com/v1", mode: "chat" },
  { id: "qwen", label: "通义千问（百炼）", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", mode: "chat" },
  { id: "siliconflow", label: "硅基流动", url: "https://api.siliconflow.cn/v1", mode: "chat" },
  { id: "moonshot", label: "月之暗面", url: "https://api.moonshot.cn/v1", mode: "chat" },
  { id: "custom", label: "自定义地址", url: "", mode: "chat" },
];

const normalizeBaseUrl = (value) => String(value || "").trim().replace(/\/+$/, "").toLowerCase();

export function apiPresetFor(baseUrl) {
  const normalized = normalizeBaseUrl(baseUrl);
  if (!normalized || normalized === normalizeBaseUrl(DEFAULT_BASE_URL)) return AI_API_PRESETS[0];
  return AI_API_PRESETS.find((preset) => preset.url && normalizeBaseUrl(preset.url) === normalized)
    || AI_API_PRESETS.at(-1);
}

const apiModeForBaseUrl = (baseUrl) => apiPresetFor(baseUrl).mode;

const blankConfig = () => ({ enabled: false, apiKey: "", model: "", baseUrl: "", apiMode: "responses", updatedAt: "" });
const parse = (value, fallback) => {
  try { return JSON.parse(value) ?? fallback; } catch { return fallback; }
};
const browserStorage = () => {
  try { return globalThis.localStorage || null; } catch { return null; }
};
const safeGet = (storage, key) => {
  if (!storage) return null;
  try { return storage.getItem(key); } catch { return null; }
};
const safeSet = (storage, key, value) => {
  if (!storage) throw new Error("浏览器需要允许本地存储才能启用 AI");
  try { storage.setItem(key, value); }
  catch { throw new Error("浏览器需要允许本地存储才能启用 AI"); }
};
const safeRemove = (storage, key) => {
  if (!storage) throw new Error("无法清除本地配置，请允许浏览器站点存储");
  try { storage.removeItem(key); }
  catch { throw new Error("无法清除本地配置，请允许浏览器站点存储"); }
};

export function loadAIConfig(storage = null) {
  const target = storage || browserStorage();
  const value = parse(safeGet(target, AI_CONFIG_KEY), blankConfig());
  const apiKey = typeof value.apiKey === "string" ? value.apiKey.trim().slice(0, 512) : "";
  const model = typeof value.model === "string" ? value.model.trim().slice(0, 128) : "";
  const baseUrl = typeof value.baseUrl === "string" ? value.baseUrl.slice(0, 512) : "";
  const apiMode = value.apiMode === "chat" || value.apiMode === "responses"
    ? value.apiMode
    : apiModeForBaseUrl(baseUrl);
  return {
    enabled: value.enabled === true && Boolean(apiKey && model),
    apiKey,
    model,
    baseUrl,
    apiMode,
    updatedAt: typeof value.updatedAt === "string" ? value.updatedAt : "",
  };
}

export function validateAIConfig(input) {
  const value = {
    enabled: input.enabled === true,
    apiKey: String(input.apiKey || "").trim(),
    model: String(input.model || "").trim(),
    baseUrl: String(input.baseUrl || "").trim(),
    apiMode: input.apiMode === "chat" || input.apiMode === "responses"
      ? input.apiMode
      : apiModeForBaseUrl(input.baseUrl),
  };
  if (!value.apiKey || value.apiKey.length > 512) throw new Error("请填写有效的 API Key");
  if (!value.model || value.model.length > 128) throw new Error("请填写有效的模型名称");
  if (value.baseUrl) {
    let parsed;
    try { parsed = new URL(value.baseUrl); }
    catch { throw new Error("API 地址必须是有效的 HTTPS 地址"); }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
      throw new Error("API 地址必须是 HTTPS 公网地址");
    }
  }
  return value;
}

export function saveAIConfig(input, storage = null) {
  const target = storage || browserStorage();
  const value = validateAIConfig(input);
  const saved = { ...value, updatedAt: new Date().toISOString() };
  safeSet(target, AI_CONFIG_KEY, JSON.stringify(saved));
  return saved;
}

export function disableAI(storage = null) {
  const target = storage || browserStorage();
  const value = loadAIConfig(storage);
  safeSet(target, AI_CONFIG_KEY, JSON.stringify({ ...value, enabled: false, updatedAt: new Date().toISOString() }));
}

export function clearAIData(storage = null) {
  const target = storage || browserStorage();
  safeRemove(target, AI_CONFIG_KEY);
  safeRemove(target, AI_WORKSPACE_KEY);
  safeRemove(target, AI_TOUR_KEY);
}

export function aiHeaders(config) {
  if (!config.enabled || !String(config.apiKey || "").trim() || !String(config.model || "").trim()) {
    throw new Error("请先在设置中启用 AI 分析");
  }
  return {
    "X-TB-API-Key": config.apiKey,
    "X-TB-Model": config.model,
    "X-TB-Base-URL": config.baseUrl || DEFAULT_BASE_URL,
    "X-TB-API-Mode": config.apiMode || apiModeForBaseUrl(config.baseUrl),
  };
}

function loadWorkspace(storage) {
  const target = storage || browserStorage();
  const value = parse(safeGet(target, AI_WORKSPACE_KEY), { assets: {} });
  return value && typeof value.assets === "object" && value.assets !== null && !Array.isArray(value.assets)
    ? value
    : { assets: {} };
}

export function loadAssetAI(assetId, storage = null) {
  const asset = loadWorkspace(storage).assets[String(assetId)] || {};
  return {
    messages: Array.isArray(asset.messages) ? asset.messages.slice(-50) : [],
    analyses: Array.isArray(asset.analyses) ? asset.analyses.slice(-20) : [],
  };
}

export function boundRecentMessages(messages) {
  return (Array.isArray(messages) ? messages : []).slice(-6).map(({ role, content }) => {
    let bounded = String(content || "");
    if (role === "assistant") {
      try {
        const parsed = JSON.parse(bounded);
        bounded = parsed.result?.conclusion || parsed.conclusion || bounded;
      } catch {
        // Older local entries may already be plain text.
      }
    }
    return { role, content: bounded.slice(0, 2000) };
  });
}

export function captureView(state) {
  return { assetId: state.assetId, generation: state.viewGeneration };
}

export function isCurrentView(state, view) {
  return state.assetId === view.assetId && state.viewGeneration === view.generation;
}

export function applyIfCurrentView(state, view, apply) {
  if (!isCurrentView(state, view)) return false;
  apply();
  return true;
}

export function transitionAssetView(state, assetId, { cancelGeneration = () => {}, loadLocalAIState = () => {} } = {}) {
  if (state.busy) cancelGeneration();
  else if (state.abortController) state.abortController.abort();
  state.abortController = null;
  state.viewGeneration += 1;
  state.assetId = assetId;
  state.selectedEventId = null;
  state.analysis = null;
  state.thesisContext = null;
  state.thesisDraft = null;
  state.thesisDraftPending = false;
  state.thesisAcceptedChanges = {};
  state.overview = null;
  loadLocalAIState();
}

export async function runCurrentViewRefresh(state, view, refresh, loadOverview, onSuccess, onError) {
  if (!isCurrentView(state, view)) return false;
  try {
    await refresh();
    if (!isCurrentView(state, view)) return false;
    await loadOverview(view.assetId);
    if (!isCurrentView(state, view)) return false;
    onSuccess();
    return true;
  } catch (error) {
    if (!isCurrentView(state, view)) return false;
    onError(error);
    return false;
  }
}

function updateAsset(assetId, update, storage) {
  const target = storage || browserStorage();
  const workspace = loadWorkspace(target);
  const current = loadAssetAI(assetId, target);
  workspace.assets[String(assetId)] = update(current);
  safeSet(target, AI_WORKSPACE_KEY, JSON.stringify(workspace));
}

export function saveAnalysis(assetId, analysis, storage = null) {
  updateAsset(assetId, (current) => ({ ...current, analyses: [...current.analyses, analysis].slice(-20) }), storage);
}

export function saveConversationTurn(assetId, question, completed, storage = null) {
  const createdAt = new Date().toISOString();
  updateAsset(assetId, (current) => ({
    ...current,
    messages: [
      ...current.messages,
      { role: "user", content: question, created_at: createdAt },
      { role: "assistant", content: JSON.stringify(completed), created_at: createdAt },
    ].slice(-50),
  }), storage);
}
