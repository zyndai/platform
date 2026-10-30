import { after } from "next/server";
import { NextRequest, NextResponse } from "next/server";

// First-party image proxy for profile avatars. LinkedIn/X/GitHub CDN images
// are third-party on the page, so some browsers/extensions block them even
// though they load fine in a direct tab. Serving through our own domain makes
// the request first-party and also dodges LinkedIn's expiring signed URLs
// (the URL is fetched fresh server-side on each cache miss).
//
// Self-heal: when a LinkedIn URL fails (photo changed or removed), a
// background refresh of that card's avatar is triggered in cards-api.
const ALLOWED_HOSTS = new Set([
  "media.licdn.com",
  "static.licdn.com",
  "pbs.twimg.com",
  "abs.twimg.com",
  "avatars.githubusercontent.com",
  "github.com",
  "lh3.googleusercontent.com",
  // Project covers from a design portfolio, shown in the card's work grid.
  // Behance is its one image CDN, not all of *.behance.net: same host as
  // cards-api's scraping/sites.py accepts covers from.
  "cdn.dribbble.com",
  "mir-s3-cdn-cf.behance.net",
]);

// github.com/<user>.png answers with a redirect to avatars.githubusercontent.com.
// Each hop is followed by hand and checked against the allowlist, so an allowed
// host can't bounce the proxy to an arbitrary one.
const MAX_REDIRECTS = 3;
const NOT_AN_IMAGE = "not-an-image";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai";
const AVATAR_REFRESH_TOKEN = process.env.AVATAR_REFRESH_TOKEN || "";
const HANDLE_RE = /^[a-zA-Z0-9_-]{1,80}$/;

const FETCH_HEADERS = {
  "User-Agent": "Mozilla/5.0 (compatible; ZyndCards/1.0)",
  Accept: "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
};

function validImageUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    if (u.protocol !== "https:") return null;
    const host = u.hostname.toLowerCase();
    // Google serves account avatars from lhN.googleusercontent.com — allow
    // the whole suffix so a host rotation can't break already-stored URLs.
    if (ALLOWED_HOSTS.has(host)) return u.toString();
    if (host.endsWith(".googleusercontent.com")) return u.toString();
    // Photos uploaded through the old card editor live in our public avatars bucket and are
    // still shown when a card has no linked-account photo. Match the bucket path, not just the
    // host, so this isn't a proxy for arbitrary Supabase storage.
    if (host.endsWith(".supabase.co") && u.pathname.startsWith("/storage/v1/object/public/avatars/")) {
      return u.toString();
    }
    return null;
  } catch {
    return null;
  }
}

/** The image, NOT_AN_IMAGE when the upstream answered with something else, or null when it couldn't be fetched. */
async function fetchImage(raw: string): Promise<Response | typeof NOT_AN_IMAGE | null> {
  let url = validImageUrl(raw);
  const signal = AbortSignal.timeout(15000);
  try {
    for (let hop = 0; url && hop <= MAX_REDIRECTS; hop++) {
      const res = await fetch(url, { headers: FETCH_HEADERS, redirect: "manual", signal });
      if (res.status >= 300 && res.status < 400) {
        void res.body?.cancel();
        const location = res.headers.get("location");
        url = location ? validImageUrl(new URL(location, url).toString()) : null;
        continue;
      }
      if (!res.ok || !res.body) return null;
      // Passing any content type through would let an allowed host serve HTML or script from our origin.
      if (!(res.headers.get("content-type") ?? "").toLowerCase().startsWith("image/")) {
        void res.body.cancel();
        return NOT_AN_IMAGE;
      }
      return res;
    }
    return null;
  } catch {
    return null;
  }
}

function triggerAvatarRefresh(handle: string | null | undefined, failedUrl: string | null | undefined) {
  if (!handle || !HANDLE_RE.test(handle) || !AVATAR_REFRESH_TOKEN || !failedUrl) return;
  let host = "";
  try {
    host = new URL(failedUrl).hostname;
  } catch {
    return;
  }
  if (host !== "media.licdn.com") return;
  after(async () => {
    try {
      await fetch(`${API_BASE}/cards/internal/refresh-avatar/${encodeURIComponent(handle)}`, {
        method: "POST",
        headers: { "x-avatar-refresh-token": AVATAR_REFRESH_TOKEN },
        signal: AbortSignal.timeout(8000),
      });
    } catch {
      /* best effort */
    }
  });
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const url = searchParams.get("url") || "";
  const fallback = searchParams.get("fallback") || "";
  const handle = searchParams.get("handle");

  const primary = url ? await fetchImage(url) : null;
  const backup = primary instanceof Response || !fallback ? null : await fetchImage(fallback);
  const res = primary instanceof Response ? primary : backup instanceof Response ? backup : null;

  if (!res) {
    triggerAvatarRefresh(handle, url);
    if (primary === NOT_AN_IMAGE || backup === NOT_AN_IMAGE) {
      return NextResponse.json({ error: "upstream did not return an image" }, { status: 502 });
    }
    return NextResponse.json({ error: "image unavailable" }, { status: 404 });
  }
  if (res !== primary) triggerAvatarRefresh(handle, url);

  return new Response(res.body, {
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "image/jpeg",
      "Cache-Control": "public, max-age=86400, s-maxage=604800",
    },
  });
}