import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import type { AuthError, EmailOtpType, VerifyTokenHashParams } from "@supabase/supabase-js";
import { safeNextPath } from "@/lib/auth/next-cookie";
import { requestOrigin } from "@/lib/auth/origin";
import { emailSignInEnabled } from "@/lib/auth/providers";

/**
 * Sign-in callback. Deliberately simpler than the dashboard's: no Prisma
 * developer lookup, no destinationAfterLogin routing table — just "go back
 * where the user was trying to go, or the directory."
 *
 * Two ways in:
 * - `?code=` — PKCE code exchange. LinkedIn (the default, D12), Google, and a
 *   magic link sent with Supabase's default email template all land here. The
 *   code verifier is a cookie, so a magic link only works this way in the
 *   browser that requested it.
 * - `?token_hash=&type=` — a magic link whose Supabase email template links
 *   here with the token hash. verifyOtp needs no verifier, so this works on any
 *   device. Only accepted while NEXT_PUBLIC_AUTH_EMAIL is on.
 */

/**
 * Only the types a sign-in email can carry: `email`/`magiclink` for an existing
 * user, `signup` for the confirmation Supabase sends a new user instead.
 * recovery / invite / email_change are other flows and must not create a
 * session through this route.
 */
const SIGN_IN_OTP_TYPES: ReadonlySet<EmailOtpType> = new Set(["email", "magiclink", "signup"]);

function signInOtp(searchParams: URLSearchParams): VerifyTokenHashParams | null {
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  if (!tokenHash || !type || !SIGN_IN_OTP_TYPES.has(type)) return null;
  return { token_hash: tokenHash, type };
}

type Credential = { kind: "code"; code: string } | { kind: "otp"; otp: VerifyTokenHashParams };

/** Reason shown on /auth (`?error=`), mapped to copy in auth/page.tsx. */
function failureReason(error: Pick<AuthError, "code"> | null, supabaseErrorCode: string | null): string {
  if (emailSignInEnabled) {
    if (error?.code === "otp_expired" || supabaseErrorCode === "otp_expired") return "link_expired";
    if (error?.code === "pkce_code_verifier_not_found") return "link_other_browser";
  }
  return "auth_callback_failed";
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const origin = requestOrigin(request);
  const code = searchParams.get("code");
  const otp = !code && emailSignInEnabled ? signInOtp(searchParams) : null;
  const cookieNext = safeNextPath(request.cookies.get("zynd_next")?.value);
  const queryNext = safeNextPath(searchParams.get("next"));

  const clearAuthCookies = (res: NextResponse) => {
    res.cookies.delete("zynd_next");
    res.cookies.delete("zynd_intent");
  };
  const fail = (reason: string) => {
    const failure = NextResponse.redirect(`${origin}/auth?error=${reason}`);
    clearAuthCookies(failure);
    return failure;
  };

  const credential: Credential | null = code ? { kind: "code", code } : otp ? { kind: "otp", otp } : null;
  if (!credential) return fail(failureReason(null, searchParams.get("error_code")));

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

  const { error } = credential.kind === "code"
    ? await supabase.auth.exchangeCodeForSession(credential.code)
    : await supabase.auth.verifyOtp(credential.otp);
  if (error) return fail(failureReason(error, null));

  const next = cookieNext || queryNext || "/directory";
  const response = NextResponse.redirect(`${origin}${next}`);
  pending.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
  clearAuthCookies(response);
  return response;
}
