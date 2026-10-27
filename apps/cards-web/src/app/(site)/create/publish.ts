import { CARDS_API } from "@/lib/cards";
import type { AgentProfileCard } from "@/lib/cards";
import { claimHeaders, forgetClaimToken, saveClaimToken } from "@/lib/claim-tokens";
import { attrPublishFields } from "@/lib/attr";
import { cardDeclarations } from "@/lib/profile-quality";
import { createClient } from "@/lib/supabase/client";

// Memory layer (api.zynd.ai): the same host the /connect and /findable pages use.
const ZYND_API = process.env.NEXT_PUBLIC_ZYND_API_URL || "https://api.zynd.ai";
/** The memory layer takes at most this many declarations per batch. */
const MAX_DECLARATIONS = 50;

export async function getToken(): Promise<string | null> {
  const { data } = await createClient().auth.getSession();
  return data.session?.access_token ?? null;
}

export type PublishResult =
  | { kind: "existing"; handle: string }
  | { kind: "published"; handle: string; claimToken?: string };

/** Publishes the reviewed card. Throws with the API's message when it is refused. */
export async function publishCard(input: {
  jobId: string;
  card: AgentProfileCard;
  userAnswers: Record<string, string>;
  customHandle: string;
  ownerEmail: string | null;
  token: string | null;
}): Promise<PublishResult> {
  const res = await fetch(`${CARDS_API}/onboard/${input.jobId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(input.token ? { Authorization: `Bearer ${input.token}` } : {}) },
    body: JSON.stringify({
      card: input.card,
      user_answers: input.userAnswers,
      owner_email: input.ownerEmail,
      custom_handle: input.customHandle.length >= 2 ? input.customHandle : undefined,
      ...attrPublishFields(),
    }),
  });
  if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
  const body = await res.json();
  // One card per person: the API returns {existing, handle} instead of making a second one.
  if (body.existing) return { kind: "existing", handle: body.handle };
  return {
    kind: "published",
    handle: body.handle || body.id,
    claimToken: typeof body.claim_token === "string" ? body.claim_token : undefined,
  };
}

/** Anonymous publish: keep what the creator needs to edit or claim the card later. */
export function rememberPublished(handle: string, claimToken?: string): void {
  // The API returns a one-time claim token, needed to take ownership after signing in.
  if (claimToken) saveClaimToken(handle, claimToken);
  try {
    const stored: string[] = JSON.parse(localStorage.getItem("zynd_my_handles") || "[]");
    if (!stored.includes(handle)) stored.push(handle);
    localStorage.setItem("zynd_my_handles", JSON.stringify(stored));
  } catch { /* storage unavailable: the card is live either way */ }
}

/**
 * Seed the memory layer from the card, then pull the snapshot onto the card so
 * the public profile shows what the person is up to. Best-effort: nothing here
 * may stop a publish.
 */
export async function syncMemoryOnClaim(supabaseToken: string, handle: string, card: AgentProfileCard): Promise<void> {
  try {
    const ex = await fetch(`${ZYND_API}/token/exchange`, { method: "POST", headers: { Authorization: `Bearer ${supabaseToken}` } });
    if (!ex.ok) return;
    const { token: zyndToken } = await ex.json();
    if (!zyndToken) return;
    const declarations = cardDeclarations(card);
    if (declarations.length) {
      await fetch(`${ZYND_API}/me/findability/declare-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${zyndToken}` },
        body: JSON.stringify({ declarations: declarations.slice(0, MAX_DECLARATIONS) }),
      }).catch(() => { /* non-fatal */ });
    }
  } catch { /* non-fatal: memory is best-effort on claim */ }
  await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/refresh-memory`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  }).catch(() => { /* non-fatal */ });
}

/**
 * An anonymous publish is claimed by the first signed-in PATCH that carries
 * its claim token. Claiming also seeds the memory layer.
 */
export async function claimPublished(token: string, handle: string, card: AgentProfileCard): Promise<void> {
  try {
    const res = await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...claimHeaders(handle) },
      body: JSON.stringify(card),
    });
    if (res.ok) forgetClaimToken(handle);
  } catch { /* non-fatal: the card is live either way */ }
  await syncMemoryOnClaim(token, handle, card);
}

export async function handleIsFree(slug: string): Promise<boolean | null> {
  try {
    const res = await fetch(`${CARDS_API}/cards/handle-available/${encodeURIComponent(slug)}`);
    const data = await res.json();
    return data.available ?? false;
  } catch {
    return null;
  }
}
