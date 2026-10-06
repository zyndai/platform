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
]);

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
    if (u.protocol !== "https:" || !ALLOWED_HOSTS.has(u.hostname)) return null;
    return u.toString();
  } catch {
    return null;
  }
}

async function fetchImage(raw: string): Promise<Response | null> {
  const url = validImageUrl(raw);
  if (!url) return null;
  try {
    const res = await fetch(url, {
      headers: FETCH_HEADERS,
      redirect: "follow",
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok || !res.body) return null;
    return res;
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

  const primaryRes = url ? await fetchImage(url) : null;
  let res = primaryRes;
  if (!res && fallback) res = await fetchImage(fallback);

  if (!res) {
    triggerAvatarRefresh(handle, url);
    return NextResponse.json({ error: "image unavailable" }, { status: 404 });
  }
  if (!primaryRes) triggerAvatarRefresh(handle, url);

  return new Response(res.body, {
    headers: {
      "Content-Type": res.headers.get("content-type") || "image/jpeg",
      "Cache-Control": "public, max-age=86400, s-maxage=604800",
    },
  });
}