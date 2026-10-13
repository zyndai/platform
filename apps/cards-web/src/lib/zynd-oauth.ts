/**
 * Zynd OAuth hand-off for MCP / ChatGPT connectors.
 *
 * /oauth/authorize redirects here with a signed `?zynd_oauth=<req>`. We stash it,
 * use the Supabase session already on cards (LinkedIn or any trusted provider),
 * then POST that session to memory's /oauth/complete and bounce back to Claude.
 */
const KEY = "zynd_oauth_req";
const MEMORY_API = (process.env.NEXT_PUBLIC_ZYND_API_URL || process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

export function captureZyndOAuthReq(): void {
  if (typeof window === "undefined") return;
  const req = new URLSearchParams(window.location.search).get("zynd_oauth");
  if (!req) return;
  try {
    window.sessionStorage.setItem(KEY, req);
  } catch {
    /* sessionStorage unavailable; hand-off simply won't complete */
  }
}

export function hasPendingZyndOAuth(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return !!window.sessionStorage.getItem(KEY);
  } catch {
    return false;
  }
}

export async function completeZyndOAuth(accessToken: string | undefined): Promise<string | null> {
  if (typeof window === "undefined" || !accessToken || !MEMORY_API) return "Not signed in.";
  let req: string | null = null;
  try {
    req = window.sessionStorage.getItem(KEY);
  } catch {
    return "Couldn't read the connector request.";
  }
  if (!req) return null;

  try {
    const res = await fetch(`${MEMORY_API}/oauth/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ req, supabase_token: accessToken }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : `oauth/complete returned ${res.status}`;
      throw new Error(detail);
    }
    if (typeof data.redirect_url !== "string" || !data.redirect_url) throw new Error("no redirect_url");
    window.sessionStorage.removeItem(KEY);
    window.location.href = data.redirect_url;
    return null;
  } catch (e) {
    const message = e instanceof Error ? e.message : "Connector sign-in failed.";
    console.warn("[zynd-oauth] hand-off failed:", e);
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    return message;
  }
}
