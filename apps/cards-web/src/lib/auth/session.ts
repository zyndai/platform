"use client";

import type { AuthError } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { clearNetworkCache } from "@/lib/network-cache";
import { safeNextPath, setAuthNext } from "@/lib/auth/next-cookie";
import { clientOrigin, oauthCallbackUrl } from "@/lib/auth/origin";

type OAuthProvider = "linkedin_oidc" | "google";

/** Remembers where to land after sign-in and returns the callback URL Supabase redirects to. */
function prepareAuthRedirect(nextPath: string, intent?: "card"): string {
  setAuthNext(nextPath, intent);
  return oauthCallbackUrl();
}

async function startOAuth(
  provider: OAuthProvider,
  nextPath: string,
  intent?: "card",
): Promise<string | null> {
  const redirectTo = prepareAuthRedirect(nextPath, intent);
  const { error } = await createClient().auth.signInWithOAuth({
    provider,
    options: { redirectTo },
  });
  return error ? error.message : null;
}

export function startLinkedInOAuth(nextPath: string, intent?: "card"): Promise<string | null> {
  return startOAuth("linkedin_oidc", nextPath, intent);
}

/** Only offered while Supabase has the Google provider enabled (see lib/auth/providers.ts). */
export function startGoogleOAuth(nextPath: string, intent?: "card"): Promise<string | null> {
  return startOAuth("google", nextPath, intent);
}

/**
 * Upper bound from RFC 5321 (254 octets for a forward path). The pattern only
 * rejects obvious typos: one "@", no whitespace, and a dot in the domain.
 * Supabase does the real validation.
 */
export const MAX_EMAIL_LENGTH = 254;
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isPlausibleEmail(raw: string): boolean {
  const email = raw.trim();
  return email.length > 0 && email.length <= MAX_EMAIL_LENGTH && EMAIL_SHAPE.test(email);
}

function magicLinkErrorMessage(error: AuthError): string {
  if (
    error.status === 429 ||
    error.code === "over_email_send_rate_limit" ||
    error.code === "over_request_rate_limit"
  ) {
    return "Too many sign-in emails requested. Wait a minute, then try again.";
  }
  if (error.code === "email_address_invalid") return "That email address can't receive sign-in links.";
  if (error.code === "email_provider_disabled" || error.code === "otp_disabled" || error.code === "signup_disabled") {
    return "Email sign-in isn't available right now. Use LinkedIn instead.";
  }
  return error.message || "Couldn't send the sign-in link. Try again.";
}

/**
 * Emails a one-time sign-in link (Supabase magic link). Only offered when
 * lib/auth/providers.ts allows email sign-in (off until SMTP is confirmed).
 *
 * `next` rides on the redirect URL as well as in the zynd_next cookie: the
 * link is often opened in a different tab or the mail app's browser, where
 * the cookie may be missing. The callback re-sanitizes it with safeNextPath,
 * so it can't be used as an open redirect.
 *
 * Returns null on success, or a message fit to show the user.
 */
export async function sendMagicLink(
  email: string,
  nextPath: string,
  intent?: "card",
): Promise<string | null> {
  const address = email.trim();
  if (!isPlausibleEmail(address)) return "Enter a valid email address.";

  const callback = new URL(prepareAuthRedirect(nextPath, intent));
  callback.searchParams.set("next", safeNextPath(nextPath) ? nextPath : "/");

  try {
    const { error } = await createClient().auth.signInWithOtp({
      email: address,
      options: { emailRedirectTo: callback.toString() },
    });
    return error ? magicLinkErrorMessage(error) : null;
  } catch (err) {
    console.error("[sendMagicLink] request failed:", err);
    return "Couldn't reach the sign-in service. Check your connection and try again.";
  }
}

export async function signOutAndLeave(path = "/"): Promise<void> {
  try {
    const { error } = await createClient().auth.signOut();
    if (error) console.error("Sign out failed:", error.message);
  } catch (err) {
    console.error("Sign out failed:", err);
  }
  clearNetworkCache();
  window.location.assign(new URL(path, clientOrigin()).toString());
}
