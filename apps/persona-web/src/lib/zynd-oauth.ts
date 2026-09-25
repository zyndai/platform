/**
 * Zynd OAuth hand-off (front-door flow).
 *
 * When a user arrives via Zynd's ChatGPT/MCP OAuth, Zynd redirects them here with a
 * signed `?zynd_oauth=<req>`. We stash it, let them sign in and finish persona
 * onboarding, then — once onboarding is done — POST the verified Supabase session to
 * Zynd's /oauth/complete and redirect the browser back to the original client.
 *
 * The req lives in sessionStorage so it survives the Supabase OAuth bounce (same
 * origin, same tab) and the multi-step onboarding navigation.
 */
const KEY = "zynd_oauth_req";
// Default to the prod API when NEXT_PUBLIC_MEMORY_API_URL is unset — matches
// dashboard/connect and settings/you. Without this, an empty base made
// completeZyndOAuth() silently no-op, trapping already-signed-in users on the
// persona dashboard instead of bouncing back to the OAuth client.
const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

/** Capture `?zynd_oauth` from the current URL into sessionStorage, if present. */
export function captureZyndOAuthReq(): void {
  if (typeof window === "undefined") return;
  const req = new URLSearchParams(window.location.search).get("zynd_oauth");
  if (!req) return;
  try {
    window.sessionStorage.setItem(KEY, req);
  } catch {
    /* sessionStorage unavailable (private mode); hand-off simply won't complete */
  }
}

/**
 * If a Zynd hand-off is pending, finish it: exchange the Supabase session for a Zynd
 * auth code and redirect the browser back to the original client. Returns true once it
 * has taken over navigation (caller should stop its own routing).
 *
 * Best-effort: on any failure it clears the pending req and returns false so the user
 * lands in the persona dashboard instead of being trapped in a redirect loop.
 */
export async function completeZyndOAuth(accessToken: string | undefined): Promise<boolean> {
  if (typeof window === "undefined" || !accessToken || !MEMORY_API) return false;
  let req: string | null = null;
  try {
    req = window.sessionStorage.getItem(KEY);
  } catch {
    return false;
  }
  if (!req) return false;

  try {
    const res = await fetch(`${MEMORY_API}/oauth/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ req, supabase_token: accessToken }),
    });
    if (!res.ok) throw new Error(`oauth/complete returned ${res.status}`);
    const { redirect_url } = await res.json();
    if (typeof redirect_url !== "string" || !redirect_url) throw new Error("no redirect_url");
    window.sessionStorage.removeItem(KEY);
    window.location.href = redirect_url;
    return true;
  } catch (e) {
    console.warn("[zynd-oauth] hand-off failed:", e);
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    return false;
  }
}
