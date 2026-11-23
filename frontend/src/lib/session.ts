import { supabase } from "./supabase";

export const NO_MEMBERSHIP_MESSAGE =
  "Ask the factory owner to add you: python -m app.admin add-member --email <you> --factory <id> --role owner|approver|viewer";

export const SERVICE_UNAVAILABLE_MESSAGE = "Service temporarily unavailable, retrying";

/** Authorization header for the current Supabase session (empty when signed out). */
export function authHeaders(session: { access_token: string } | null | undefined): Record<string, string> {
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}

/** 401 means no/invalid session: the user must sign in again. */
export function isAuthError(res: { status: number }): boolean {
  return res.status === 401;
}

/** User-facing message for the special backend statuses; null means "use the generic message". */
export function describeApiError(status: number, path: string, detail: string | undefined): string | null {
  if (status === 404 && path.includes("/api/v1/factory")) return NO_MEMBERSHIP_MESSAGE;
  if (status === 503) return SERVICE_UNAVAILABLE_MESSAGE;
  return detail || null;
}

const FACTORY_KEY = "cz.factory_id";
export const CHOOSE_FACTORY_EVENT = "cz:choose-factory";

export function getSelectedFactory(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(FACTORY_KEY) || null;
  } catch {
    return null;
  }
}

export function setSelectedFactory(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(FACTORY_KEY, id);
    else window.localStorage.removeItem(FACTORY_KEY);
  } catch {
    /* storage unavailable: the choice just lasts for this page */
  }
}

/** Routes that read `factory_id` from the JSON body rather than only the query string. */
const BODY_ROUTES = [
  "/api/v1/reset",
  "/api/v1/simulate-crisis",
  "/api/v1/channels/link-code",
  "/api/v1/ingest/erp-csv",
  "/api/v1/ingest/stock-summary",
  "/api/v1/ingest/open-purchase-orders",
  "/api/v1/ingest/sales-order-lines",
];
/** Routes that must never be scoped to a factory. */
const UNSCOPED = ["/api/v1/factories", "/api/v1/my/"];

/** Adds the selected factory to a request: `?factory_id=` on the path, and into the JSON body of the
 *  routes that take it there. An explicit factory_id already present is never overridden. */
export function scopeRequest(
  path: string,
  body: BodyInit | null | undefined,
  factoryId: string | null,
): { path: string; body: BodyInit | null | undefined } {
  if (!factoryId || !path.startsWith("/api/") || UNSCOPED.some((u) => path.startsWith(u))) return { path, body };
  let outPath = path;
  if (!/[?&]factory_id=/.test(path)) outPath += (path.includes("?") ? "&" : "?") + `factory_id=${encodeURIComponent(factoryId)}`;
  let outBody = body;
  if (BODY_ROUTES.some((r) => path === r || path.startsWith(r + "?"))) {
    try {
      const obj = typeof body === "string" ? JSON.parse(body) : body == null ? {} : null;
      if (obj && typeof obj === "object" && !Array.isArray(obj) && !("factory_id" in obj)) {
        outBody = JSON.stringify({ ...obj, factory_id: factoryId });
      }
    } catch {
      /* not JSON: leave the body alone */
    }
  }
  return { path: outPath, body: outBody };
}

export async function getSession() {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session;
}

/** fetch() that carries the signed-in user's bearer token; a 401 sends the user to /login. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const session = await getSession();
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(authHeaders(session))) headers.set(k, v);
  const scoped = scopeRequest(path, init.body, getSelectedFactory());
  if (scoped.body !== init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(scoped.path, { ...init, body: scoped.body, headers });
  if (res.status === 409 && typeof window !== "undefined") {
    // A user in several factories who named none: ask the shell to open the picker.
    const detail = await res.clone().json().then((b) => b?.detail, () => null);
    if (detail === "choose a factory") window.dispatchEvent(new Event(CHOOSE_FACTORY_EVENT));
  }
  if (isAuthError(res) && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.assign("/login");
  }
  return res;
}
