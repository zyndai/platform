/** Which search a profile link came from, so the profile's `view` can be tied to it in the funnel
 *  (cards-api records the search id and rank, never the query). The ids are in the URL only until
 *  the profile has counted the view. */
const SEARCH_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface SearchRef {
  searchId: string;
  rank: number;
}

/** `sid` and `r` from a URL, or null unless both are well formed. */
export function parseSearchRef(sid: string | string[] | undefined, rank: string | string[] | undefined): SearchRef | null {
  const id = Array.isArray(sid) ? sid[0] : sid;
  const r = Number(Array.isArray(rank) ? rank[0] : rank);
  if (!id || !SEARCH_ID.test(id) || !Number.isInteger(r) || r < 1 || r > 100) return null;
  return { searchId: id.toLowerCase(), rank: r };
}

/** A profile link that remembers the search (and the person's place in it) it was shown in. */
export function withSearch(href: string, searchId: string | undefined, rank: number): string {
  if (!searchId || !SEARCH_ID.test(searchId) || rank < 1 || rank > 100) return href;
  return `${href}${href.includes("?") ? "&" : "?"}sid=${searchId}&r=${rank}`;
}
