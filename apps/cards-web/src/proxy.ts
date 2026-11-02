import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { ATTR_COOKIE, type AttrPayload } from "@/lib/attr";

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"] as const;
const MAX_AGE = 60 * 60 * 24 * 30; // 30 days

/** Our own "get a card" CTAs (profile card bar, /visibility report). They only
 *  fill an empty ref: a visitor who came in through a share link or a campaign
 *  keeps that ref, which is the channel that actually brought them. */
function isInternalCtaRef(ref: string): boolean {
  return ref === "visibility" || ref === "card_bar" || ref.startsWith("card_bar:");
}

function readExisting(request: NextRequest): AttrPayload | null {
  const raw = request.cookies.get(ATTR_COOKIE)?.value;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AttrPayload;
  } catch {
    return null;
  }
}

export async function proxy(request: NextRequest) {
  const { searchParams, pathname } = request.nextUrl;
  // Resolve archived cards before page rendering so old URLs return an actual
  // 301. Never forward a visitor session to this public lookup.
  const mergedPath = pathname.match(/^\/p\/([^/]+)(\/.*)?$/);
  const aliasPath = pathname.match(/^\/([^/]+)$/);
  const reserved = new Set(["home", "feed", "create", "auth", "directory", "find", "search", "for-ai", "privacy", "terms", "support", "claude", "companion", "visibility"]);
  const slug = mergedPath?.[1] || (aliasPath && !reserved.has(aliasPath[1]) ? aliasPath[1] : null);
  if (slug) {
    try {
      const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
      const result = await fetch(`${api}/cards/redirect/${encodeURIComponent(slug)}`, { cache: "no-store", signal: AbortSignal.timeout(2000) });
      if (result.ok) {
        const data = await result.json() as { handle?: string | null };
        if (data.handle && /^[a-zA-Z0-9_-]+$/.test(data.handle) && data.handle !== slug) {
          const target = request.nextUrl.clone();
          target.pathname = `/p/${data.handle}${mergedPath?.[2] || ""}`;
          return NextResponse.redirect(target, 301);
        }
      }
    } catch { /* Backend outage: keep the ordinary profile fallback. */ }
  }
  const ref = searchParams.get("ref");
  const utm: Record<string, string> = {};
  for (const key of UTM_KEYS) {
    const v = searchParams.get(key);
    if (v) utm[key] = v.slice(0, 128);
  }

  const existing = readExisting(request);
  const incomingRef = ref && existing?.ref && isInternalCtaRef(ref) ? null : ref;
  if (!incomingRef && Object.keys(utm).length === 0) {
    return NextResponse.next();
  }
  let nextRef = incomingRef?.slice(0, 64) || existing?.ref;
  // Campaign beats share: keep an existing non-share ref when the new one is card:*.
  // An internal CTA ref isn't a campaign, so a share link may still replace it.
  if (existing?.ref && incomingRef?.startsWith("card:") && !existing.ref.startsWith("card:") && !isInternalCtaRef(existing.ref)) {
    nextRef = existing.ref;
  }

  const payload: AttrPayload = {
    ref: nextRef,
    source: pathname.slice(0, 200) || existing?.source || "/",
    utm: Object.keys(utm).length ? utm : existing?.utm,
    ts: Date.now(),
  };

  const response = NextResponse.next();
  response.cookies.set(ATTR_COOKIE, JSON.stringify(payload), {
    path: "/",
    maxAge: MAX_AGE,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    httpOnly: false,
  });
  return response;
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:txt|xml|json|png|jpg|jpeg|gif|svg|ico|webp)$).*)",
  ],
};
