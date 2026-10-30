/**
 * One-time claim tokens for cards published before signing in.
 *
 * An anonymous publish returns `claim_token`; the cards API only lets a
 * signed-in user take ownership of that unowned card when the same token is
 * sent back as `X-Claim-Token`. Kept in localStorage next to the
 * `zynd_my_handles` list so the creator can claim after the OAuth round-trip.
 */
const KEY = "zynd_claim_tokens";

function read(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function write(tokens: Record<string, string>): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(tokens));
  } catch {
    /* storage unavailable — claiming just won't be possible from this browser */
  }
}

export function saveClaimToken(handle: string, token: string): void {
  write({ ...read(), [handle]: token });
}

export function forgetClaimToken(handle: string): void {
  const tokens = read();
  if (handle in tokens) {
    delete tokens[handle];
    write(tokens);
  }
}

/** Did this browser publish `handle` anonymously, and so can still claim it? */
export function hasClaimToken(handle: string): boolean {
  return typeof read()[handle] === "string";
}

/** useSyncExternalStore subscription: another tab publishing or claiming changes the answer. */
export function subscribeClaimTokens(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY || e.key === null) onChange();
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}

// Survives the LinkedIn OAuth round-trip (same tab, same origin) so the claim
// can finish on return without a second click.
const INTENT_KEY = "zynd_claim_intent";

export function markClaimIntent(handle: string): void {
  try {
    sessionStorage.setItem(INTENT_KEY, handle);
  } catch {
    /* storage unavailable — the claim button still works, it just needs a click */
  }
}

// An email magic link finishes the sign-in in a new tab, which can't read this
// tab's sessionStorage, so the email path copies the intent here. It lives as
// long as the link does (an hour, per the "check your email" notice).
const CROSS_TAB_INTENT_KEY = "zynd_claim_intent_xtab";
const CROSS_TAB_INTENT_TTL_MS = 60 * 60 * 1000;

/** Call when a sign-in that finishes in another tab starts: carries this tab's claim intent, if any, over to it. */
export function shareClaimIntentAcrossTabs(): void {
  let handle: string | null;
  try {
    handle = sessionStorage.getItem(INTENT_KEY);
  } catch {
    return; // storage unavailable — no intent was saved to carry
  }
  if (!handle) return;
  try {
    localStorage.setItem(CROSS_TAB_INTENT_KEY, JSON.stringify({ handle, expiresAt: Date.now() + CROSS_TAB_INTENT_TTL_MS }));
  } catch (err) {
    console.warn("claim intent: could not keep a copy for the sign-in link's tab", err);
  }
}

function readCrossTabIntent(): string | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(CROSS_TAB_INTENT_KEY) || "null") as { handle?: unknown; expiresAt?: unknown } | null;
    const fresh = typeof parsed?.expiresAt === "number" && parsed.expiresAt > Date.now();
    return fresh && typeof parsed?.handle === "string" ? parsed.handle : null;
  } catch {
    return null;
  }
}

/** True once, right after a sign-in started from "Claim this card" on `handle`.
 *  Taking it clears both copies, so the original tab and the magic-link tab can't both auto-claim. */
export function takeClaimIntent(handle: string): boolean {
  let sameTab = false;
  try {
    sameTab = sessionStorage.getItem(INTENT_KEY) === handle;
    if (sameTab) sessionStorage.removeItem(INTENT_KEY);
  } catch {
    sameTab = false;
  }
  const crossTab = readCrossTabIntent() === handle;
  if (crossTab) {
    try {
      localStorage.removeItem(CROSS_TAB_INTENT_KEY);
    } catch (err) {
      console.warn("claim intent: could not clear the cross-tab copy", err);
    }
  }
  return sameTab || crossTab;
}

/** `{ "X-Claim-Token": … }` when this browser published `handle` anonymously. */
export function claimHeaders(handle: string): Record<string, string> {
  const token = read()[handle];
  return token ? { "X-Claim-Token": token } : {};
}
