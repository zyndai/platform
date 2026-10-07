import { ACTIVITY, INTROS, LETTERS, ME, SOURCES, TODAY } from "./fixtures";
import type { Activity, Fact, FactKind, IntroRequest, Letter, SearchHit, SourceConnection, SourceId } from "./types";

/**
 * The only place the Dear Agent UI reads data from.
 *
 * Today every function returns fixtures. To wire the backend, replace the
 * bodies here and leave the screens alone. The comment on each function names
 * the service it should call and the engineering-guide slice that covers it.
 */

/** cards-api: GET /cards/{handle} → CardView (slice S06). */
export async function getLetter(handle: string): Promise<Letter | null> {
  return LETTERS.find((l) => l.handle === handle) ?? null;
}

/** cards-api: GET /cards/mine (slice S10). */
export async function getMyLetter(): Promise<Letter> {
  return LETTERS.find((l) => l.handle === ME)!;
}

/** cards-api: GET /ask?q= with claimed-only default (slices S03, S06). */
export async function searchLetters(query: string): Promise<SearchHit[]> {
  const words = query.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2);
  const hits: SearchHit[] = [];
  for (const letter of LETTERS) {
    const inked = letter.facts.filter((f) => f.state === "ink");
    const haystack = (f: Fact) => `${f.text} ${letter.headline} ${letter.location}`.toLowerCase();
    const reasons = words.length ? inked.filter((f) => words.some((w) => haystack(f).includes(w))) : inked.slice(0, 2);
    const headlineMatch = words.some((w) => `${letter.name} ${letter.headline} ${letter.location}`.toLowerCase().includes(w));
    if (reasons.length || headlineMatch || !words.length) hits.push({ letter, reasons: reasons.slice(0, 3) });
  }
  // Claimed and fresher letters first, as the review asked.
  return hits.sort(
    (a, b) => Number(b.letter.claimed) - Number(a.letter.claimed) || b.reasons.length - a.reasons.length || b.letter.updatedAt.localeCompare(a.letter.updatedAt),
  );
}

/** memory: GET /mcp/suggestions (slices S01, S05). */
export async function getPencilled(): Promise<Fact[]> {
  return (await getMyLetter()).facts.filter((f) => f.state === "pencil");
}

/** persona-api: connection requests addressed to me (slice S12). */
export async function getIntros(): Promise<IntroRequest[]> {
  return INTROS;
}

/** cards-api: card_events rolled up per week (slices S04, S10). */
export async function getActivity(): Promise<Activity> {
  return ACTIVITY;
}

/** memory + cards-api: connected sources and assistants (slice S09). */
export async function getSources(): Promise<SourceConnection[]> {
  return SOURCES;
}

// ── presentation helpers ───────────────────────────────────────────────────

export const SOURCE_LABEL: Record<SourceId, string> = {
  you: "Written by them",
  linkedin: "LinkedIn",
  github: "GitHub",
  x: "X",
  claude: "Claude",
  cursor: "Cursor",
  chatgpt: "ChatGPT",
};

export const KIND_LABEL: Record<FactKind, string> = {
  building: "Building",
  looking_for: "Looking for",
  can_help: "Can help with",
  role: "Role",
  shipped: "Shipped",
  skill: "Works with",
  tool: "Uses",
  location: "Based in",
};

function days(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000);
}

/** "today", "3 days ago", "March 2024" — relative to the fixture date so renders are stable. */
export function ageLabel(iso: string): string {
  const d = days(iso, TODAY);
  if (d <= 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 14) return `${d} days ago`;
  if (d < 60) return `${Math.round(d / 7)} weeks ago`;
  return new Date(iso).toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** A line older than a year is flagged, never hidden. */
export function isStale(iso: string): boolean {
  return days(iso, TODAY) > 365;
}

/** Days until a line expires; negative once it has. */
export function expiresIn(fact: Fact): number | null {
  return fact.expiresAt ? days(TODAY, fact.expiresAt) : null;
}

export function byKind(letter: Letter, kind: FactKind, state: Fact["state"] = "ink"): Fact[] {
  return letter.facts.filter((f) => f.kind === kind && f.state === state);
}
