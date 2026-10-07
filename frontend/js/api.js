// Thin fetch wrapper for the backend JSON API.

export const API_BASE = (window.APP_CONFIG && window.APP_CONFIG.apiBase) || "http://127.0.0.1:8765";

export function apiUrl(path) {
  return API_BASE + path;
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(`无法连接后端（${API_BASE}），请确认已运行 run 脚本`);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `请求失败（HTTP ${response.status}）`);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  put: (path, body = {}) => request("PUT", path, body),
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function showNotice(element, message, ok = true) {
  element.hidden = !message;
  element.className = `notice ${ok ? "ok" : "bad"}`;
  element.textContent = message || "";
}
