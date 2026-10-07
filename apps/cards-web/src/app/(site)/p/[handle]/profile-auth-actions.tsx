"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { oauthCallbackUrl } from "@/lib/auth/origin";
import { getMyCard, updateCard, type AgentProfileCard } from "@/lib/cards";
import { hasClaimToken, markClaimIntent, subscribeClaimTokens, takeClaimIntent } from "@/lib/claim-tokens";
import { useAuth } from "@/hooks/useAuth";
import { useMyCard } from "@/hooks/useMyCard";
import { displayUserName, initialsOf, pickUserAvatar } from "@/lib/identity";
import { imgProxyUrl } from "@/lib/avatar";

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
      options: { redirectTo: oauthCallbackUrl() },
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

/** Signed-in header action: the visitor's own identity — photo, name, sign out.
 *  Replaces the bare "Sign out" button so the header always answers "who am I
 *  here as?" instead of only offering an exit. The photo prefers the LinkedIn
 *  profile picture (Google default avatars would otherwise win), with a
 *  second URL and initials as fallbacks. */
export function ProfileAccountChip() {
  const { authenticated, user, logout } = useAuth();
  const { card: myCard } = useMyCard();
  const md = (user?.user_metadata ?? {}) as Record<string, unknown>;
  const { primary, secondary } = pickUserAvatar(md);
  const avatarSrc = imgProxyUrl(primary, secondary);
  const [failed, setFailed] = useState(false);
  if (!authenticated) return null;

  const authName = displayUserName(md, user?.email);
  const cardName = (myCard?.identity?.name ?? "").trim();
  const name = cardName || authName;
  const initials = initialsOf(name);

  return (
    <span
      className="inline-flex items-center gap-2 pl-1 pr-2 py-1 rounded-full font-mono text-[12px]! font-semibold"
      style={{ background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0" }}
    >
      {avatarSrc && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={avatarSrc}
          alt=""
          onError={() => setFailed(true)}
          style={{ width: 24, height: 24, borderRadius: "50%", objectFit: "cover", display: "block", flexShrink: 0 }}
        />
      ) : (
        <span style={{
          width: 24, height: 24, borderRadius: "50%", background: "#7B72E9", color: "#fff",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          fontSize: "10px", fontWeight: 700, flexShrink: 0,
        }}>
          {initials}
        </span>
      )}
      <span style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {name}
      </span>
      <button
        type="button"
        onClick={() => logout()}
        title="Sign out"
        aria-label="Sign out"
        className="inline-flex items-center gap-1 cursor-pointer"
        style={{
          background: "transparent", border: "none", padding: "4px 6px", borderRadius: 8,
          color: "#64748b", fontSize: "11px", fontWeight: 600, fontFamily: "inherit",
        }}
      >
        Sign out
      </button>
    </span>
  );
}
