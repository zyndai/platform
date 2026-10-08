"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { oauthCallbackUrl } from "@/lib/auth/origin";
import { useAuth } from "@/hooks/useAuth";
import { CARDS_API } from "@/lib/cards";

interface ClaimBannerProps {
  handle: string;
  name: string;
}

/** S03: banner on unclaimed cards. "Claim with LinkedIn" — the signed-in
 *  LinkedIn identity must match the card's LinkedIn URL (checked server-side).
 *  "Not me" files a takedown and hides the card everywhere immediately. */
export function ClaimBanner({ handle, name }: ClaimBannerProps) {
  const { authenticated } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoClaimed = useRef(false);

  const claim = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { data: { session } } = await createClient().auth.getSession();
      const token = session?.access_token;
      if (!token) {
        setError("Sign in first, then try again");
        return;
      }
      const res = await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/claim`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json().catch(() => ({})) as { detail?: unknown };
      if (!res.ok) {
        setError(typeof data.detail === "string" ? data.detail : "Claim failed — try again");
        return;
      }
      router.refresh();
    } catch {
      setError("Claim failed — try again");
    } finally {
      setBusy(false);
    }
  }, [handle, router]);

  // After a "claim with LinkedIn" sign-in round-trips back to this page,
  // attempt the claim once automatically.
  useEffect(() => {
    if (authenticated && !autoClaimed.current) {
      autoClaimed.current = true;
      void claim();
    }
  }, [authenticated, claim]);

  function signInToClaim() {
    setAuthNext(`/p/${encodeURIComponent(handle)}`, "card");
    void createClient().auth.signInWithOAuth({
      provider: "linkedin_oidc",
      options: { redirectTo: oauthCallbackUrl() },
    });
  }

  const reportNotMe = useCallback(async () => {
    if (!window.confirm("Hide this card? It will be removed from search and the directory while Zynd reviews the report.")) return;
    setBusy(true);
    setError(null);
    try {
      const { data: { session } } = await createClient().auth.getSession();
      await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/report-not-me`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
        },
        body: JSON.stringify({}),
      });
      router.refresh();
    } catch {
      setError("Could not file the report — try again");
    } finally {
      setBusy(false);
    }
  }, [handle, router]);

  return (
    <div
      style={{
        background: "#FFF7E6", border: "1px solid #F5D9A0", borderRadius: 16,
        padding: "14px 18px", marginBottom: 20, display: "flex", alignItems: "center",
        justifyContent: "space-between", gap: 14, flexWrap: "wrap",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "#7a4d00" }}>Is this you?</div>
        <div style={{ fontSize: 12.5, color: "#8a6d3b", marginTop: 2 }}>
          This card was assembled from public data and its owner hasn&apos;t claimed it yet.
          {error && <span style={{ color: "#b91c1c", fontWeight: 600 }}> {error}</span>}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        {authenticated ? (
          <button
            type="button"
            onClick={claim}
            disabled={busy}
            style={{
              background: "#0B0B0B", color: "#fff", border: "none", borderRadius: 99,
              padding: "8px 16px", fontSize: 13, fontWeight: 700, cursor: busy ? "wait" : "pointer",
            }}
          >
            {busy ? "Claiming…" : "Claim with LinkedIn"}
          </button>
        ) : (
          <button
            type="button"
            onClick={signInToClaim}
            disabled={busy}
            style={{
              background: "#0B0B0B", color: "#fff", border: "none", borderRadius: 99,
              padding: "8px 16px", fontSize: 13, fontWeight: 700, cursor: busy ? "wait" : "pointer",
            }}
          >
            {busy ? "Signing in…" : "Claim with LinkedIn"}
          </button>
        )}
        <button
          type="button"
          onClick={reportNotMe}
          disabled={busy}
          style={{
            background: "transparent", color: "#8a6d3b", border: "none",
            fontSize: 12, fontWeight: 600, textDecoration: "underline", cursor: "pointer", padding: "4px 6px",
          }}
        >
          This isn&apos;t {name.split(" ")[0]} — remove it
        </button>
      </div>
    </div>
  );
}