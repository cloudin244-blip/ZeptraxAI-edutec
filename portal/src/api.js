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

const TIMEOUT_MS = 20000;
// Overloaded or briefly unreachable server: worth trying again after a short, randomised wait
const RETRY_STATUS = new Set([429, 502, 503, 504]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function once(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = controller && setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: controller?.signal });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  } finally {
    clearTimeout(timer);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new ApiError(data.error || data.message || `Request failed (${res.status})`, res.status);
    err.retryAfter = Number(res.headers.get("Retry-After")) || 0;
    throw err;
  }
  return data;
}

// `retries` > 0 only for requests that are safe to repeat (reads, saves that overwrite, idempotent actions).
// Waits grow exponentially with random jitter so thousands of students don't all retry in the same instant.
async function request(method, path, body, { retries = method === "GET" ? 3 : 0 } = {}) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await once(method, path, body);
    } catch (err) {
      // A long Retry-After (rate limit on sign-in attempts) means "wait minutes", not "try again now"
      const retryable = (err.status === 0 || RETRY_STATUS.has(err.status)) && !(err.retryAfter > 10);
      if (!retryable || attempt >= retries) throw err;
      const backoff = Math.min(8000, 500 * 2 ** attempt);
      await sleep(Math.max(err.retryAfter * 1000 || 0, backoff / 2 + Math.random() * backoff));
    }
  }
}

export const portal = {
  get: (path, opts) => request("GET", `/api/portal${path}`, undefined, opts),
  post: (path, body, opts) => request("POST", `/api/portal${path}`, body ?? {}, opts),
  put: (path, body, opts) => request("PUT", `/api/portal${path}`, body ?? {}, opts),
  del: (path, opts) => request("DELETE", `/api/portal${path}`, undefined, opts),
};

export const login = (email, password) => request("POST", `/api/apps/${APP_ID}/auth/login`, { email, password }, { retries: 2 });

export function query(params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v));
  const s = q.toString();
  return s ? `?${s}` : "";
}
