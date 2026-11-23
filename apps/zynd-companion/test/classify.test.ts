import { describe, expect, it } from "vitest";
import { cleanUrl, detectKind, displayAddress, isPrivateHost, ogUrlMatches, resolvePage, tidyText, tidyTitle, urlKey } from "../src/classify";
import type { PageInfo } from "../src/page-info";

describe("cleanUrl", () => {
  it.each([
    ["https://github.com/zyndai/platform", "https://github.com/zyndai/platform"],
    ["https://www.example.com/a?utm_source=x&b=1&fbclid=z#frag", "https://www.example.com/a?b=1"],
    ["https://x.com/dil/status/123?s=20&t=abc", "https://x.com/dil/status/123"],
    ["https://youtu.be/abc?t=42", "https://youtu.be/abc?t=42"],
    ["  https://8.8.8.8/x  ", "https://8.8.8.8/x"],
    ["https://www.youtube.com/watch?v=abc&si=xyz&pp=0gcJ&feature=shared&t=42", "https://www.youtube.com/watch?v=abc&t=42"],
    ["https://youtu.be/abc?si=xyz", "https://youtu.be/abc"],
    ["https://www.youtube.com/watch?v=abc&list=RDabc&index=3", "https://www.youtube.com/watch?v=abc"],
    ["https://www.youtube.com/watch?v=abc&list=PLreal&index=3", "https://www.youtube.com/watch?v=abc&list=PLreal&index=3"],
    ["https://example.com/a?si=1&feature=2", "https://example.com/a?si=1&feature=2"],
  ])("keeps the public form of %s", (raw, expected) => {
    expect(cleanUrl(raw)).toEqual({ ok: true, url: expected });
  });

  it.each([
    "", "   ", "javascript:alert(1)", "file:///etc/passwd", "chrome://extensions", "chrome-extension://abc/popup.html",
    "about:blank", "ftp://example.com/x", "http://localhost:3000/", "http://127.0.0.1/", "http://10.0.0.5/admin",
    "http://192.168.1.1/", "http://169.254.169.254/latest", "http://[::1]/", "http://0.0.0.0/", "http://intranet/wiki",
    "http://jira.corp/browse/X-1", "https://build.internal/job/1", "https://nas.local/", "http://2130706433/",
    "https://user:pass@example.com/", "http://[fd00::1]/", "http://[fe80::1]/", "http://100.64.0.1/",
    "https://example.com/" + "a".repeat(600),
  ])("refuses %s", (raw) => {
    expect(cleanUrl(raw).ok).toBe(false);
  });

  it("explains why, in words a person can act on", () => {
    expect(cleanUrl("http://localhost:3000/").ok === false && cleanUrl("http://localhost:3000/")).toMatchObject({
      reason: expect.stringContaining("private network"),
    });
  });
});

describe("isPrivateHost", () => {
  it("treats ordinary public hosts and addresses as public", () => {
    for (const host of ["example.com", "sub.example.co.uk", "8.8.8.8", "172.32.0.1", "[2606:4700::1111]", "1.1.1.1"]) {
      expect(isPrivateHost(host), host).toBe(false);
    }
  });
  it("catches private ranges at their edges", () => {
    for (const host of ["172.16.0.1", "172.31.255.255", "192.168.0.1", "10.255.0.1", "127.8.8.8", "169.254.0.1", "224.0.0.1", "localhost", "printer"]) {
      expect(isPrivateHost(host), host).toBe(true);
    }
  });
});

