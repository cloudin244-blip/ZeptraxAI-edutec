// The portal shares its login with the main ZeptraAI site (same origin, same token key)
const TOKEN_KEYS = ["base44_access_token", "token"];
const APP_ID = "6a58811b763e4b993e2b1bed";

export function getToken() {
  try {
    return TOKEN_KEYS.map((k) => localStorage.getItem(k)).find(Boolean) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  try {
    TOKEN_KEYS.forEach((k) => (token ? localStorage.setItem(k, token) : localStorage.removeItem(k)));
  } catch {
    // storage unavailable (private mode); the session lasts until reload
  }
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || data.message || `Request failed (${res.status})`, res.status);
  return data;
}

export const portal = {
  get: (path) => request("GET", `/api/portal${path}`),
  post: (path, body) => request("POST", `/api/portal${path}`, body ?? {}),
  put: (path, body) => request("PUT", `/api/portal${path}`, body ?? {}),
  del: (path) => request("DELETE", `/api/portal${path}`),
};

export const login = (email, password) => request("POST", `/api/apps/${APP_ID}/auth/login`, { email, password });

export function query(params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v));
  const s = q.toString();
  return s ? `?${s}` : "";
}
