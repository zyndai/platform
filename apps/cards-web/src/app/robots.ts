import { MetadataRoute } from "next";

const BASE_URL = "https://cards.zynd.ai";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/api/img"],
        // Only machine endpoints and signed-in surfaces are blocked here. Pages
        // that must stay out of the index (unclaimed cards, /home, /network,
        // /intros, welcome) carry a noindex tag instead: a crawler blocked by
        // robots.txt never fetches the page, so it never sees the noindex.
        // /api/img is the first-party avatar proxy, so it stays crawlable.
        // Profiles live at /<alias>, so "/create$" must not become a prefix
        // that also blocks an alias like /creative-jane.
        disallow: ["/api/", "/auth/", "/create$"],
      },
    ],
    sitemap: `${BASE_URL}/sitemap.xml`,
  };
}
