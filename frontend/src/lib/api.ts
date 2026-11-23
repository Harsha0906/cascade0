import { apiFetch } from "./session";

export interface ApiResult<T = any> {
  ok: boolean;
  status: number;
  data: T | null;
  /** The server's message, verbatim; empty when ok. */
  error: string;
}

/** The server's error text, shown verbatim: a string `detail`, or FastAPI's 422 list as "field: message". */
export function errorText(status: number, body: unknown): string {
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d) => {
        if (d && typeof d === "object") {
          const loc = Array.isArray((d as any).loc) ? (d as any).loc.filter((p: unknown) => p !== "body").join(".") : "";
          const msg = String((d as any).msg ?? "");
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(d);
      })
      .join("; ");
  }
  return `Request failed (HTTP ${status})`;
}

/** apiFetch + JSON parsing + verbatim error text. Never throws. */
export async function callApi<T = any>(path: string, method = "GET", body?: unknown): Promise<ApiResult<T>> {
  try {
    const res = await apiFetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => null);
    return { ok: res.ok, status: res.status, data, error: res.ok ? "" : errorText(res.status, data) };
  } catch {
    return { ok: false, status: 0, data: null, error: "Could not reach the server. Check your connection and try again." };
  }
}
