import { notFound, redirect } from "next/navigation";
import { CARDS_API } from "@/lib/cards";

export const revalidate = 300;

interface PageProps {
  params: Promise<{ alias: string }>;
}

// Reserved words never resolve here: they belong to real routes. A catch-all
// like this must stay last-resort (static routes always win anyway).
const RESERVED = new Set([
  "p", "find", "directory", "search", "api", "create", "for-ai", "auth",
  "profile", "tag", "edit", "onboard", "mcp", "dashboard", "settings",
  "home", "about", "contact", "help", "login", "logout", "account", "cards",
  "zynd", "www", "assets", "images", "icons", "icon", "apple-icon",
  "favicon.ico", "llms.txt", "llms-full.txt", "agents.txt", "sitemap.xml",
  "robots.txt", "data.json", "opengraph-image", "_next", "web",
]);

export default async function AliasRedirectPage({ params }: PageProps) {
  const { alias } = await params;
  const slug = alias.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
  if (RESERVED.has(slug) || slug.length < 2) notFound();

  try {
    const res = await fetch(`${CARDS_API}/cards/by-alias/${encodeURIComponent(slug)}`, {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) notFound();
    const card = (await res.json()) as { handle?: string };
    if (card.handle) redirect(`/p/${encodeURIComponent(card.handle)}`);
  } catch {
    // fetch threw (timeout/network) — fall through to 404 rather than a 500
  }
  notFound();
}