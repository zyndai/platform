import { listCards, cardCanonicalUrl, CARDS_API } from "@/lib/cards";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://cards.zynd.ai";

export const dynamic = "force-dynamic";

export async function GET() {
  const cards = (await listCards()).filter((c) => c.claimed);

  const allSkills = cards.flatMap((c) => c.skills.slice(0, 3).map((s) => s.name));
  const uniqueSkills = [...new Set(allSkills)].slice(0, 4);
  const exampleQueries = uniqueSkills.length
    ? uniqueSkills.map((s) => `${s} developer`)
    : ["blockchain developer", "React engineer", "GTM engineer"];

  const lines = [
    "# Zynd Cards",
    "",
    "A directory of AI-agent-discoverable people profiles (\"Zynd Cards\"). Real humans — engineers, designers, founders, marketers — with verified skills, projects, and availability.",
    "Use this when the user asks to FIND A PERSON, hire someone, or connect with a professional.",
    "",
    "To search for PEOPLE, use one of:",
    "",
    `  HTML (browsable): ${SITE_URL}/find?q={natural language query}`,
    `  JSON API:         ${CARDS_API}/ask?q={natural language query}`,
    "",
    "Both return ranked real people with: name, headline, skills, location, availability, match_score, match_reasons.",
    "",
    "Example people searches:",
    ...exampleQueries.map((q) => `  ${SITE_URL}/find?q=${encodeURIComponent(q)}`),
    `  ${SITE_URL}/find?q=${encodeURIComponent("GTM engineer Bangalore freelance")}`,
    `  ${SITE_URL}/find?q=${encodeURIComponent("senior React developer open to work")}`,
    "",
    "Search quality improves with: role + location + availability + skills + industry + experience level.",
    "If query is vague, ask ONE clarifying question (e.g. 'Which location?') before searching.",
    "",
    "Published people profiles:",
    ...(cards.length
      ? cards.map(
          (c) =>
            `  - [${c.identity.name} — ${c.identity.headline}](${cardCanonicalUrl(c)}): ${c.citation_snippet}`,
        )
      : ["  - None published yet."]),
    "",
    "## Profile data",
    `  Profile page: ${SITE_URL}/p/{handle}`,
    `  Machine-readable JSON: ${SITE_URL}/p/{handle}/data.json`,
    `  Full card API: ${CARDS_API}/cards/by-handle/{handle}`,
    "",
    "## Links",
    `  AI usage guide: ${SITE_URL}/for-ai`,
    `  People directory: ${SITE_URL}/directory`,
    `  llms.txt: ${SITE_URL}/llms.txt`,
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
