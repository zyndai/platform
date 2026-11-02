"use client";

import { createClient } from "@/lib/supabase/client";
import { clearNetworkCache } from "@/lib/network-cache";
import { safeNextPath, setAuthNext } from "@/lib/auth/next-cookie";
import { clientOrigin, oauthCallbackUrl } from "@/lib/auth/origin";

/** The OAuth providers Cards offers. Email is a 6-digit code (sendEmailCode). */
export type OAuthProvider = "google" | "linkedin_oidc";

export async function startOAuth(
  provider: OAuthProvider,
  nextPath: string,
  intent?: "card",
): Promise<string | null> {
  setAuthNext(nextPath, intent);
  const { error } = await createClient().auth.signInWithOAuth({
    provider,
    options: { redirectTo: oauthCallbackUrl() },
  });
  return error ? error.message : null;
}

/** The sign-in page, returning to `nextPath` afterwards. Every "Sign in" and
 *  "Claim" button goes here, so Google, LinkedIn and the email code are offered
 *  in one place instead of each button picking a provider. */
export function signInHref(nextPath: string): string {
  const next = safeNextPath(nextPath) ?? "/";
  return `/auth?next=${encodeURIComponent(next)}`;
}

export function goToSignIn(nextPath: string): void {
  window.location.assign(new URL(signInHref(nextPath), clientOrigin()).toString());
}

/** Email the 6-digit sign-in code. Creates the account on first use. */
export async function sendEmailCode(email: string): Promise<string | null> {
  const { error } = await createClient().auth.signInWithOtp({
    email,
    options: { shouldCreateUser: true },
  });
  return error ? error.message : null;
}

/** Check the code from the email; on success the session cookies are set. */
export async function verifyEmailCode(email: string, code: string): Promise<string | null> {
  const { error } = await createClient().auth.verifyOtp({ email, token: code, type: "email" });
  return error ? error.message : null;
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
