import type { PageInfo } from "./page-info";

/**
 * What may be clipped, and what kind of thing it is. Pure functions, no browser APIs.
 * The URL rules mirror cards-api services/companion.py (clean_url): the server checks again.
 * (Stripping a few extra share-tracking parameters on video sites here is cosmetic: the server
 * never puts them back, and what is safe to publish is still decided there.)
 */
export type Kind = "repo" | "paper" | "video" | "post" | "newsletter" | "blog" | "news" | "link";

export const KINDS: { kind: Kind; label: string }[] = [
  { kind: "repo", label: "Repo" },
  { kind: "paper", label: "Paper" },
  { kind: "video", label: "Video" },
  { kind: "post", label: "Post" },
  { kind: "newsletter", label: "Newsletter" },
  { kind: "blog", label: "Blog" },
  { kind: "news", label: "News" },
  { kind: "link", label: "Link" },
];

const TRACKING_PARAMS = new Set([
  "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref_src", "ref_url",
  "_hsenc", "_hsmi", "mkt_tok", "yclid", "twclid",
]);
const NO_QUERY_HOSTS = new Set(["x.com", "twitter.com", "mobile.twitter.com"]);
/** Parameters YouTube adds when a link is shared or clicked from a list: they identify the sharer, not the video. */
const YOUTUBE_NOISE = new Set(["si", "pp", "feature", "ab_channel", "start_radio"]);
const isYouTube = (host: string) => host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com");
const PRIVATE_SUFFIXES = [".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".private"];

export const URL_MAX = 500;
export const TITLE_MAX = 140;
export const NOTE_MAX = 200;
export const WORKING_ON_MAX = 120;

function ipv4Parts(host: string): number[] | null {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  return parts.every((n) => n <= 255) ? parts : null;
}

/** True for a host that is only reachable from the person's own machine or network. */
export function isPrivateHost(rawHost: string): boolean {
  const host = rawHost.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  const v4 = ipv4Parts(host);
  if (v4) {
    const [a, b] = v4 as [number, number, number, number];
    return (
      a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0)) || (a === 198 && (b === 18 || b === 19))
    );
  }
  if (host.includes(":")) {
    // IPv6: loopback, unspecified, unique-local (fc00::/7), link-local (fe80::/10), IPv4-mapped.
    return host === "::1" || host === "::" || /^f[cd]/.test(host) || /^fe[89ab]/.test(host) || host.startsWith("::ffff:");
  }
  return !host.includes(".") || host === "localhost" || PRIVATE_SUFFIXES.some((s) => host.endsWith(s));
}

export type Clippable = { ok: true; url: string } | { ok: false; reason: string };

/** The public form of a page address, or the reason it cannot go on a public card. */
export function cleanUrl(raw: string): Clippable {
  const text = (raw || "").trim();
  if (!text || text.length > URL_MAX) return { ok: false, reason: "This page's address is too long to add." };
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return { ok: false, reason: "This page cannot be added." };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: "Only web pages (http or https) can be added." };
  }
  if (url.username || url.password) return { ok: false, reason: "Links with a login in them cannot be added." };
  if (isPrivateHost(url.hostname)) {
    return { ok: false, reason: "Pages on your own computer or a private network cannot go on a public card." };
  }
  const host = url.hostname.toLowerCase();
  url.hash = "";
  if (NO_QUERY_HOSTS.has(host.replace(/^www\./, ""))) {
    url.search = "";
  } else {
    for (const key of [...url.searchParams.keys()]) {
      if (TRACKING_PARAMS.has(key.toLowerCase()) || key.toLowerCase().startsWith("utm_")) url.searchParams.delete(key);
    }
    if (isYouTube(host)) {
      for (const key of [...url.searchParams.keys()]) if (YOUTUBE_NOISE.has(key.toLowerCase())) url.searchParams.delete(key);
      // An auto-generated "Mix" (list=RD…) is not a page anyone else can open the same way.
      if ((url.searchParams.get("list") || "").startsWith("RD")) {
        url.searchParams.delete("list");
        url.searchParams.delete("index");
      }
    }
  }
  const cleaned = url.toString();
  return cleaned.length > URL_MAX ? { ok: false, reason: "This page's address is too long to add." } : { ok: true, url: cleaned };
}

export interface PageHints {
  ogType?: string;
  generator?: string;
  siteName?: string;
}

