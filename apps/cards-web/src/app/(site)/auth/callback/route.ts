import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { safeNextPath } from "@/lib/auth/next-cookie";

const HOST_RE = /^[a-z0-9.-]+(:\d+)?$/i;

/**
 * The origin the browser is actually on. Behind Caddy, `next start` builds
 * request.url from its own bind address (https://localhost:3102 on dev,
 * https://0.0.0.0:3002 on prod), so redirecting there strands the user.
 * Caddy passes the real Host through and replaces any client-sent
 * X-Forwarded-* headers; without a proxy (`next dev`) request.url is right.
 */
function publicOrigin(request: NextRequest): string {
  const fallback = new URL(request.url);
  const host = (request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? "").split(",")[0].trim();
  if (!HOST_RE.test(host)) return fallback.origin;
  const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",")[0].trim();
  const proto = forwardedProto === "https" || forwardedProto === "http" ? forwardedProto : fallback.protocol.slice(0, -1);
  return `${proto}://${host}`;
}

/**
 * OAuth (LinkedIn, D12) callback. Deliberately simpler than the dashboard's:
 * no Prisma developer lookup, no destinationAfterLogin routing table — just
 * "go back where the user was trying to go, or the directory."
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const origin = publicOrigin(request);
  const code = searchParams.get("code");
  const cookieNext = safeNextPath(request.cookies.get("zynd_next")?.value);
  const queryNext = safeNextPath(searchParams.get("next"));

  const clearAuthCookies = (res: NextResponse) => {
    res.cookies.delete("zynd_next");
    res.cookies.delete("zynd_intent");
  };

  if (!code) {
    const failure = NextResponse.redirect(`${origin}/auth?error=auth_callback_failed`);
    clearAuthCookies(failure);
    return failure;
  }

  const pending: { name: string; value: string; options?: Record<string, unknown> }[] = [];
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options?: Record<string, unknown> }[]) {
          pending.push(...cookiesToSet);
        },
      },
    },
  );

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const failure = NextResponse.redirect(`${origin}/auth?error=auth_callback_failed`);
    clearAuthCookies(failure);
    return failure;
  }

  const next = cookieNext || queryNext || "/directory";
  const response = NextResponse.redirect(`${origin}${next}`);
  pending.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
  clearAuthCookies(response);
  return response;
}
