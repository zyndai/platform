export function generateStaticParams() {
  return [];
}

const STATIC_PAGES: { title: string; path: string; description: string }[] = [
  {
    title: "Home",
    path: "/",
    description: "ZyndAI landing page — your AI networking agent",
  },
  {
    title: "Terms of Service",
    path: "/terms",
    description: "ZyndAI terms of service",
  },
  {
    title: "Privacy Policy",
    path: "/privacy",
    description: "ZyndAI privacy policy",
  },
  {
    title: "Data Deletion",
    path: "/data-deletion",
    description: "How to delete your Google and LinkedIn data",
  },
  {
    title: "Security",
    path: "/security",
    description: "How Zynd protects your data",
  },
  {
    title: "Contact",
    path: "/contact",
    description: "Contact Zynd AI Inc",
  },
];

export async function GET() {
  const base = "https://persona.zynd.ai";

  const lines: string[] = [
    "# ZyndAI Persona",
    "> Your Persona finds people worth meeting, reaches out on your behalf, and books the times. You just show up.",
    "",
    "## Static Pages",
    ...STATIC_PAGES.map(
      (p) => `- [${p.title}](${base}${p.path}): ${p.description}`
    ),
    "",
    "## Dynamic Content",
    `- [Public Persona Cards](${base}/p/): Individual AI persona profiles with agent-to-agent chat`,
    `- [Published Pages](${base}/pages/): Agent-generated content pages (HTML, Markdown)`,
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
