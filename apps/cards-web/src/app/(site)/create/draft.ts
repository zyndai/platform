import type { ChipGroupId, PersonaId } from "./chips";

/** What survives a sign-in round trip. A résumé file and hand edits to the draft do not: the card rebuilds from the links. */
export interface Draft {
  urls: string[];
  picks: Partial<Record<ChipGroupId, string[]>>;
  /** The persona the person switched to, if they did. */
  persona?: PersonaId | null;
  location: string | null;
  calendly: string;
  googleCalendar: string;
  handle: string;
}

const KEY = "zynd_create_draft";
// An email magic link opens in a new tab, which can't read this tab's
// sessionStorage, so the email path also leaves a copy in localStorage. It
// lives as long as the link does (an hour, per the "check your email" notice) and is
// deleted once a tab restores it.
const CROSS_TAB_KEY = "zynd_create_draft_xtab";
const CROSS_TAB_TTL_MS = 60 * 60 * 1000;

function isDraft(value: unknown): value is Draft {
  return !!value && typeof value === "object" && Array.isArray((value as Draft).urls);
}

/** `acrossTabs`: the sign-in finishes in another tab (email magic link). */
export function saveDraft(draft: Draft, { acrossTabs = false }: { acrossTabs?: boolean } = {}): void {
  try { sessionStorage.setItem(KEY, JSON.stringify(draft)); } catch { /* private mode: the round trip just starts fresh */ }
  if (!acrossTabs) return;
  try {
    localStorage.setItem(CROSS_TAB_KEY, JSON.stringify({ draft, expiresAt: Date.now() + CROSS_TAB_TTL_MS }));
  } catch (err) {
    console.warn("create draft: could not keep a copy for the sign-in link's tab", err);
  }
}

function takeSessionDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function takeCrossTabDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(CROSS_TAB_KEY);
    if (!raw) return null;
    localStorage.removeItem(CROSS_TAB_KEY);
    const parsed = JSON.parse(raw) as { draft?: unknown; expiresAt?: unknown } | null;
    const fresh = typeof parsed?.expiresAt === "number" && parsed.expiresAt > Date.now();
    return fresh && isDraft(parsed.draft) ? parsed.draft : null;
  } catch {
    return null;
  }
}

/** Reads and forgets the saved draft: this tab's own first, else one left for a magic-link tab.
 *  A tab that finds its own leaves the cross-tab copy for the tab the link opens. */
export function takeDraft(): Draft | null {
  return takeSessionDraft() ?? takeCrossTabDraft();
}

/** Forgets every saved copy, e.g. once the card is published. */
export function discardDraft(): void {
  try { sessionStorage.removeItem(KEY); } catch { /* storage unavailable: nothing was saved */ }
  try { localStorage.removeItem(CROSS_TAB_KEY); } catch { /* storage unavailable: nothing was saved */ }
}
