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
  let ownerCard = cardFixture("owner");
  let hasDuplicate = true;
  let prefs = { weekly_digest: true, email_nudges: false };
  const ownerStatus = () => ({
    handle: "owner", card_id: "id-owner", name: "Alice Chen", visibility: ownerCard.status === "private" ? "private" : "public",
    completeness: { score: 75, actions: [{ section: "projects", title: "Add a project", href: "/p/owner/edit#projects" }] },
    inbox_count: 3, connection: { memory_connected: true, assistants_available: false },
    sources: [{ platform: "github", scraped_at: "2026-10-10T00:00:00Z", state: "fresh" }],
    activity: { available: true, views: 12, agent_hits: 4, intro_requests: null, queries: [], query_capture_available: false },
    notification_prefs: prefs,
    duplicates: hasDuplicate ? [{ id: "id-old-owner", handle: "old-owner", name: "Alice Chen", status: "published" }] : [],
    nudges: [{ id: "n1", kind: "expiring", title: "What you are looking for expires within 3 days", href: "/p/owner/edit#memory" }],
  });
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
    const path = url.pathname;
    const json = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization,apikey,content-type,x-client-info,x-supabase-api-version", "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS" });
      res.end(JSON.stringify(body));
    };

    if (req.method === "OPTIONS") return json(200, {});
    if (path === "/__s10/reset") {
      ownerCard = cardFixture("owner"); hasDuplicate = true; prefs = { weekly_digest: true, email_nudges: false };
      return json(200, {});
    }
    if (path === "/auth/v1/user") return json(200, { id: "11111111-1111-4111-8111-111111111111", aud: "authenticated", role: "authenticated", email: "owner@example.test", user_metadata: { name: "Alice Chen" } });
    if (path === "/cards/mine/status") return json(200, ownerStatus());
    if (path === "/cards/mine/digest-preview") return json(200, { html: "<h1>Your week on Zynd</h1><p>12 views</p>" });
    if (path === "/cards/mcp/suggestions") return json(200, { suggestions: [] });
    if (path === "/cards/redirect/old-owner") return json(200, { handle: hasDuplicate ? null : "owner" });
    if (path.startsWith("/cards/redirect/")) return json(200, { handle: null });
    if (path === "/cards/by-handle/owner") return json(200, ownerCard);
    if (path === "/cards/by-handle/owner/view") return json(200, { ...ownerCard, facts: [], cite_as: "http://127.0.0.1:3010/p/owner" });
    if (req.method === "PATCH" || (req.method === "POST" && path === "/cards/merge")) {
      if (path.startsWith("/cards/by-handle/owner/sections/") || path === "/cards/mine/notification-prefs" || path === "/cards/mine/visibility" || path === "/cards/merge") {
        let raw = "";
        req.on("data", chunk => { raw += chunk; });
        req.on("end", () => {
          const data = JSON.parse(raw || "{}");
          if (path.includes("/sections/")) { ownerCard = { ...ownerCard, ...data.patch }; return json(200, ownerCard); }
          if (path.endsWith("notification-prefs")) { prefs = data; return json(200, prefs); }
          if (path.endsWith("visibility")) { ownerCard.status = data.public ? "published" : "private"; return json(200, { visibility: data.public ? "public" : "private" }); }
          hasDuplicate = false;
          return json(200, { handle: "owner", merged: 1 });
        });
        return;
      }
    }

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
      const linkedin = url.searchParams.get("linkedin") || "";
      // Non-empty lookalike when the pasted URL mentions alice — drives claim-first UI.
      if (/alice/i.test(linkedin)) {
        return json(200, {
          candidates: [{
            handle: "unclaimed",
            name: "Alex Rivera",
            headline: "Engineer",
          }],
        });
      }
      return json(200, { candidates: [] });
    }
    if (req.method === "POST" && path === "/onboard/job1/publish") {
      return json(200, {
        ...cardFixture("alice-chen"),
        handle: "alice-chen",
        claim_token: "smoke-claim-token",
      });
    }
    if (path === "/cards/mine") {
      if (req.headers.authorization) return json(200, { card: ownerCard, handle: "owner" });
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
