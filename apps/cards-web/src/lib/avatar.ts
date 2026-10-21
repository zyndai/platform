/**
 * First-party proxy URL for third-party avatar CDNs.
 *
 * LinkedIn/X/GitHub/Google avatar URLs are third-party on the page; some
 * browsers and extensions block those requests outright, leaving a blank
 * image (no error event, so no fallback either). Serving through our own
 * /api/img route makes the request first-party and also sidesteps LinkedIn's
 * expiring signed URLs. The route tries `fallback` server-side when the
 * primary URL fails.
 */
export function imgProxyUrl(
  src: string | null | undefined,
  fallback?: string | null,
  handle?: string | null,
): string | undefined {
  const qs = new URLSearchParams();
  if (src) qs.set("url", src);
  if (fallback) qs.set("fallback", fallback);
  if (handle) qs.set("handle", handle);
  if (!qs.has("url") && !qs.has("fallback")) return undefined;
  return `/api/img?${qs.toString()}`;
}

/**
 * Proxied photo for a Cards network summary (inbox, group members, people
 * search). The handle rides along so /api/img can kick off an avatar refresh
 * when a stored LinkedIn URL has expired.
 */
export function cardAvatarSrc(
  card: { avatar_url?: string | null; handle?: string | null } | null | undefined,
): string | undefined {
  return imgProxyUrl(card?.avatar_url, null, card?.handle);
}