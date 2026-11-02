import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { safeNextPath } from "@/lib/auth/next-cookie";
import { requestOrigin } from "@/lib/auth/origin";

const MAX_REASON_LENGTH = 200;

function withParam(url: string, key: string, value: string): string {
  const u = new URL(url);
  u.searchParams.set(key, value);
  return u.toString();
}

/**
 * OAuth callback (Google, LinkedIn, and linking either to an account).
 * Deliberately simpler than the dashboard's: no Prisma developer lookup, no
 * destinationAfterLogin routing table — just "go back where the user was
 * trying to go, or the directory."
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const origin = requestOrigin(request);
  const code = searchParams.get("code");
  const cookieNext = safeNextPath(request.cookies.get("zynd_next")?.value);
  const queryNext = safeNextPath(searchParams.get("next"));

  const clearAuthCookies = (res: NextResponse) => {
    res.cookies.delete("zynd_next");
    res.cookies.delete("zynd_intent");
  };

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

  if (!code) {
    // No code: the provider or Supabase refused, e.g. that Google account
    // already belongs to another Zynd account. Someone already signed in was
    // linking a sign-in method, so send them back where they started, with
    // the reason. Everyone else goes back to the sign-in page.
    const reason = (searchParams.get("error_description") || "").slice(0, MAX_REASON_LENGTH);
    const { data: { user } } = await supabase.auth.getUser();
    const target = user && cookieNext
      ? withParam(`${origin}${cookieNext}`, "auth_error", reason || "Could not connect that account")
      : reason
        ? `${origin}/auth?error=${encodeURIComponent(reason)}`
        : `${origin}/auth?error=auth_callback_failed`;
    const failure = NextResponse.redirect(target);
    pending.forEach(({ name, value, options }) => failure.cookies.set(name, value, options));
    clearAuthCookies(failure);
    return failure;
  }

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
