/**
 * Pairing messages between the cards website's connect page and this extension's content script,
 * over window.postMessage. Mirrored in apps/cards-web/src/lib/companion.ts.
 *
 * The page talks first only to ask who is there ("hello"); the extension answers "ready" with the
 * state it is waiting for. The page mints a token only after that, and hands it over in "grant".
 */
export const FROM_PAGE = "zynd-cards";
export const FROM_EXTENSION = "zynd-companion";

export interface GrantProfile {
  handle: string;
  name: string;
  headline?: string;
  avatar_url?: string;
  card_url: string;
}

export type PageMessage =
  | { source: typeof FROM_PAGE; type: "hello" }
  | { source: typeof FROM_PAGE; type: "grant"; state: string; token: string; profile: GrantProfile };

export type ExtensionMessage =
  | { source: typeof FROM_EXTENSION; type: "ready"; state: string | null }
  | { source: typeof FROM_EXTENSION; type: "paired"; state: string }
  | { source: typeof FROM_EXTENSION; type: "rejected"; state: string; reason: string };

export const STATE_PATTERN = /^[a-f0-9]{32}$/;
export const TOKEN_PATTERN = /^zdc_[A-Za-z0-9_-]{20,190}$/;

/** A message from the connect page, or null for anything else (other pages' messages, junk). */
export function readPageMessage(data: unknown): PageMessage | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;
  if (d.source !== FROM_PAGE) return null;
  if (d.type === "hello") return { source: FROM_PAGE, type: "hello" };
  if (d.type !== "grant") return null;
  const profile = d.profile as Record<string, unknown> | null;
  if (typeof d.state !== "string" || !STATE_PATTERN.test(d.state)) return null;
  if (typeof d.token !== "string" || !TOKEN_PATTERN.test(d.token)) return null;
  if (!profile || typeof profile.handle !== "string" || typeof profile.card_url !== "string") return null;
  return {
    source: FROM_PAGE,
    type: "grant",
    state: d.state,
    token: d.token,
    profile: {
      handle: profile.handle,
      name: typeof profile.name === "string" ? profile.name : "",
      headline: typeof profile.headline === "string" ? profile.headline : "",
      avatar_url: typeof profile.avatar_url === "string" ? profile.avatar_url : "",
      card_url: profile.card_url,
    },
  };
}
