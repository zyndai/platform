export interface PageInfo {
  title: string;
  siteName: string;
  ogType: string;
  generator: string;
  selection: string;
}

/**
 * Runs inside the page the person is looking at, once, when they open the popup on it
 * (chrome.scripting.executeScript with activeTab). It reads only what the page says about itself
 * and what the person has selected. Chrome serialises this function, so it must stay
 * self-contained: no imports, no helpers, and the build must not rename or wrap it.
 */
export function readPage(): PageInfo {
  const meta = (selector: string): string =>
    document.querySelector(selector)?.getAttribute("content")?.trim() ?? "";
  return {
    title: meta('meta[property="og:title"]') || document.title || "",
    siteName: meta('meta[property="og:site_name"]'),
    ogType: meta('meta[property="og:type"]'),
    generator: meta('meta[name="generator"]'),
    selection: String(window.getSelection() ?? "").trim().slice(0, 400),
  };
}
