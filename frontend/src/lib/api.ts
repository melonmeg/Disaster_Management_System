// Thin fetch wrapper for the FastAPI backend: bearer token, one silent refresh on 401, uniform errors.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";
const KEY = "erms.session";

export type User = { user_id: number; username: string; role: "admin" | "dispatcher" | "responder"; responder_id: number | null };
type Session = { access_token: string; refresh_token: string; user: User };

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

// sessionStorage: cleared when the tab closes. Trade-off: readable by any script on this origin (XSS).
export function loadSession(): Session | null {
  try { return JSON.parse(sessionStorage.getItem(KEY) ?? "null"); } catch { return null; }
}
function saveSession(s: Session | null) {
  try { s ? sessionStorage.setItem(KEY, JSON.stringify(s)) : sessionStorage.removeItem(KEY); } catch { /* storage blocked */ }
}

let onSessionLost: (() => void) | null = null;
export function setSessionLostHandler(fn: (() => void) | null) { onSessionLost = fn; }

async function parse(res: Response) {
  if (res.status === 204) return null;
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
  if (!res.ok) {
    const e = body?.error;
    const detail = Array.isArray(e?.details) ? e.details.map((d: any) => `${d.field}: ${d.message}`).join("; ") : "";
    throw new ApiError(res.status, e?.code ?? "HTTP_ERROR", (e?.message ?? `Request failed (${res.status})`) + (detail ? ` — ${detail}` : ""), e?.details);
  }
  return body;
}

async function send(path: string, init: RequestInit, token: string | null) {
  try {
    return await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers },
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check that the backend is running.");
  }
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  const s = loadSession();
  if (!s) return false;
  refreshing ??= (async () => {
    try {
      const res = await send("/auth/refresh", { method: "POST", body: JSON.stringify({ refresh_token: s.refresh_token }) }, null);
      if (!res.ok) return false;
      const t = await res.json();
      saveSession({ access_token: t.access_token, refresh_token: t.refresh_token, user: t.user });
      return true;
    } catch { return false; } finally { setTimeout(() => (refreshing = null), 0); }
  })();
  return refreshing;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const opts: RequestInit = { ...rest, ...(json !== undefined ? { body: JSON.stringify(json) } : {}) };
  let res = await send(path, opts, loadSession()?.access_token ?? null);
  if (res.status === 401 && (await refresh())) res = await send(path, opts, loadSession()?.access_token ?? null);
  if (res.status === 401 && loadSession()) { saveSession(null); onSessionLost?.(); }
  return parse(res);
}

/** Like api() but returns the raw Response (for binary downloads/uploads). Throws ApiError on non-2xx. */
export async function apiRaw(path: string, init: RequestInit = {}): Promise<Response> {
  let res = await send(path, init, loadSession()?.access_token ?? null);
  if (res.status === 401 && (await refresh())) res = await send(path, init, loadSession()?.access_token ?? null);
  if (res.status === 401 && loadSession()) { saveSession(null); onSessionLost?.(); }
  if (!res.ok) await parse(res);   // throws with the server's error message
  return res;
}

export async function login(username: string, password: string): Promise<User> {
  const res = await send("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }, null);
  const t = await parse(res);
  saveSession({ access_token: t.access_token, refresh_token: t.refresh_token, user: t.user });
  return t.user;
}

export async function logout() {
  try { if (loadSession()) await send("/auth/logout", { method: "POST" }, loadSession()!.access_token); } catch { /* ignore */ }
  saveSession(null);
}

export const qs = (params: Record<string, string | number | boolean | string[] | undefined | null>) => {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    (Array.isArray(v) ? v : [v]).forEach((x) => u.append(k, String(x)));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
};
