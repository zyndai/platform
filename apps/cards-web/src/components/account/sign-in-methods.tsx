"use client";

/**
 * "Sign-in methods": connect Google or LinkedIn to the account you're signed
 * in with, even when they use a different email, so any of them opens the
 * same account and card. Card ownership follows the account's main email,
 * which linking never changes.
 *
 * Needs "manual linking" turned on in the Supabase project (Auth settings);
 * until then Supabase refuses and the reason is shown here.
 */

import { useCallback, useEffect, useState } from "react";
import type { UserIdentity } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { oauthCallbackUrl } from "@/lib/auth/origin";
import type { OAuthProvider } from "@/lib/auth/session";

const LINKABLE: { provider: OAuthProvider; label: string }[] = [
  { provider: "google", label: "Google" },
  { provider: "linkedin_oidc", label: "LinkedIn" },
];

function identityEmail(identity: UserIdentity): string {
  const data = (identity.identity_data ?? {}) as Record<string, unknown>;
  return String(data.email ?? "");
}

interface SignInState {
  email: string;
  identities: UserIdentity[];
  error: string | null;
}

async function fetchSignInState(): Promise<SignInState> {
  const supabase = createClient();
  const [{ data: userData }, { data, error }] = await Promise.all([
    supabase.auth.getUser(),
    supabase.auth.getUserIdentities(),
  ]);
  return {
    email: userData.user?.email ?? "",
    identities: data?.identities ?? [],
    error: error?.message ?? null,
  };
}

export function SignInMethods({ returnTo = "/home" }: { returnTo?: string }) {
  const [identities, setIdentities] = useState<UserIdentity[] | null>(null);
  const [accountEmail, setAccountEmail] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((state: SignInState, linkError?: string | null) => {
    setAccountEmail(state.email);
    setIdentities(state.identities);
    if (linkError || state.error) setError(linkError || state.error);
  }, []);

  useEffect(() => {
    // A link that failed on the provider side comes back as ?auth_error=… (see /auth/callback).
    const params = new URLSearchParams(window.location.search);
    const linkError = params.get("auth_error");
    if (linkError) {
      params.delete("auth_error");
      const query = params.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`);
    }
    fetchSignInState().then((state) => apply(state, linkError));
  }, [apply]);

  async function connect(provider: OAuthProvider) {
    setBusy(provider);
    setError(null);
    setAuthNext(returnTo);
    const { error: linkError } = await createClient().auth.linkIdentity({
      provider,
      options: { redirectTo: oauthCallbackUrl() },
    });
    if (linkError) {
      setError(linkError.message);
      setBusy(null);
    }
    // On success the browser is already on its way to the provider.
  }

  async function disconnect(identity: UserIdentity) {
    setBusy(identity.identity_id);
    setError(null);
    const { error: unlinkError } = await createClient().auth.unlinkIdentity(identity);
    if (unlinkError) setError(unlinkError.message);
    await createClient().auth.refreshSession();
    apply(await fetchSignInState());
    setBusy(null);
  }

  const canRemove = (identities?.length ?? 0) > 1;

  return (
    <section className="oh-panel oh-wide sim" aria-labelledby="sim-h">
      <p className="oh-eyebrow">Account</p>
      <h2 id="sim-h">Sign-in methods</h2>
      <p className="sim-lede">
        Connect your other accounts, even ones with a different email, so any of them signs you in
        here. Your card stays on {accountEmail ? <strong>{accountEmail}</strong> : "this account"}.
      </p>
      {error && <p role="alert" className="sim-error">{error}</p>}
      {identities === null ? (
        <p className="sim-lede">Loading…</p>
      ) : (
        <ul className="sim-list">
          {identities.some((i) => i.provider === "email") && (
            <li>
              <span><b>Email code</b><small>{accountEmail}</small></span>
            </li>
          )}
          {LINKABLE.map(({ provider, label }) => {
            const linked = identities.filter((i) => i.provider === provider);
            if (!linked.length) {
              return (
                <li key={provider}>
                  <span><b>{label}</b><small>Not connected</small></span>
                  <button type="button" className="oh-button oh-outline" disabled={busy !== null} onClick={() => void connect(provider)}>
                    {busy === provider ? "Opening…" : `Connect ${label}`}
                  </button>
                </li>
              );
            }
            return linked.map((identity) => (
              <li key={identity.identity_id}>
                <span><b>{label}</b><small>{identityEmail(identity) || "Connected"}</small></span>
                {canRemove && (
                  <button
                    type="button"
                    className="oh-text-link"
                    disabled={busy !== null}
                    onClick={() => void disconnect(identity)}
                  >
                    {busy === identity.identity_id ? "Removing…" : "Remove"}
                  </button>
                )}
              </li>
            ));
          })}
        </ul>
      )}
    </section>
  );
}