describe("detectKind", () => {
  it.each([
    ["https://github.com/zyndai/platform", "repo"],
    ["https://github.com/zyndai/platform/pull/12", "repo"],
    ["https://github.com/zyndai", "link"],
    ["https://github.com/orgs/zyndai/people", "link"],
    ["https://gitlab.com/group/project", "repo"],
    ["https://huggingface.co/meta-llama/Llama-3", "repo"],
    ["https://huggingface.co/papers/2401.00001", "paper"],
    ["https://arxiv.org/abs/1706.03762", "paper"],
    ["https://openreview.net/forum?id=abc", "paper"],
    ["https://www.nature.com/articles/s41586-024-00001-1", "paper"],
    ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "video"],
    ["https://www.youtube.com/@channel", "link"],
    ["https://youtu.be/dQw4w9WgXcQ", "video"],
    ["https://vimeo.com/12345", "video"],
    ["https://x.com/dil/status/123", "post"],
    ["https://x.com/dil", "link"],
    ["https://twitter.com/dil/status/9", "post"],
    ["https://bsky.app/profile/a.bsky.social/post/3k", "post"],
    ["https://www.linkedin.com/posts/someone_thing-activity-1", "post"],
    ["https://someone.substack.com/p/a-post", "newsletter"],
    ["https://newsletter.beehiiv.com/p/issue-4", "newsletter"],
    ["https://medium.com/@a/a-post-1234", "blog"],
    ["https://dev.to/a/post", "blog"],
    ["https://www.theverge.com/2026/1/1/story", "news"],
    ["https://techcrunch.com/2026/01/01/story/", "news"],
    ["https://example.com/blog/a-post", "blog"],
    ["https://blog.example.com/a-post", "blog"],
    ["https://example.com/", "link"],
    ["not a url", "link"],
  ])("%s is %s", (url, kind) => {
    expect(detectKind(url)).toBe(kind);
  });

  it("uses what the page says about itself when the address is no help", () => {
    expect(detectKind("https://letters.example.org/issue-9", { generator: "Substack" })).toBe("newsletter");
    expect(detectKind("https://example.org/notes/why", { generator: "WordPress 6.5" })).toBe("blog");
    expect(detectKind("https://unknown-paper.example/2026/story", { ogType: "article" })).toBe("news");
    expect(detectKind("https://unknown.example/tool", { ogType: "website" })).toBe("link");
  });
});

describe("text tidying", () => {
  it("drops site boilerplate from titles", () => {
    expect(tidyTitle("GitHub - zyndai/platform: Zynd", "https://github.com/zyndai/platform")).toBe("zyndai/platform: Zynd");
    expect(tidyTitle("Attention explained - YouTube", "https://www.youtube.com/watch?v=1")).toBe("Attention explained");
    expect(tidyTitle("(3) Attention explained - YouTube", "https://www.youtube.com/watch?v=1")).toBe("Attention explained");
    expect(tidyTitle("(12+) Home / X", "https://x.com/home")).toBe("Home");
    expect(tidyTitle("Dil on shipping | LinkedIn", "https://www.linkedin.com/posts/x")).toBe("Dil on shipping");
    expect(tidyTitle("(500) Days of Summer", "https://example.com/film")).toBe("(500) Days of Summer");
    expect(tidyTitle("", "https://www.example.com/x")).toBe("example.com");
    expect(tidyTitle("x".repeat(300), "https://example.com/").length).toBe(140);
  });
  it("collapses whitespace and control characters and cuts to length", () => {
    expect(tidyText("  a\n\tb\u0000c  ", 10)).toBe("a b c");
    expect(tidyText("z".repeat(500), 200).length).toBe(200);
  });
});

const page = (over: Partial<PageInfo>): Partial<PageInfo> => ({
  documentTitle: "", ogTitle: "", ogUrl: "", pageUrl: "", siteName: "", ogType: "", generator: "", selection: "", channel: "", ...over,
});

