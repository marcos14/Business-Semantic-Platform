export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function getToken(): string | null {
  try {
    return localStorage.getItem("bsp_token");
  } catch {
    return null;
  }
}

export function clearToken() {
  try {
    localStorage.removeItem("bsp_token");
  } catch {
    /* ignore */
  }
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const t = getToken();
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (r.status === 401) {
    clearToken();
    if (typeof window !== "undefined") window.location.href = "/";
    throw new Error("Não autenticado");
  }
  if (!r.ok) {
    const d = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail));
  }
  return r.json();
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: unknown) =>
  api<T>(p, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
