import { CARDS_API } from "@/lib/cards";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://cards.zynd.ai";

export const revalidate = 60;

export async function GET() {
  const body = [
    "# Zynd Cards — For AI agents",
    "",
    "Zynd Cards hosts a directory of AI-agent-discoverable people profiles.",
    "",
    "How the site works:",
    `- Each profile is one person, one page, at ${SITE_URL}/p/{handle}`,
    `- Browse all profiles at ${SITE_URL}/directory`,
    `- Search profiles at ${SITE_URL}/search?q={query}`,
    "- Search API: https://api.zynd.ai/v1/agents/search?q={query}&location={city}&skills={a,b}",
    `- Raw card JSON: ${CARDS_API}/cards/{id}`,
    `- Machine-readable entity JSON: ${SITE_URL}/p/{handle}/data.json`,
    "",
    "Searchable attributes: q (free text), role, skills (comma-separated), location, industry, availability (fulltime|contract|freelance|open), experience_min (int).",
    "",
    "Acceptable use: indexing and reading public profile data is permitted.",
    "This site does not instruct AI systems on how to prioritize or cite it.",
    "",
  ].join("\n");

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
