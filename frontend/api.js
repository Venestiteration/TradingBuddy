const configuredApiRoot = document.body.dataset.apiRoot || "/api";
export const API_ROOT = configuredApiRoot === "/api"
  && globalThis.location?.protocol === "file:"
  ? "http://127.0.0.1:8000/api"
  : configuredApiRoot;

export async function api(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch { body = { raw: text }; }
  if (!response.ok) {
    const error = new Error(body.detail || body.message || `请求失败（${response.status}）`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

export async function streamPost(path, payload, onEvent, signal, headers = {}) {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...headers },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const chunks = buffer.split(/\r?\n\r?\n/);
    buffer = chunks.pop() || "";
    for (const chunk of chunks.filter(Boolean)) {
      const lines = chunk.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
      const data = lines.filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim()).join("\n");
      try { onEvent({ event, data: JSON.parse(data || "{}") }); }
      catch { onEvent({ event, data: { message: data } }); }
    }
    if (done) break;
  }
  if (buffer.trim()) {
    const data = buffer.split(/\r?\n/).filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim()).join("\n");
    onEvent({ event: "message", data: JSON.parse(data || "{}") });
  }
}
