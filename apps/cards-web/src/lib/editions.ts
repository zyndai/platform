/** Limited-edition card looks. The owner's choice lives on the card at
 *  `identity.edition`; cards-api validates it against the same ids
 *  (services/cards-api/models/card.py → Edition). */

export const EDITION_IDS = ["mumbai-26"] as const;
// Moods are no longer offered (the edition has one look) but stay valid so
// cards saved with one keep reading as the edition; the API accepts the same set.
export const EDITION_MOODS = ["night", "dusk", "monsoon"] as const;
export const HERE_FOR = ["hacking", "speaking", "building", "hiring", "raising", "investing", "exploring"] as const;
// The banner artwork; cards saved before the choice existed get the first.
export const EDITION_BANNERS = ["waterfront", "gateway"] as const;

export type EditionId = (typeof EDITION_IDS)[number];
export type EditionMood = (typeof EDITION_MOODS)[number];
export type HereFor = (typeof HERE_FOR)[number];
export type EditionBanner = (typeof EDITION_BANNERS)[number];

export interface CardEdition {
  id: EditionId;
  mood: EditionMood;
  banner: EditionBanner;
  here_for: HereFor | null;
}

export const BANNER_LABEL: Record<EditionBanner, { name: string; hint: string }> = {
  waterfront: { name: "Waterfront", hint: "Sunset over the skyline" },
  gateway: { name: "Gateway", hint: "The Gateway of India at night" },
};

export const EDITION_NAME: Record<EditionId, string> = {
  "mumbai-26": "Mumbai Builder Week ’26",
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
  const { id, mood, banner, here_for } = raw as Record<string, unknown>;
  if (!isOneOf(EDITION_IDS, id)) return null;
  if (mood != null && !isOneOf(EDITION_MOODS, mood)) return null;
  if (banner != null && !isOneOf(EDITION_BANNERS, banner)) return null;
  if (here_for != null && !isOneOf(HERE_FOR, here_for)) return null;
  return { id, mood: mood ?? "night", banner: banner ?? "waterfront", here_for: here_for ?? null };
}
