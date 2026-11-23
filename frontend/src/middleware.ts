import { NextResponse, type NextRequest } from "next/server";

/**
 * Proxied /api/v1 requests carry the signed-in user's own `Authorization: Bearer <token>`
 * (passed through untouched); the backend verifies it and checks the user's factory role.
 *
 * The browser path never uses the machine key: any machine-key header (automation only) or
 * `X-Dev-User` (backend dev mode only) header a client sends is discarded here, and no key
 * is injected.
 */
export function middleware(req: NextRequest) {
  const headers = new Headers(req.headers);
  headers.delete("x-api-key");
  headers.delete("x-dev-user");
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/v1/:path*" };
