"use client";

import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { clientOrigin, oauthCallbackUrl } from "@/lib/auth/origin";

export async function startLinkedInOAuth(
  nextPath: string,
  intent?: "card",
): Promise<string | null> {
  setAuthNext(nextPath, intent);
  const { error } = await createClient().auth.signInWithOAuth({
    provider: "linkedin_oidc",
    options: { redirectTo: oauthCallbackUrl() },
  });
  return error ? error.message : null;
}

export async function signOutAndLeave(path = "/"): Promise<void> {
  try {
    const { error } = await createClient().auth.signOut();
    if (error) console.error("Sign out failed:", error.message);
  } catch (err) {
    console.error("Sign out failed:", err);
  }
  window.location.assign(new URL(path, clientOrigin()).toString());
}
