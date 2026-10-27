/**
 * What may be clipped, and what kind of thing it is. Pure functions, no browser APIs.
 * The URL rules mirror cards-api services/companion.py (clean_url): the server checks again.
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
  if (host === "github.com") title = title.replace(/^GitHub\s*-\s*/, "");
  if (host.endsWith("youtube.com") || host === "youtu.be") title = title.replace(/\s*-\s*YouTube$/, "");
  if (host === "x.com" || host === "twitter.com") title = title.replace(/\s*\/\s*X$/, "");
  return title.slice(0, TITLE_MAX).trim() || host;
}

/** Collapse whitespace and cut to length: what the API stores. */
export function tidyText(raw: string, limit: number): string {
  // eslint-disable-next-line no-control-regex
  return (raw || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, limit).trim();
}