describe("ogUrlMatches", () => {
  it("accepts the same page spelled differently", () => {
    expect(ogUrlMatches("https://example.com/a/", "https://www.example.com/a?utm_source=x#top")).toBe(true);
    expect(ogUrlMatches("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc&t=9")).toBe(true);
    expect(ogUrlMatches("/a", "https://example.com/a")).toBe(true);
  });
  it("has nothing to say when either side is missing", () => {
    expect(ogUrlMatches("", "https://example.com/a")).toBe(true);
    expect(ogUrlMatches("https://example.com/a", "")).toBe(true);
  });
  it("spots tags left over from another page", () => {
    expect(ogUrlMatches("https://www.youtube.com/", "https://www.youtube.com/watch?v=abc")).toBe(false);
    expect(ogUrlMatches("https://www.youtube.com/watch?v=old", "https://www.youtube.com/watch?v=new")).toBe(false);
    expect(ogUrlMatches("https://example.com/a", "https://other.example/a")).toBe(false);
  });
});

describe("resolvePage", () => {
  it("prefers the clean og:title when the tags belong to this page", () => {
    const r = resolvePage(page({
      documentTitle: "How chips got hot | The Verge", ogTitle: "How chips got hot", ogType: "article",
      ogUrl: "https://www.theverge.com/chips", pageUrl: "https://www.theverge.com/chips",
    }));
    expect(r.title).toBe("How chips got hot");
    expect(r.ogType).toBe("article");
  });
  it("falls back to the tab title when the og: tags are left over (YouTube after a click)", () => {
    const r = resolvePage(page({
      documentTitle: "(2) Cool talk - YouTube", ogTitle: "YouTube", ogType: "website", siteName: "YouTube",
      ogUrl: "https://www.youtube.com/", pageUrl: "https://www.youtube.com/watch?v=abc", channel: "Fireship",
    }));
    expect(r.title).toBe("(2) Cool talk - YouTube");
    expect(r.ogType).toBe("");
    expect(r.siteName).toBe("");
    expect(r.channel).toBe("Fireship");
    expect(tidyTitle(r.title, "https://www.youtube.com/watch?v=abc")).toBe("Cool talk");
  });
  it("catches the real YouTube home page, which has og:title but no og:url", () => {
    const r = resolvePage(page({
      documentTitle: "Cool talk - YouTube", ogTitle: "YouTube", pageUrl: "https://www.youtube.com/watch?v=abc",
    }));
    expect(r.title).toBe("Cool talk - YouTube");
  });
  it("keeps a site-name og:title when the tab title has nothing better (a home page)", () => {
    expect(resolvePage(page({ documentTitle: "Example", ogTitle: "Example", pageUrl: "https://www.example.com/" })).title).toBe("Example");
    expect(resolvePage(page({ documentTitle: "", ogTitle: "Example", pageUrl: "https://www.example.com/" })).title).toBe("Example");
  });
  it("does not mistake a page title that merely contains the site name for a generic one", () => {
    expect(resolvePage(page({
      documentTitle: "YouTube tips | Blog", ogTitle: "YouTube tips", pageUrl: "https://blog.example.com/youtube-tips",
    })).title).toBe("YouTube tips");
  });
  it("never uses a stale og:title, even with no tab title", () => {
    expect(resolvePage(page({ ogTitle: "YouTube", ogUrl: "https://www.youtube.com/", pageUrl: "https://www.youtube.com/watch?v=x" })).title).toBe("");
  });
  it("copes with nothing at all (a page the browser would not let us read)", () => {
    expect(resolvePage({})).toMatchObject({ title: "", selection: "", channel: "" });
  });
});

describe("urlKey and displayAddress", () => {
  it("treats spellings of one page alike, and different videos apart", () => {
    expect(urlKey("https://www.example.com/a/")).toBe(urlKey("https://example.com/a"));
    expect(urlKey("https://www.youtube.com/watch?v=a")).not.toBe(urlKey("https://www.youtube.com/watch?v=b"));
  });
  it("shows what identifies the page, including the video id", () => {
    expect(displayAddress("https://www.youtube.com/watch?v=abc123")).toBe("youtube.com/watch?v=abc123");
    expect(displayAddress("https://www.theverge.com/2026/10/1/chips")).toBe("theverge.com/2026/10/1/chips");
    expect(displayAddress("https://example.com/")).toBe("example.com");
  });
});
