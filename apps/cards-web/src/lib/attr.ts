/** S04 first-touch attribution cookie helpers (client + share URLs). */

export const ATTR_COOKIE = "zynd_attr";

export type AttrPayload = {
  ref?: string;
  source?: string;
  utm?: Record<string, string>;
  ts?: number;
};

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"] as const;

export function withShareRef(url: string, handle: string): string {
  try {
    const u = new URL(url, "https://cards.zynd.ai");
    u.searchParams.set("ref", `card:${handle}`);
    // Preserve path-only / relative callers: if input had no origin, return path+query.
    if (!/^https?:\/\//i.test(url)) {
      return `${u.pathname}${u.search}${u.hash}`;
    }
    return u.toString();
  } catch {
    const sep = url.includes("?") ? "&" : "?";
    return `${url}${sep}ref=${encodeURIComponent(`card:${handle}`)}`;
  }
}

export function readAttrCookie(): AttrPayload | null {
  if (typeof document === "undefined") return null;
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${ATTR_COOKIE}=`))
    ?.slice(ATTR_COOKIE.length + 1);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw)) as AttrPayload;
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

/** Append attribution fields to FormData for POST /onboard/start. */
export function appendAttrToForm(form: FormData): void {
  const attr = readAttrCookie();
  if (!attr) return;
  if (attr.source) form.append("source", attr.source);
  if (attr.ref) form.append("ref", attr.ref);
  if (attr.utm && Object.keys(attr.utm).length) {
    form.append("utm", JSON.stringify(attr.utm));
  }
}

/** Fields for POST /onboard/{job}/publish JSON body. */
export function attrPublishFields(): {
  source?: string;
  ref?: string;
  utm?: Record<string, string>;
  created_via: string;
} {
  const attr = readAttrCookie();
  return {
    ...(attr?.source ? { source: attr.source } : {}),
    ...(attr?.ref ? { ref: attr.ref } : {}),
    ...(attr?.utm && Object.keys(attr.utm).length ? { utm: attr.utm } : {}),
    created_via: "web",
  };
}

export function parseUtmFromSearch(searchParams: URLSearchParams): Record<string, string> {
  const utm: Record<string, string> = {};
  for (const key of UTM_KEYS) {
    const v = searchParams.get(key);
    if (v) utm[key] = v.slice(0, 128);
  }
  return utm;
}
