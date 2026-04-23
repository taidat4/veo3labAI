/**
 * Next.js Middleware — Skip body size limit for upload routes
 * 
 * By default Next.js limits request body to 10MB for middleware processing.
 * We skip middleware entirely for /api/* routes since they are just proxied
 * to the FastAPI backend via rewrites.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  // Just pass through — no processing needed
  return NextResponse.next();
}

// Only run middleware on non-API routes (pages only)
// This ensures /api/* requests bypass Next.js body size limits entirely
export const config = {
  matcher: [
    // Match all pages EXCEPT api, ws, static, _next, favicon
    "/((?!api|ws|static|_next|favicon.ico).*)",
  ],
};
