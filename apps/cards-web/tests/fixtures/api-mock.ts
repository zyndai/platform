/**
 * Minimal fixture server for Playwright smoke tests. Playwright's page.route
 * can't intercept Next.js server-component fetches, so the dev server is
 * pointed at this instead (NEXT_PUBLIC_API_URL=http://127.0.0.1:3030).
 */
import http from "node:http";

const PORT = 3030;

export function cardFixture(handle: string, opts: { claimed?: boolean; name?: string } = {}): Record<string, unknown> {
  const { claimed = true, name = handle === "unclaimed" ? "Alex Rivera" : "Alice Chen" } = opts;
  return {
    id: `id-${handle}`,
    schema_version: "1.0",
    status: "published",
    handle,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-08T00:00:00Z",
    identity: {
      name,
      headline: "Engineer",
      location: "Bangalore",
      avatar_url: "",
      links: claimed ? { github: "https://github.com/alice", linkedin: "https://www.linkedin.com/in/alice-chen/" } : {},
    },
    citation_snippet: `${name} — Engineer in Bangalore.`,
    summary: "Engineer.",
    skills: [{ name: "TypeScript", level: "advanced", evidence_count: 2 }],
    projects: [],
    writing_samples: [],
    searchable_facts: [`${name} — working on agent tooling — Zynd`],
    sources: [],
    review: { status: "human_approved", reviewed_by: "user_self", reviewed_at: "2026-10-01T00:00:00Z" },
    experience_years: 4,
    industries: [],
    availability: "fulltime",
    working_on: ["Agent tooling"],
    can_help_with: ["Code review"],
    connect_with: [],
    love_talking_about: [],
    github_stats: null,
    claimed,
    alias: null,
  };
}

export function startFixtureServer(): Promise<void> {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
    const path = url.pathname;
    const json = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
      res.end(JSON.stringify(body));
    };

    if (req.method === "POST" && path === "/onboard/start") {
      return json(200, { job_id: "job1" });
    }
    if (path === "/onboard/job1") {
      return json(200, {
        status: "ready",
        card: { ...cardFixture("draft-card"), status: "draft", handle: "", claimed: undefined, id: "id-draft" },
        error: null,
        url_warnings: [],
      });
    }
    if (path === "/onboard/claim-candidates") {
      return json(200, { candidates: [] });
    }
    if (path === "/cards/mine") {
      return json(200, null);
    }
    if (path === "/cards/by-handle/unclaimed" || path === "/cards/by-handle/claimed") {
      const handle = path.split("/").pop()!;
      return json(200, cardFixture(handle, { claimed: handle === "claimed" }));
    }
    if (path === "/cards/by-handle/draft-card") {
      return json(200, { ...cardFixture("draft-card"), status: "draft", claimed: undefined });
    }
    if (path === "/cards") {
      return json(200, [cardFixture("claimed"), cardFixture("unclaimed", { claimed: false })]);
    }
    if (path.startsWith("/cards/handle-available/")) {
      return json(200, { available: true, slug: path.split("/").pop() });
    }
    if (path.startsWith("/cards/by-handle/") && req.method === "PATCH") {
      return json(200, cardFixture(path.split("/").pop()!));
    }
    if (path === "/v1/chat/claimed") {
      return json(403, { detail: "blocked in smoke" });
    }
    json(404, { detail: `no fixture for ${req.method} ${path}` });
  });

  return new Promise((resolve) => {
    server.listen(PORT, "127.0.0.1", () => resolve());
  });
}