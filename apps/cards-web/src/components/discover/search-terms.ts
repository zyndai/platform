/** Shared by the directory page (server) and its search (client): no "use client" here, so both can import values. */

export const DEFAULT_LIMIT = 10;
export const LIMIT_CHOICES = [10, 25, 50];
/** The ask API rejects anything longer. */
export const MAX_QUERY = 200;

/** Words that steer the ranked search. Adding one to the query is how you refine it; there is no separate filter API. */
export const REFINEMENTS = [
  { label: "Freelance", term: "freelance" },
  { label: "Open to work", term: "open to work" },
  { label: "Remote", term: "remote" },
  { label: "Senior", term: "senior" },
  { label: "5+ years", term: "5+ years" },
];

export function hasTerm(q: string, term: string): boolean {
  return q.toLowerCase().includes(term);
}

/** The query with `term` added, or taken out again if it is already there. */
export function toggleTerm(q: string, term: string): string {
  if (!hasTerm(q, term)) return `${q} ${term}`.trim();
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return q.replace(new RegExp(escaped, "ig"), " ").replace(/\s+/g, " ").trim();
}

/** The directory URL for a ranked search. */
export function matchHref(q: string, limit: number = DEFAULT_LIMIT): string {
  const params = new URLSearchParams({ q, match: "1" });
  if (limit !== DEFAULT_LIMIT) params.set("limit", String(limit));
  return `/directory?${params}`;
}