const PAPER_HOSTS = [
  "arxiv.org", "openreview.net", "biorxiv.org", "medrxiv.org", "ssrn.com", "doi.org", "semanticscholar.org",
  "aclanthology.org", "proceedings.mlr.press", "papers.nips.cc", "proceedings.neurips.cc", "dl.acm.org",
  "ieeexplore.ieee.org", "paperswithcode.com", "pubmed.ncbi.nlm.nih.gov", "researchgate.net", "jmlr.org",
];
const REPO_HOSTS = ["github.com", "gitlab.com", "bitbucket.org", "codeberg.org"];
const REPO_RESERVED = new Set([
  "orgs", "settings", "topics", "trending", "explore", "marketplace", "sponsors", "features", "pricing",
  "login", "about", "search", "notifications", "issues", "pulls", "collections", "events", "new",
]);
const VIDEO_HOSTS = ["youtube.com", "youtu.be", "vimeo.com", "loom.com", "twitch.tv", "wistia.com"];
const NEWSLETTER_HOSTS = ["substack.com", "beehiiv.com", "buttondown.email", "ck.page", "kit.com", "mailchi.mp", "campaign-archive.com", "convertkit.com", "revue.email"];
const BLOG_HOSTS = ["medium.com", "dev.to", "hashnode.dev", "hashnode.com", "wordpress.com", "blogspot.com", "mirror.xyz", "lesswrong.com", "ghost.io", "tumblr.com"];
const NEWS_HOSTS = [
  "nytimes.com", "bbc.com", "bbc.co.uk", "reuters.com", "theverge.com", "techcrunch.com", "wired.com", "bloomberg.com",
  "ft.com", "wsj.com", "theguardian.com", "cnbc.com", "economist.com", "arstechnica.com", "theinformation.com", "axios.com",
  "forbes.com", "businessinsider.com", "livemint.com", "economictimes.indiatimes.com", "thehindu.com", "indianexpress.com",
  "hindustantimes.com", "inc42.com", "yourstory.com", "medianama.com", "moneycontrol.com", "cnn.com", "apnews.com", "vox.com",
  "washingtonpost.com", "technologyreview.com", "semafor.com", "fortune.com", "venturebeat.com", "zdnet.com", "engadget.com",
];

const onHost = (host: string, list: string[]) => list.some((h) => host === h || host.endsWith(`.${h}`));

