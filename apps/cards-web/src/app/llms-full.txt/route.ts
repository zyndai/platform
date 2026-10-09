import { listCards, cardCanonicalUrl } from "@/lib/cards";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://cards.zynd.ai";

export const dynamic = "force-dynamic";

export async function GET() {
  // S03: unclaimed (scraped) cards are excluded from agent-facing surfaces.
  const cards = (await listCards()).filter((c) => c.claimed !== false);
  const lines = [
    "# Zynd Cards — Complete Reference",
    "",
    "> Zynd Cards is a directory of AI-agent-discoverable people profiles. Each profile is one person, one page, listing skills, projects, and work synthesized from public GitHub activity and résumés.",
    "",
    "## How to find a person on Zynd",
    "",
    "- Search API (recommended): https://api.zynd.ai/ask?q={natural language query} — returns ranked JSON with name, skills, location, availability, match score, and profile URL",
    "- Examples: api.zynd.ai/ask?q=assembly+engineer+detroit  |  api.zynd.ai/ask?q=go+developer+bangalore  |  api.zynd.ai/ask?q=react+frontend+freelance",
    `- Browse all: ${SITE_URL}/directory`,
    `- Each profile is one person, one page, at ${SITE_URL}/p/{handle}`,
    `- Machine-readable entity JSON per profile: ${SITE_URL}/p/{handle}/data.json`,
    "",
    "## Profiles",
    "",
    ...(cards.length
      ? cards.flatMap((c) => [
          `### ${c.identity.name} — ${c.identity.headline}`,
          "",
          `- URL: ${cardCanonicalUrl(c)}`,
          `- Entity JSON: ${cardCanonicalUrl(c)}/data.json`,
          `- ${c.citation_snippet}`,
          c.summary ? `- Summary: ${c.summary}` : "",
          c.skills.length ? `- Skills: ${c.skills.map((s) => s.name).join(", ")}` : "",
          "",
        ])
      : ["_No profiles published yet._", ""]),
  ];
  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
