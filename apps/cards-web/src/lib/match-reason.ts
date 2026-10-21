/** Why a card matched a search, as returned by Cards API. Strings are plain reasons; a memory
 *  reason carries an approved fact with where it came from and how old it is. */
export type MatchReason =
  | string
  | { type: string; text: string; source?: string; age_days?: number | null };

/** " (this week)", " (3 weeks ago)", " (2 months ago)" — how current an approved fact is. */
export function ageHint(days: number | null | undefined): string {
  if (typeof days !== "number" || !Number.isFinite(days) || days < 0) return "";
  if (days <= 7) return " (this week)";
  if (days <= 30) return ` (${Math.floor(days / 7)} weeks ago)`;
  return ` (${Math.floor(days / 30)} months ago)`;
}

export function formatMatchReason(reason: MatchReason): string {
  if (typeof reason === "string") return reason;
  if (reason?.type === "memory" && reason.text) return `Memory: ${reason.text}${ageHint(reason.age_days)}`;
  return reason?.text || "";
}

/** Identities Cards has proven for a card's owner, as a short label ("LinkedIn"). Unknown
 *  providers are ignored so a new one never renders as a raw key. */
const VERIFIED_LABELS: Record<string, string> = { linkedin: "LinkedIn", github: "GitHub", work_email: "work email" };

export function verifiedLabels(verified: readonly string[] | null | undefined): string[] {
  return (verified ?? []).map((v) => VERIFIED_LABELS[v]).filter((v): v is string => Boolean(v));
}
