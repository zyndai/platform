// Types, fetch helper and pure helpers for the action feed (cards-api GET /cards/feed).
// No runtime imports here, so `node --test` can load this file without the "@/" alias.

import type { AskKind } from "./asks";

export type FeedKind = "ask" | "working_on" | "exploring" | "joined" | "github" | "post";
export type FeedFilter = "all" | "asks" | "network";

export const FEED_FILTERS: { id: FeedFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "asks", label: "Asks" },
  { id: "network", label: "People you know" },
];

/** How the viewer stands with the author; null when there is no connection row. `incoming` is true
 *  when the author asked and the viewer is the one who can answer. The server leaves out anyone the
 *  viewer is blocked from, declined or revoked, so only these two states reach the page. */
export interface FeedConnection {
  id: string;
  status: "pending" | "accepted";
  incoming: boolean;
}

export interface FeedAuthor {
  handle: string;
  name: string;
  headline: string;
  avatar_url: string | null;
  location: string;
  claimed: boolean;
}

export type GithubItemType = "release" | "repo" | "pull_request";

interface FeedItemBase {
  /** Stable between requests: kind + handle + a key for the source. */
  id: string;
  /** When the thing happened (ISO 8601). */
  at: string;
  /** Older than the recent window: shown after every recent item, under an "Earlier" divider. */
  earlier: boolean;
  /** Why the viewer is seeing it ("You're connected", ...); empty when nothing specific applies. */
  reason: string;
  author: FeedAuthor;
  connection: FeedConnection | null;
}

export type FeedItem =
  | (FeedItemBase & { kind: "ask"; content: { text: string; kind: AskKind; url: string | null } })
  | (FeedItemBase & { kind: "working_on"; content: { text: string } })
  | (FeedItemBase & { kind: "exploring"; content: { title: string; url: string; note: string; kind: string } })
  | (FeedItemBase & { kind: "joined"; content: { headline: string; can_help_with: string[] } })
  | (FeedItemBase & { kind: "github"; content: { type: GithubItemType; repo: string; title: string; url: string } })
  | (FeedItemBase & { kind: "post"; content: { platform: "linkedin" | "x"; preview: string; url: string } });

export interface FeedPage {
  items: FeedItem[];
  next_cursor: string | null;
  /** has_card is false for someone who has not created a Card yet: replying needs one. */
  viewer: {
    has_card: boolean;
    handle: string | null;
    /** The viewer's own identity, so the ask composer can preview a post as it will look. */
    name?: string;
    headline?: string;
    avatar_url?: string | null;
    location?: string;
  };
}

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

/** One page of the feed. Works on the server (first page) and in the browser (load more). */
export async function fetchFeed(
  token: string,
  options: { filter?: FeedFilter; kind?: AskKind | null; cursor?: string | null; signal?: AbortSignal } = {},
): Promise<FeedPage> {
  const params = new URLSearchParams();
  if (options.filter && options.filter !== "all") params.set("filter", options.filter);
  if (options.kind && options.filter === "asks") params.set("kind", options.kind);
  if (options.cursor) params.set("cursor", options.cursor);
  const query = params.toString();
  const response = await fetch(`${API}/cards/feed${query ? `?${query}` : ""}`, {
    cache: "no-store",
    signal: options.signal,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    let detail = "Could not load your feed";
    try { detail = (await response.json()).detail || detail; } catch { /* keep the fallback */ }
    throw new Error(detail);
  }
  return response.json() as Promise<FeedPage>;
}

/** The server's answer to a reply: it picked the channel from the real connection state. */
export interface FeedReplyResult {
  channel: "dm" | "request";
  connection: FeedConnection;
}

/** Reply to a feed item. The server decides between a message and a connection request, applies the
 *  request limits and refuses blocked or hidden people; its own message (a 409, a 429...) is the error. */
export async function replyToFeedItem(
  token: string,
  itemId: string,
  message: string,
  clientId: string,
): Promise<FeedReplyResult> {
  const response = await fetch(`${API}/cards/feed/reply`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: itemId, message, client_id: clientId }),
  });
  if (!response.ok) {
    let detail = "Could not send. Please try again.";
    try {
      const body = await response.json();
      // Validation errors arrive as a list; a plain string is the server's own message.
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* keep the fallback */ }
    throw new Error(detail);
  }
  return response.json() as Promise<FeedReplyResult>;
}

export function parseFilter(raw: string | string[] | null | undefined): FeedFilter {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === "asks" || value === "network" ? value : "all";
}

/** The asks tab's kind chip from the URL (?kind=team); anything else is "all kinds". */
export function parseKind(raw: string | string[] | null | undefined): AskKind | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && Object.hasOwn(ASK_REPLY, value) ? (value as AskKind) : null;
}

export const KIND_LABEL: Record<FeedKind, string> = {
  ask: "Ask",
  working_on: "Working on",
  exploring: "Exploring",
  joined: "New on Zynd",
  github: "GitHub",
  post: "Post",
};

/** "just now", "5m ago", "3h ago", "2d ago", "3w ago". */
export function relativeTime(iso: string, nowMs: number): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const minutes = Math.floor(Math.max(nowMs - then, 0) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return days < 14 ? `${days}d ago` : `${Math.floor(days / 7)}w ago`;
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] || "there";
}

