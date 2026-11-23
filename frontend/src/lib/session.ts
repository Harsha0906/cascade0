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
  const res = await fetch(path, { ...init, headers });
  if (isAuthError(res) && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.assign("/login");
  }
  return res;
}
