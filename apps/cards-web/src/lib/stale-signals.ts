/** Stale "Working on" (cards-api services/stale_signals.py). The API sends
 *  `working_on_updated_at`: when the list last changed or the owner confirmed it,
 *  stamped by the database (cards migration 0035). Missing = unknown = not stale:
 *  cards from before the stamp existed must never be dimmed for lack of data. */

/** Keep in step with STALE_DAYS in cards-api services/stale_signals.py. */
export const STALE_DAYS = 90;

const DAY_MS = 86_400_000;

/** The stamp as epoch ms, or null when it is missing or unreadable. */
export function parseWorkingOnStamp(stamp: unknown): number | null {
  if (typeof stamp !== "string" || !stamp.trim()) return null;
  const ms = Date.parse(stamp);
  return Number.isNaN(ms) ? null : ms;
}

export function isWorkingOnStale(stamp: unknown, items: readonly string[], nowMs: number): boolean {
  if (!items.some((item) => item.trim())) return false;
  const ms = parseWorkingOnStamp(stamp);
  if (ms === null) return false;
  return nowMs - ms >= STALE_DAYS * DAY_MS;
}
