/** Limited-edition card looks. The owner's choice lives on the card at
 *  `identity.edition`; cards-api validates it against the same ids
 *  (services/cards-api/models/card.py → Edition). */

export const EDITION_IDS = ["mumbai-26"] as const;
export const EDITION_MOODS = ["night", "dusk", "monsoon"] as const;
export const HERE_FOR = ["hacking", "speaking", "building", "hiring", "raising", "investing", "exploring"] as const;

export type EditionId = (typeof EDITION_IDS)[number];
export type EditionMood = (typeof EDITION_MOODS)[number];
export type HereFor = (typeof HERE_FOR)[number];

export interface CardEdition {
  id: EditionId;
  mood: EditionMood;
  here_for: HereFor | null;
}

export const EDITION_NAME: Record<EditionId, string> = {
  "mumbai-26": "Mumbai Builder Week ’26",
};

export const MOOD_LABEL: Record<EditionMood, string> = {
  night: "Night",
  dusk: "Dusk",
  monsoon: "Monsoon",
};

export const HERE_FOR_LABEL: Record<HereFor, string> = {
  hacking: "Hacking",
  speaking: "Speaking",
  building: "Building",
  hiring: "Hiring",
  raising: "Raising",
  investing: "Investing",
  exploring: "Exploring",
};

/** End of 30 Nov 2026 in Mumbai (IST, UTC+5:30). After this the edition is no
 *  longer offered to new picks; cards that already use it keep it. */
const MUMBAI_26_PICKABLE_UNTIL = Date.parse("2026-11-30T23:59:59+05:30");

export function isEditionPickable(id: EditionId, nowMs: number = Date.now()): boolean {
  return id === "mumbai-26" && nowMs <= MUMBAI_26_PICKABLE_UNTIL;
}

function isOneOf<T extends string>(options: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (options as readonly string[]).includes(value);
}

/** The card's edition, or null for the classic look. Mirrors the API, which
 *  treats an unknown or malformed edition as no edition. */
export function readEdition(raw: unknown): CardEdition | null {
  if (!raw || typeof raw !== "object") return null;
  const { id, mood, here_for } = raw as Record<string, unknown>;
  if (!isOneOf(EDITION_IDS, id)) return null;
  if (mood != null && !isOneOf(EDITION_MOODS, mood)) return null;
  if (here_for != null && !isOneOf(HERE_FOR, here_for)) return null;
  return { id, mood: mood ?? "night", here_for: here_for ?? null };
}
