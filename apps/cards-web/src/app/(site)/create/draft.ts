import type { ChipGroupId } from "./chips";

/** What survives a sign-in round trip. A résumé file and hand edits to the draft do not: the card rebuilds from the links. */
export interface Draft {
  urls: string[];
  picks: Partial<Record<ChipGroupId, string[]>>;
  location: string | null;
  calendly: string;
  googleCalendar: string;
  handle: string;
}

const KEY = "zynd_create_draft";

export function saveDraft(draft: Draft): void {
  try { sessionStorage.setItem(KEY, JSON.stringify(draft)); } catch { /* private mode: the round trip just starts fresh */ }
}

/** Reads and forgets the saved draft. */
export function takeDraft(): Draft | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && Array.isArray(parsed.urls) ? (parsed as Draft) : null;
  } catch {
    return null;
  }
}
