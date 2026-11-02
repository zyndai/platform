"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { goToSignIn } from "@/lib/auth/session";
import { markClaimIntent, takeClaimIntent } from "@/lib/claim-tokens";
import { useAuth } from "@/hooks/useAuth";
import { useMyCard } from "@/hooks/useMyCard";
import { CARDS_API } from "@/lib/cards";
import { track } from "@/lib/track";

interface ClaimBannerProps {
  handle: string;
  name: string;
}

/** S03: banner on unclaimed cards. Anyone signed in, with any sign-in method
 *  (Google, LinkedIn, email code), can claim a card; the only limit is one card
 *  per account (bar a duplicate of your own card, to merge), checked
 *  server-side, which also explains a refusal. A wrong claim is what "This isn't me" is
 *  for: it files a takedown and hides the card everywhere immediately. */
export function ClaimBanner({ handle, name }: ClaimBannerProps) {
  const { authenticated } = useAuth();
  const { ready: myCardReady, refresh: refreshMyCard } = useMyCard();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const autoClaimed = useRef(false);

  const claim = useCallback(async () => {
    setBusy(true);
    setError(null);
    track("claim_start", { handle }, handle);
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
      await refreshMyCard();
      router.refresh();
    } catch {
      setError("Claim failed — try again");
    } finally {
      setBusy(false);
    }
  }, [handle, router, refreshMyCard]);

  // Finish a claim by itself only right after a sign-in that started from
  // "Sign in to claim" on this card. Never just because a signed-in visitor
  // opened an unclaimed card: anyone may claim, so it has to be a choice.
  useEffect(() => {
    if (!authenticated || !myCardReady || autoClaimed.current) return;
    if (!takeClaimIntent(handle)) return;
    autoClaimed.current = true;
    queueMicrotask(() => void claim());
  }, [authenticated, myCardReady, handle, claim]);

  function signInToClaim() {
    track("claim_start", { handle }, handle);
    markClaimIntent(handle);
    goToSignIn(`/p/${encodeURIComponent(handle)}`);
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
        <button
          type="button"
          onClick={authenticated ? () => void claim() : signInToClaim}
          disabled={busy}
          style={{
            background: "#0B0B0B", color: "#fff", border: "none", borderRadius: 99,
            padding: "8px 16px", fontSize: 13, fontWeight: 700, cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "Claiming…" : authenticated ? "Claim this card" : "Sign in to claim"}
        </button>
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