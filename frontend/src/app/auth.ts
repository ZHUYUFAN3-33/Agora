import { API_BASE } from "./data/agents";

export type AgoraAuth = {
  token: string;
  user_id: string;
  is_admin?: boolean;
};

const KEY = "agora_auth";

export function getAuth(): AgoraAuth | null {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    if (raw?.token && raw?.user_id) {
      return {
        token: String(raw.token),
        user_id: String(raw.user_id),
        is_admin: !!raw.is_admin,
        // legacy nickname field → treat as display
      };
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function setAuth(auth: AgoraAuth) {
  localStorage.setItem(
    KEY,
    JSON.stringify({
      token: auth.token,
      user_id: auth.user_id,
      is_admin: !!auth.is_admin,
      nickname: auth.user_id,
    }),
  );
}

export function clearAuth() {
  localStorage.removeItem(KEY);
}

export function authHeaders(extra?: HeadersInit): HeadersInit {
  const auth = getAuth();
  return {
    ...(extra || {}),
    ...(auth?.token ? { Authorization: `Bearer ${auth.token}` } : {}),
  };
}

export async function authFetch(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  const auth = getAuth();
  if (auth?.token) headers.set("Authorization", `Bearer ${auth.token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_BASE}${path.startsWith("/") ? path : `/${path}`}`, {
    ...init,
    headers,
  });
}

export async function loginRequest(userId: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Login failed");
  return data as AgoraAuth;
}

export async function registerRequest(userId: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Register failed");
  return data as AgoraAuth;
}

export async function logoutRequest() {
  try {
    await authFetch("/auth/logout", { method: "POST" });
  } catch {
    /* ignore */
  }
  clearAuth();
}
