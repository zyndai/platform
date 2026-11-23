export interface PageInfo {
  /** The tab's title as the page keeps it now. */
  documentTitle: string;
  /** og:title: clean, but on single-page sites it can be left over from the first page loaded. */
  ogTitle: string;
  /** og:url: what the og: tags above claim to describe. Compared with `pageUrl` to spot stale tags. */
  ogUrl: string;
  /** The address of the page as it is now. */
  pageUrl: string;
  siteName: string;
  ogType: string;
  generator: string;
  selection: string;
  /** Who made a video, where the page shows it. Empty everywhere else. */
  channel: string;
}

/**
 * Runs inside the page the person is looking at, once, when they open the popup on it
 * (chrome.scripting.executeScript with activeTab). It reads only what the page says about itself
 * and what the person has selected. Chrome serialises this function, so it must stay
 * self-contained: no imports, no helpers, and the build must not rename or wrap it.
 * What to make of the raw values (which title to trust) is decided in classify.ts resolvePage.
 */
export function readPage(): PageInfo {
  const meta = (selector: string): string =>
    document.querySelector(selector)?.getAttribute("content")?.trim() ?? "";
  const host = location.hostname.toLowerCase();
  let channel = "";
  if ((host === "youtube.com" || host.endsWith(".youtube.com")) && location.pathname === "/watch") {
    channel = (
      document.querySelector("ytd-watch-metadata ytd-channel-name a")?.textContent ||
      document.querySelector('[itemprop="author"] link[itemprop="name"]')?.getAttribute("content") ||
      ""
    ).replace(/\s+/g, " ").trim();
  }
  return {
    documentTitle: document.title || "",
    ogTitle: meta('meta[property="og:title"]'),
    ogUrl: meta('meta[property="og:url"]'),
    pageUrl: location.href,
    siteName: meta('meta[property="og:site_name"]'),
    ogType: meta('meta[property="og:type"]'),
    generator: meta('meta[name="generator"]'),
    selection: String(window.getSelection() ?? "").trim().slice(0, 400),
    channel,
  };
}
