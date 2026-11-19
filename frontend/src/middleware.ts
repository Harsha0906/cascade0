import { NextResponse, type NextRequest } from "next/server";

/**
 * Injects the backend operator key (server-side env, never sent to the browser) into
 * proxied /api/v1 requests. Any X-API-Key supplied by the client is discarded.
 *
 * This gates the FastAPI backend so it cannot be driven directly from the internet,
 * but anyone who can load this Next.js app can still use it. Put the app behind real
 * user auth (e.g. Supabase Auth or your SSO) before exposing it beyond a trusted network.
 */
export function middleware(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.delete("x-api-key");
  const key = process.env.CASCADE_API_KEY;
  if (key) headers.set("x-api-key", key);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/v1/:path*" };
