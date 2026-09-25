import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { safeNextPath } from "@/lib/auth/next-cookie";

/**
 * OAuth (Google/LinkedIn) and email-magic-link callback. Deliberately
 * simpler than the dashboard's: no Prisma developer lookup, no
 * destinationAfterLogin routing table — just "go back where the user was
 * trying to go, or the directory."
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
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
