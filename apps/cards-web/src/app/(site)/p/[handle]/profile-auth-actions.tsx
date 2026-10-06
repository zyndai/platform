"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { getMyCard, updateCard, type AgentProfileCard } from "@/lib/cards";
import { hasClaimToken, markClaimIntent, subscribeClaimTokens, takeClaimIntent } from "@/lib/claim-tokens";
import { useAuth } from "@/hooks/useAuth";

const PILL_CLASS =
  "inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full font-mono text-[12px]! font-semibold cursor-pointer hover:opacity-90 transition-opacity disabled:opacity-60";
const PILL_STYLE = { background: "#7B72E9", color: "#fff", border: "none" };

/**
 * Only the browser that published a card anonymously holds its one-time claim
 * token, so that's what makes a visitor "the creator". False on the server and
 * during hydration; the real answer comes from localStorage right after.
 */
function useCanClaim(handle: string): boolean {
  return useSyncExternalStore(subscribeClaimTokens, () => hasClaimToken(handle), () => false);
}

/** Signed-out header action: "Claim this card" for its creator, "Sign In" for everyone else. */
export function ProfileSignIn({ handle }: { handle: string }) {
  const canClaim = useCanClaim(handle);

  function signIn() {
    if (canClaim) markClaimIntent(handle);
    setAuthNext(`/p/${encodeURIComponent(handle)}`, "card");
    createClient().auth.signInWithOAuth({
      provider: "linkedin_oidc",
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  }

  return (
    <button type="button" onClick={signIn} className={PILL_CLASS} style={PILL_STYLE}>
      {canClaim ? "Claim this card" : "Sign In"}
    </button>
  );
}

/**
 * Signed-in, not-yet-owner header action. Shown only to the card's creator;
 * claims on click, or by itself right after a sign-in that started from
 * "Claim this card". On success the server re-renders the header with Edit.
 */
export function ClaimCardButton({ handle, card }: { handle: string; card: AgentProfileCard }) {
  const router = useRouter();
  const canClaim = useCanClaim(handle);
  const [status, setStatus] = useState<"idle" | "claiming" | "failed" | "has-card">("idle");
  const autoClaimed = useRef(false);

  const claim = useCallback(async () => {
    setStatus("claiming");
    try {
      const { data: { session } } = await createClient().auth.getSession();
      const token = session?.access_token;
      if (!token) throw new Error("no session");
      // One card per account: an account that already owns a card can't take this one too.
      const mine = await getMyCard(token);
      if (mine?.handle) {
        setStatus("has-card");
        return;
      }
      if (!(await updateCard(handle, card, token))) throw new Error("claim refused");
      router.refresh();
    } catch (err) {
      console.error("[ClaimCardButton] failed:", err);
      setStatus("failed");
    }
  }, [handle, card, router]);

  useEffect(() => {
    if (!canClaim || autoClaimed.current || !takeClaimIntent(handle)) return;
    autoClaimed.current = true;
    claim();
  }, [canClaim, handle, claim]);

  if (!canClaim) return null;
  if (status === "has-card") {
    return (
      <span className="font-mono text-[11px] font-semibold text-slate-500">
        Your account already has a card
      </span>
    );
  }
  return (
    <button type="button" onClick={claim} disabled={status === "claiming"} className={PILL_CLASS} style={PILL_STYLE}>
      {status === "claiming" ? "Claiming…" : status === "failed" ? "Claim failed · retry" : "Claim this card"}
    </button>
  );
}

/** Signed-in header action: lets anyone who is signed in sign back out. */
export function ProfileSignOut() {
  const { authenticated, logout } = useAuth();
  if (!authenticated) return null;
  return (
    <button
      type="button"
      onClick={() => logout()}
      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full font-mono text-[12px]! font-semibold cursor-pointer hover:opacity-90 transition-opacity"
      style={{ background: "transparent", color: "#64748b", border: "1px solid #e2e8f0" }}
    >
      Sign out
    </button>
  );
}
