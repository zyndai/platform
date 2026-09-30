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

/** True once, right after a sign-in started from "Claim this card" on `handle`. */
export function takeClaimIntent(handle: string): boolean {
  try {
    if (sessionStorage.getItem(INTENT_KEY) !== handle) return false;
    sessionStorage.removeItem(INTENT_KEY);
    return true;
  } catch {
    return false;
  }
}

/** `{ "X-Claim-Token": … }` when this browser published `handle` anonymously. */
export function claimHeaders(handle: string): Record<string, string> {
  const token = read()[handle];
  return token ? { "X-Claim-Token": token } : {};
}
