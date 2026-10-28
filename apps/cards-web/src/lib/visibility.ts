/** AI visibility report (/visibility). Pair with cards-api FEATURE_AI_VISIBILITY; NEXT_PUBLIC_*
 *  is baked at build time, so flipping it needs a rebuild. */
export const visibilityEnabled = process.env.NEXT_PUBLIC_FEATURE_AI_VISIBILITY === "true";

export const MAX_NAME_CHARS = 100;
export const MAX_LINK_CHARS = 300;

export interface ZyndCardMatch {
  handle: string;
  name: string;
  claimed: boolean;
}

/** POST /cards/visibility/check response. */
export interface VisibilityReport {
  model: string;
  model_label: string;
  found: boolean;
  answer: string;
  cited_urls: string[];
  cites_zynd: boolean;
  zynd_card: ZyndCardMatch | null;
  cached: boolean;
  checked_at: string;
}

/** undefined = malformed, null = the API found no card. */
function parseCard(value: unknown): ZyndCardMatch | null | undefined {
  if (value === null) return null;
  if (typeof value !== "object") return undefined;
  const c = value as Record<string, unknown>;
  if (typeof c.handle !== "string" || !c.handle || typeof c.claimed !== "boolean") return undefined;
  return { handle: c.handle, name: typeof c.name === "string" ? c.name : "", claimed: c.claimed };
}

/** The API's JSON, checked at the boundary: null when it is not a report. */
export function parseVisibilityReport(data: unknown): VisibilityReport | null {
  if (typeof data !== "object" || data === null) return null;
  const r = data as Record<string, unknown>;
  const card = parseCard(r.zynd_card);
  if (card === undefined || typeof r.found !== "boolean" || typeof r.answer !== "string"
    || typeof r.cites_zynd !== "boolean" || !Array.isArray(r.cited_urls) || typeof r.model_label !== "string") {
    return null;
  }
  return {
    model: typeof r.model === "string" ? r.model : "",
    model_label: r.model_label,
    found: r.found,
    answer: r.answer,
    cited_urls: r.cited_urls.filter((u): u is string => typeof u === "string" && isHttpUrl(u)),
    cites_zynd: r.cites_zynd,
    zynd_card: card,
    cached: r.cached === true,
    checked_at: typeof r.checked_at === "string" ? r.checked_at : "",
  };
}

export type VisibilityStatus = "not_found" | "found_without_zynd" | "cites_zynd";

export function visibilityStatus(report: VisibilityReport): VisibilityStatus {
  if (!report.found) return "not_found";
  return report.cites_zynd ? "cites_zynd" : "found_without_zynd";
}

export const STATUS_TEXT: Record<VisibilityStatus, string> = {
  not_found: "AI found nothing about you.",
  found_without_zynd: "AI found you, but doesn't mention Zynd.",
  cites_zynd: "AI cites your Zynd card.",
};

export interface VisibilityCta {
  label: string;
  href: string;
}

export function visibilityCta(report: VisibilityReport, link: string | null): VisibilityCta {
  const card = report.zynd_card;
  if (card) {
    const href = `/p/${encodeURIComponent(card.handle)}`;
    return card.claimed ? { label: "View your card", href } : { label: "This is you? Claim it", href };
  }
  const params = new URLSearchParams({ ref: "visibility" });
  if (link) params.set("url", link);
  return { label: "Get your Zynd card", href: `/create?${params.toString()}` };
}

/** Mirrors the API's checks so an obvious typo is caught before a 10-20s wait. */
export function validateVisibilityInput(name: string, link: string): string | null {
  const cleanName = name.trim().replace(/\s+/g, " ");
  if (cleanName.length < 2) return "Type your name (at least 2 characters).";
  if (cleanName.length > MAX_NAME_CHARS) return `Your name can be at most ${MAX_NAME_CHARS} characters.`;
  const cleanLink = link.trim();
  if (!cleanLink) return null;
  if (cleanLink.length > MAX_LINK_CHARS) return `The link can be at most ${MAX_LINK_CHARS} characters.`;
  if (!isHttpUrl(cleanLink)) return "The link must be a full web address starting with http:// or https://.";
  return null;
}

export function isHttpUrl(value: string): boolean {
  try {
    const { protocol, hostname } = new URL(value);
    return (protocol === "http:" || protocol === "https:") && hostname.length > 0;
  } catch {
    return false;
  }
}

/** "en.wikipedia.org/wiki/Ada" for a source link's visible text. */
export function displayUrl(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    const path = pathname === "/" ? "" : pathname;
    const shown = `${hostname.replace(/^www\./, "")}${path}`;
    return shown.length > 60 ? `${shown.slice(0, 57)}…` : shown;
  } catch {
    return url;
  }
}