/** What the single action button on an item says and what the message starts with. */
export interface FeedReply {
  label: string;
  prefill: string;
}

/** The API accepts up to 2000 characters on a connection request note and 4000 on a message. */
export const MAX_REPLY_LENGTH = 2000;

const PLATFORM_NAME = { linkedin: "LinkedIn", x: "X" } as const;

/** The reply button and the start of the message for each kind of ask (`hi` is "Hi Ana, "). An ask with
 *  no kind, or "other", gets the general offer of help. The reply still goes through the same endpoint,
 *  so the offer is recorded whichever words start it. */
export const ASK_REPLY: Record<AskKind, { label: string; prefill: (hi: string, text: string) => string }> = {
  team: { label: "I'm in", prefill: (hi) => `${hi}I'd like to join your team: ` },
  cofounder: { label: "Let's talk", prefill: (hi) => `${hi}I'd like to talk about co-founding: ` },
  hiring: { label: "I'm interested", prefill: (hi) => `${hi}I'm interested in the role: ` },
  work: { label: "I might have something", prefill: (hi) => `${hi}I might have something for you: ` },
  feedback: { label: "Give feedback", prefill: (hi) => `${hi}happy to give feedback: ` },
  users: { label: "I'll try it", prefill: (hi) => `${hi}I'd like to try it: ` },
  investors: { label: "Let's talk", prefill: (hi) => `${hi}I'd like to hear more: ` },
  other: { label: "I can help", prefill: (hi, text) => `${hi}I can help with "${text}": ` },
};

export function replyFor(item: FeedItem): FeedReply {
  const hi = `Hi ${firstName(item.author.name)}, `;
  let reply: FeedReply;
  switch (item.kind) {
    case "ask":
      {
        const ask = Object.hasOwn(ASK_REPLY, item.content.kind) ? ASK_REPLY[item.content.kind] : ASK_REPLY.other;
        reply = { label: ask.label, prefill: ask.prefill(hi, item.content.text) };
      }
      break;
    case "working_on":
      reply = { label: "Me too", prefill: `${hi}"${item.content.text}" caught my eye, I'm into this too. ` };
      break;
    case "joined":
      reply = { label: "Welcome", prefill: `${hi}welcome to Zynd! ` };
      break;
    case "github":
      if (item.content.type === "release") {
        reply = { label: "Congratulate", prefill: `${hi}congrats on the ${item.content.title || item.content.repo} release! ` };
      } else if (item.content.type === "pull_request") {
        reply = { label: "Congratulate", prefill: `${hi}congrats on getting "${item.content.title}" merged into ${item.content.repo}! ` };
      } else {
        reply = { label: "Say hi", prefill: `${hi}saw your new repo ${item.content.repo}. ` };
      }
      break;
    case "exploring":
      reply = { label: "Say hi", prefill: `${hi}saw you're exploring "${item.content.title}". ` };
      break;
    case "post":
      reply = { label: "Say hi", prefill: `${hi}enjoyed your post on ${PLATFORM_NAME[item.content.platform] ?? "the web"}. ` };
      break;
  }
  return { ...reply, prefill: reply.prefill.slice(0, MAX_REPLY_LENGTH) };
}

/** What can be done about an item, from the viewer's side. */
export type FeedAction =
  | { kind: "create-card" }
  | { kind: "reply"; via: "dm" | "request"; connectionId?: string }
  | { kind: "requested" }
  | { kind: "respond"; connectionId: string };

export function actionFor(hasCard: boolean, connection: FeedConnection | null): FeedAction {
  if (!hasCard) return { kind: "create-card" };
  if (!connection) return { kind: "reply", via: "request" };
  if (connection.status === "accepted") return { kind: "reply", via: "dm", connectionId: connection.id };
  return connection.incoming ? { kind: "respond", connectionId: connection.id } : { kind: "requested" };
}

/** Only http(s) links are drawn: they come from other people's cards. */
export function safeHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : "";
}

/** Why someone can report a person's card, as cards-api accepts them. */
export const REPORT_REASONS = [
  { id: "spam", label: "Spam or an ad" },
  { id: "impersonation", label: "Pretending to be someone" },
  { id: "harassment", label: "Harassment" },
  { id: "inaccurate", label: "Misleading or false" },
  { id: "other", label: "Something else" },
] as const;

export type ReportReason = (typeof REPORT_REASONS)[number]["id"];

/** Report a person's card (cards-api POST /cards/network/cards/{handle}/report, behind network controls:
 *  a 404 there means reporting is switched off, which is worded as "not available" rather than an error
 *  with the person). */
export async function reportCard(token: string, handle: string, reason: ReportReason): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API}/cards/network/cards/${encodeURIComponent(handle)}/report`, {
      method: "POST",
      cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
  } catch {
    throw new Error("Couldn't reach Zynd. Check your connection and try again.");
  }
  if (response.ok) return;
  if (response.status === 404) throw new Error("Reporting isn't available right now.");
  let detail = "Could not send your report. Please try again.";
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch { /* keep the fallback */ }
  throw new Error(detail);
}
