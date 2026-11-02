// Asks: the kinds, the link rules and the owner's calls (cards-api POST/DELETE /cards/mine/ask and
// GET /cards/mine/asks). No runtime imports, so `node --test` can load this file without the "@/" alias.

/** What an ask is for, in the order the composer lists them. Mirrors ASK_KINDS in cards-api
 *  models/card.py, the one place the server keeps them. A beacon without a kind reads as "other". */
export const ASK_KINDS = [
  { id: "team", label: "Building a team", placeholder: "Building a team for ETHGlobal Bangkok, need a Solidity dev and a designer" },
  { id: "cofounder", label: "Looking for a co-founder", placeholder: "Looking for a technical co-founder for a B2B payments idea, Bangalore or remote" },
  { id: "hiring", label: "Hiring", placeholder: "Hiring two backend engineers (Go, Postgres), remote in India" },
  { id: "work", label: "Open to work", placeholder: "Open to work: senior frontend engineer, React and TypeScript, remote or Berlin" },
  { id: "feedback", label: "Want feedback", placeholder: "Want honest feedback on my pitch deck for a seed round, 12 slides" },
  { id: "users", label: "Looking for early users", placeholder: "Looking for 20 early users to try my invoicing tool for freelancers" },
  { id: "investors", label: "Raising money", placeholder: "Raising a pre-seed for a developer tool, looking for angels who back infra" },
  { id: "other", label: "Something else", placeholder: "Say what you need in a sentence or two" },
] as const;

export type AskKind = (typeof ASK_KINDS)[number]["id"];

export const ASK_TEXT_MAX = 280;
export const ASK_URL_MAX = 500;
/** An ask stays up this long (the server sets the real expiry). */
export const ASK_LIFETIME_DAYS = 7;

export function isAskKind(value: unknown): value is AskKind {
  return ASK_KINDS.some((k) => k.id === value);
}

/** The label for a kind; a missing or unknown kind is "Something else". */
export function kindLabel(kind: string | null | undefined): string {
  return ASK_KINDS.find((k) => k.id === kind)?.label ?? "Something else";
}

/** A link on an ask: empty is fine, otherwise a web address starting http:// or https:// (the server
 *  checks the same). Returns the trimmed link, or an error to show next to the field. */
export function validateAskUrl(raw: string): { ok: true; url: string | null } | { ok: false; error: string } {
  const text = raw.trim();
  if (!text) return { ok: true, url: null };
  if (text.length > ASK_URL_MAX) return { ok: false, error: `The link can be at most ${ASK_URL_MAX} characters.` };
  if (/\s/.test(text)) return { ok: false, error: "The link can't contain spaces." };
  let parsed: URL;
  try {
    parsed = new URL(text);
  } catch {
    return { ok: false, error: "Use a web address that starts with http:// or https://" };
  }
  if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.hostname) {
    return { ok: false, error: "Use a web address that starts with http:// or https://" };
  }
  return { ok: true, url: text };
}

/** Only http(s) links are drawn: an ask's link comes from other people. */
export function safeAskUrl(url: string | null | undefined): string {
  return typeof url === "string" && validateAskUrl(url).ok && /^https?:\/\//i.test(url.trim()) ? url.trim() : "";
}

/** "ethglobal.com" for a link; the link itself when it cannot be parsed. */
export function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** The owner's live ask as the composer and the "Your live ask" card need it. `routed` and
 *  `offer_count` are 0 when unknown (right after posting, or on the edit page). */
export interface LiveAsk {
  id: string;
  text: string;
  kind: AskKind | null;
  url: string | null;
  created_at: string;
  expires_at: string;
  routed: number;
  offer_count: number;
}

interface BeaconLike {
  id?: string | null;
  text: string;
  kind?: string | null;
  url?: string | null;
  created_at: string;
  expires_at: string;
}

/** A live ask from a card's beacon (null when there is none or it has run out). */
export function liveFromBeacon(beacon: BeaconLike | null | undefined, nowMs: number): LiveAsk | null {
  if (!beacon || !(Date.parse(beacon.expires_at) > nowMs) || !(Date.parse(beacon.created_at) <= nowMs)) return null;
  return liveFromPosted(beacon);
}

/** The ask the server just saved, as it answered. No clock check: the server's word is the truth. */
export function liveFromPosted(beacon: BeaconLike): LiveAsk {
  return {
    id: beacon.id ?? "",
    text: beacon.text,
    kind: isAskKind(beacon.kind) ? beacon.kind : null,
    url: beacon.url ?? null,
    created_at: beacon.created_at,
    expires_at: beacon.expires_at,
    routed: 0,
    offer_count: 0,
  };
}

/** "Ends in 5 days", "Ends in 1 day", "Ends today". */
export function endsIn(expiresAt: string, nowMs: number): string {
  const ms = Date.parse(expiresAt) - nowMs;
  if (!Number.isFinite(ms) || ms <= 0) return "Ended";
  if (ms < 86_400_000) return "Ends today";
  const days = Math.round(ms / 86_400_000);     // a fresh 7-day ask reads "7 days", not "6"
  return `Ends in ${days} ${days === 1 ? "day" : "days"}`;
}

/** An error from the asks API with its status, so the composer can word a 429 or a 409 itself. */
export class AskError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

async function call(token: string, method: string, path: string, body?: unknown): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API}/cards/${path}`, {
      method,
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new AskError(0, "Couldn't reach Zynd. Check your connection and try again.");
  }
  if (response.ok) return response;
  throw new AskError(response.status, await errorMessage(response));
}

async function errorMessage(response: Response): Promise<string> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    /* fall through to the generic wording */
  }
  if (typeof detail === "string" && detail) return detail;
  if (response.status === 422) return "Check your ask and try again.";
  if (response.status === 401) return "Your session ended. Sign in again to post.";
  if (response.status === 404) return "Create your card first.";
  return "Could not save your ask. Please try again.";
}

/** Post an ask. 429 (too many today), 409 (your card changed) and 422 come back as an AskError with the
 *  server's own wording. */
export async function postAsk(
  token: string,
  ask: { kind: AskKind; text: string; url: string | null },
): Promise<{ beacon: BeaconLike; ask_id: string }> {
  const response = await call(token, "POST", "mine/ask", { kind: ask.kind, text: ask.text, ...(ask.url ? { url: ask.url } : {}) });
  return response.json();
}

export async function takeDownAsk(token: string): Promise<void> {
  await call(token, "DELETE", "mine/ask");
}

/** The owner's live ask with its counts, or null (no ask, no card, or the API is unavailable: the page
 *  works without it). */
export async function fetchLiveAsk(token: string, nowMs: number): Promise<LiveAsk | null> {
  try {
    const response = await call(token, "GET", "mine/asks");
    const body = (await response.json()) as { asks?: (BeaconLike & { status?: string; routed?: number; offer_count?: number })[] };
    const live = (body.asks ?? []).find((a) => a.status === "active");
    if (!live) return null;
    return { ...(liveFromBeacon(live, nowMs) as LiveAsk), routed: live.routed ?? 0, offer_count: live.offer_count ?? 0 };
  } catch {
    return null;
  }
}
