// Types, fetch helper and pure helpers for the action feed (cards-api GET /cards/feed).
// Only type-only imports here, so `node --test` can load this file without the "@/" alias.
import type { ConnectionStatus } from "@/lib/cards-network";

export type FeedKind = "ask" | "working_on" | "exploring" | "joined" | "github" | "post";
export type FeedFilter = "all" | "asks" | "network";

export const FEED_FILTERS: { id: FeedFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "asks", label: "Asks" },
  { id: "network", label: "People you know" },
];

/** How the viewer stands with the author; null when there is no connection row. `incoming` is true
 *  when the author asked and the viewer is the one who can answer. */
export interface FeedConnection {
  id: string;
  status: ConnectionStatus;
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
  /** Why the viewer is seeing it ("You're connected", ...); empty when nothing specific applies. */
  reason: string;
  author: FeedAuthor;
  connection: FeedConnection | null;
}

export type FeedItem =
  | (FeedItemBase & { kind: "ask"; content: { text: string } })
  | (FeedItemBase & { kind: "working_on"; content: { text: string } })
  | (FeedItemBase & { kind: "exploring"; content: { title: string; url: string; note: string; kind: string } })
  | (FeedItemBase & { kind: "joined"; content: { headline: string; can_help_with: string[] } })
  | (FeedItemBase & { kind: "github"; content: { type: GithubItemType; repo: string; title: string; url: string } })
  | (FeedItemBase & { kind: "post"; content: { platform: "linkedin" | "x"; preview: string; url: string } });

export interface FeedPage {
  items: FeedItem[];
  next_cursor: string | null;
  /** has_card is false for someone who has not created a Card yet: replying needs one. */
  viewer: { has_card: boolean; handle: string | null };
}

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

/** One page of the feed. Works on the server (first page) and in the browser (load more). */
export async function fetchFeed(
  token: string,
  options: { filter?: FeedFilter; cursor?: string | null; signal?: AbortSignal } = {},
): Promise<FeedPage> {
  const params = new URLSearchParams();
  if (options.filter && options.filter !== "all") params.set("filter", options.filter);
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

export function parseFilter(raw: string | string[] | null | undefined): FeedFilter {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === "asks" || value === "network" ? value : "all";
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

export function replyFor(item: FeedItem): FeedReply {
  const hi = `Hi ${firstName(item.author.name)}, `;
  let reply: FeedReply;
  switch (item.kind) {
    case "ask":
      reply = { label: "I can help", prefill: `${hi}I can help with "${item.content.text}": ` };
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
  | { kind: "respond"; connectionId: string }
  | { kind: "unavailable" };

export function actionFor(hasCard: boolean, connection: FeedConnection | null): FeedAction {
  if (!hasCard) return { kind: "create-card" };
  if (!connection) return { kind: "reply", via: "request" };
  if (connection.status === "accepted") return { kind: "reply", via: "dm", connectionId: connection.id };
  if (connection.status === "pending") {
    return connection.incoming ? { kind: "respond", connectionId: connection.id } : { kind: "requested" };
  }
  // declined, revoked, blocked: the server keeps one final row per pair, so no new request can work.
  return { kind: "unavailable" };
}

/** Only http(s) links are drawn: they come from other people's cards. */
export function safeHref(url: string): string {
  return /^https?:\/\//i.test(url) ? url : "";
}
