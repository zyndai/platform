import { MetadataRoute } from "next";
import { listCards, cardCanonicalUrl } from "@/lib/cards";

export const dynamic = "force-dynamic";

const BASE_URL = "https://cards.zynd.ai";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const cards = (await listCards()).filter((c) => c.claimed);

  const staticEntries: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "weekly", priority: 1.0 },
    { url: `${BASE_URL}/directory`, lastModified: new Date(), changeFrequency: "daily", priority: 0.9 },
    { url: `${BASE_URL}/search`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/find`, lastModified: new Date(), changeFrequency: "daily", priority: 0.95 },
    { url: `${BASE_URL}/for-ai`, lastModified: new Date(), changeFrequency: "weekly", priority: 0.9 },
  ];

  const profileEntries: MetadataRoute.Sitemap = cards.map((c) => ({
    url: cardCanonicalUrl(c),
    lastModified: c.updated_at ? new Date(c.updated_at) : new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.8,
  }));

  const skillSet = new Set<string>();
  for (const c of cards) {
    for (const s of c.skills) {
      if (s.name) skillSet.add(encodeURIComponent(s.name.toLowerCase().replace(/\s+/g, "-")));
    }
  }
  const tagEntries: MetadataRoute.Sitemap = Array.from(skillSet).map((slug) => ({
    url: `${BASE_URL}/tag/${slug}`,
    lastModified: new Date(),
    changeFrequency: "weekly" as const,
    priority: 0.7,
  }));

  return [...staticEntries, ...profileEntries, ...tagEntries];
}