/** A best guess at what the page is. The person can change it before adding. */
export function detectKind(address: string, hints: PageHints = {}): Kind {
  let url: URL;
  try {
    url = new URL(address);
  } catch {
    return "link";
  }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  const segments = url.pathname.split("/").filter(Boolean);
  const generator = (hints.generator || "").toLowerCase();

  if (onHost(host, REPO_HOSTS)) {
    return segments.length >= 2 && !REPO_RESERVED.has((segments[0] || "").toLowerCase()) ? "repo" : "link";
  }
  if (host === "huggingface.co") {
    if (segments[0] === "papers") return "paper";
    return segments.length >= 2 && !["docs", "blog", "learn", "pricing", "tasks"].includes(segments[0] || "") ? "repo" : "link";
  }
  if (onHost(host, PAPER_HOSTS)) return host === "researchgate.net" && segments[0] !== "publication" ? "link" : "paper";
  if (/^(nature|science|cell)\.(com|org)$/.test(host) && /(articles|doi|content)/.test(url.pathname)) return "paper";
  if (onHost(host, VIDEO_HOSTS)) {
    if (host.endsWith("youtube.com")) return /^\/(watch|shorts|live|playlist|embed)/.test(url.pathname) ? "video" : "link";
    return segments.length > 0 ? "video" : "link";
  }
  if (host === "x.com" || host === "twitter.com" || host === "mobile.twitter.com") return segments[1] === "status" ? "post" : "link";
  if (host === "bsky.app") return segments[2] === "post" ? "post" : "link";
  if (host === "threads.net" || host === "threads.com") return segments[1] === "post" ? "post" : "link";
  if (host === "linkedin.com") return /^\/(posts|feed\/update|pulse)\//.test(url.pathname) ? (segments[0] === "pulse" ? "blog" : "post") : "link";
  if (onHost(host, NEWSLETTER_HOSTS) || generator.includes("substack") || generator.includes("beehiiv")) {
    return host === "substack.com" && segments.length === 0 ? "link" : "newsletter";
  }
  if (onHost(host, BLOG_HOSTS) || generator.includes("wordpress") || generator.includes("ghost") || generator.includes("hugo") || generator.includes("jekyll") || generator.includes("hashnode")) {
    return segments.length > 0 ? "blog" : "link";
  }
  if (onHost(host, NEWS_HOSTS)) return segments.length > 0 ? "news" : "link";
  if (/^(blog|engineering|research|medium)\./.test(host) || /^\/(blog|posts?|articles?|essays?|writing)\//.test(url.pathname)) return "blog";
  if ((hints.ogType || "").toLowerCase() === "article") return "news";
  return "link";
}

/** The page title without the site's own boilerplate. */
export function tidyTitle(raw: string, address: string): string {
  let title = (raw || "").replace(/\s+/g, " ").trim();
  let host = "";
  try {
    host = new URL(address).hostname.replace(/^www\./, "");
  } catch {
    /* A title is still a title. */
  }
  // "(3) " in front of a title is the site's unread-notifications count, not part of the title.
  if (isYouTube(host) || host === "x.com" || host === "twitter.com" || host.endsWith("linkedin.com")) {
    title = title.replace(/^\(\d+\+?\)\s*/, "");
  }
  if (host === "github.com") title = title.replace(/^GitHub\s*-\s*/, "");
  if (isYouTube(host)) title = title.replace(/\s*-\s*YouTube$/, "");
  if (host === "x.com" || host === "twitter.com") title = title.replace(/\s*\/\s*X$/, "");
  if (host.endsWith("linkedin.com")) title = title.replace(/\s*\|\s*LinkedIn$/, "");
  return title.slice(0, TITLE_MAX).trim() || host;
}

/** Collapse whitespace and cut to length: what the API stores. */
export function tidyText(raw: string, limit: number): string {
  // eslint-disable-next-line no-control-regex
  return (raw || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit).trim();
}

/** True unless the page's own og:url says it is describing a different page than the one open now. */
export function ogUrlMatches(ogUrl: string, pageUrl: string): boolean {
  if (!ogUrl || !pageUrl) return true; // nothing to contradict
  try {
    const claimed = new URL(ogUrl, pageUrl);
    const open = new URL(pageUrl);
    const bare = (u: URL) => u.hostname.toLowerCase().replace(/^www\./, "");
    if (bare(claimed) !== bare(open)) return false;
    if (claimed.pathname.replace(/\/$/, "") !== open.pathname.replace(/\/$/, "")) return false;
    for (const [key, value] of claimed.searchParams) if (open.searchParams.get(key) !== value) return false;
    return true;
  } catch {
    return true;
  }
}

const alnum = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

/** "youtube" for www.youtube.com, "bbc" for news.bbc.co.uk: the name a site goes by in its own title. */
function siteBrand(host: string): string {
  const labels = host.toLowerCase().replace(/^www\./, "").split(".");
  if (labels.length < 2) return labels[0] || "";
  const second = labels[labels.length - 2] || "";
  const compound = ["co", "com", "org", "net", "ac", "gov", "edu"].includes(second) && (labels[labels.length - 1] || "").length === 2;
  return labels[Math.max(labels.length - (compound ? 3 : 2), 0)] || "";
}

/**
 * What the open page says about itself, with the stale parts left out.
 * Single-page sites (YouTube, X, LinkedIn…) change the address and the tab title as you click
 * around but leave the og: tags from the first page load in place. Two tells that they are left
 * over: og:url names a different page than the one open now, or og:title is only the site's own
 * name ("YouTube", from the home page it was first loaded on) while the tab title says more.
 * In both cases only the tab title, which those sites keep current, is trusted.
 */
export function resolvePage(info: Partial<PageInfo>): PageHints & { title: string; selection: string; channel: string } {
  const documentTitle = info.documentTitle || "";
  const ogTitle = info.ogTitle || "";
  let host = "";
  try {
    host = new URL(info.pageUrl || "").hostname;
  } catch {
    /* No address: nothing to compare the og: tags with. */
  }
  const siteLevel = [siteBrand(host), alnum(info.siteName || "")].includes(alnum(ogTitle)) && alnum(ogTitle) !== "";
  const fresh = ogUrlMatches(info.ogUrl || "", info.pageUrl || "") && !(siteLevel && alnum(documentTitle) !== alnum(ogTitle) && documentTitle !== "");
  return {
    title: fresh ? ogTitle || documentTitle : documentTitle,
    siteName: fresh ? info.siteName || "" : "",
    ogType: fresh ? info.ogType || "" : "",
    generator: info.generator || "",
    selection: info.selection || "",
    channel: info.channel || "",
  };
}

/** Two spellings of one page compare equal: no www, no trailing slash, same query. Mirrors cards-api url_key. */
export function urlKey(address: string): string {
  try {
    const url = new URL(address);
    return `${url.hostname.toLowerCase().replace(/^www\./, "")}${url.pathname.replace(/\/+$/, "")}?${url.search.replace(/^\?/, "")}`;
  } catch {
    return address;
  }
}

/** The address as the person should see it: the host and everything that identifies the page, never the scheme or the fragment. */
export function displayAddress(address: string): string {
  try {
    const url = new URL(address);
    return `${url.hostname.replace(/^www\./, "")}${url.pathname === "/" ? "" : url.pathname}${url.search}`;
  } catch {
    return address;
  }
}
