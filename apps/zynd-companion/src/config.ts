/** Where the Cards API and website are. The build picks production or local development. */
export const API_BASE = __API_BASE__.replace(/\/$/, "");
export const SITE_BASE = __SITE_BASE__.replace(/\/$/, "");
export const COMPANION_API = `${API_BASE}/cards/companion`;
export const CONNECT_URL = `${SITE_BASE}/companion/connect`;

/** Days without a touch from this extension before the icon asks "still working on this?". */
export const STALE_AFTER_DAYS = 10;
/** A connect link is good for this long after the person clicks Connect in the extension. */
export const PAIRING_WINDOW_MS = 10 * 60 * 1000;
