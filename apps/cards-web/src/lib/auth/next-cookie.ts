const NEXT_COOKIE = "zynd_next";
const INTENT_COOKIE = "zynd_intent";

function isSafePath(path: string): boolean {
  return path.startsWith("/") && !path.startsWith("//") && !path.includes("\\");
}

/** Decode if encoded; reject absolute / protocol-relative values. */
export function safeNextPath(raw: string | null | undefined): string | null {
  if (!raw) return null;
  let value = raw;
  try {
    value = decodeURIComponent(raw);
  } catch {
    value = raw;
  }
  return isSafePath(value) ? value : null;
}

export function setAuthNext(path: string, intent?: "card"): void {
  const next = isSafePath(path) ? path : "/agent-card";
  document.cookie = `${NEXT_COOKIE}=${encodeURIComponent(next)}; path=/; samesite=lax`;
  if (intent === "card") {
    document.cookie = `${INTENT_COOKIE}=card; path=/; samesite=lax`;
  }
}

export function setClaimHandle(handle: string): void {
  const slug = handle.replace(/[^a-z0-9-]/gi, "").slice(0, 40);
  if (!slug) return;
  document.cookie = `zynd_claim_handle=${slug}; path=/; samesite=lax`;
  setAuthNext(`/p/${slug}`, "card");
}
