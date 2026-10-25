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
    zynd_memory: handle === "owner"
      ? OWNER_FACTS.map(({ predicate, object, provenance }) => ({
          predicate, object, provenance, source: "declared", confidence: 0.9, approved_at: "2026-10-10T00:00:00Z",
        }))
      : undefined,
    claimed,
    alias: null,
  };
}

/** Public facts on the owner card: more than the editor shows collapsed, so the count and
 *  the list can be checked against each other. */
const OWNER_FACTS: Array<{ predicate: string; object: string; provenance: string; evidence: string | null }> = [
  { predicate: "is_building", object: "Verusa", provenance: "profile", evidence: null },
  { predicate: "is_working_on", object: "LinkedIn outreach", provenance: "agent", evidence: "The user works on the project: LinkedIn outreach" },
  { predicate: "is_learning", object: "Stablecoin regulation", provenance: "you", evidence: null },
  { predicate: "has_expertise_in", object: "Compliance engineering", provenance: "you", evidence: null },
  { predicate: "has_expertise_in", object: "AI agent orchestration", provenance: "you", evidence: null },
  { predicate: "has_expertise_in", object: "Team leadership", provenance: "profile", evidence: null },
  { predicate: "uses_tool", object: "Codex", provenance: "agent", evidence: "The user has a tool: Codex" },
  { predicate: "uses_tool", object: "Claude in Chrome", provenance: "agent", evidence: "The user has a tool: Claude in Chrome" },
];

export function startFixtureServer(): Promise<void> {
  const initialIntro = () => ({
    id: "33333333-3333-4333-8333-333333333333", handle: "owner",
    owner_uid: "11111111-1111-4111-8111-111111111111", requester_uid: "22222222-2222-4222-8222-222222222222",
    requester_name: "Bob", owner_name: "Alice Chen", why: "Could we discuss Python APIs for my project?",
    asks: ["meeting", "message"], status: "pending", permissions: { can_request_meetings: false },
    thread_id: "44444444-4444-4444-8444-444444444444", meeting_task_id: null as string | null,
    conversation_url: "http://127.0.0.1:3010/persona-conversation", created_at: "2026-10-13T00:00:00Z",
  });
  let intro = initialIntro();
  let sentIntros: ReturnType<typeof initialIntro>[] = [];
  const retryKeys = new Map<string, ReturnType<typeof initialIntro>>();
  let ownerCard = cardFixture("owner");
  let hasDuplicate = true;
  let anonymousMode = true;
  let humanViews = 12;
  let namedVisits = 0;
  const namedVisitIds = new Set<string>();
  let prefs = { weekly_digest: true, email_nudges: false, morning_digest: true };
  const ownerStatus = () => ({
    handle: "owner", card_id: "id-owner", name: "Alice Chen", visibility: ownerCard.status === "private" ? "private" : "public",
    completeness: { score: 75, actions: [{ section: "projects", title: "Add a project", href: "/p/owner/edit#projects" }] },
    inbox_count: 3, connection: { memory_connected: true, assistants_available: false },
    sources: [{ platform: "github", scraped_at: "2026-10-10T00:00:00Z", state: "fresh" }],
    activity: { available: true, views: humanViews, agent_hits: 4, intro_requests: null, queries: [], query_capture_available: false, chat_topics: [], chat_questions: [{ question: "What projects is Alice building?", category: "work", asked_at: "2026-10-15T10:00:00Z", truncated: false }, { question: '<img src=x onerror="window.questionHistoryXss=1">', category: "other", asked_at: "2026-10-15T09:00:00Z", truncated: false }] },
    visitors: { available: true, items: !anonymousMode && namedVisits ? [{ name: "Alice Chen", handle: "owner", visited_at: "2026-10-15T10:00:00Z", visits: namedVisits }] : [] },
    notification_prefs: prefs,
    duplicates: hasDuplicate ? [{ id: "id-old-owner", handle: "old-owner", name: "Alice Chen", status: "published" }] : [],
    nudges: [{ id: "n1", kind: "expiring", title: "What you are looking for expires within 3 days", href: "/p/owner/edit#memory" }],
  });
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
    const path = url.pathname;
    const json = (status: number, body: unknown) => {
      res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization,apikey,content-type,x-client-info,x-supabase-api-version", "Access-Control-Allow-Methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS" });
      res.end(JSON.stringify(body));
    };

    if (req.method === "OPTIONS") return json(200, {});
    // The directory list (/directory): two claimed people and one unclaimed.
    if (req.method === "GET" && path === "/cards") {
      return json(200, [cardFixture("alice"), cardFixture("bob", { name: "Bob Okafor" }), cardFixture("unclaimed", { claimed: false })]);
    }
    // The directory's ranked search: Alice (verified, freelance) then Bob; a query with "nobody" in it finds no one.
    if (req.method === "GET" && path === "/ask") {
      const q = url.searchParams.get("q") ?? "";
      const hit = (handle: string, name: string, score: number, extra: Record<string, unknown> = {}) => ({
        agent_id: `id-${handle}`, handle, name, headline: "Engineer", location: "Bangalore", skills: ["TypeScript"],
        availability: "", experience_years: 4, match_reasons: ["Matches your search terms"], verified: [],
        match_score: score, url: `http://127.0.0.1:3010/p/${handle}`, claimed: true, ...extra,
      });
      const results = q.includes("nobody") ? [] : [
        hit("alice", "Alice Chen", 0.92, { availability: "freelance", verified: ["github"] }),
        hit("bob", "Bob Okafor", 0.61),
      ];
      return json(200, { query: q, results, numberOfItems: results.length });
    }
    if (path === "/cards/by-handle/owner/beacon") {
      if (!req.headers.authorization) return json(401, { detail: "Unauthorized" });
      if (req.method === "DELETE") { ownerCard = { ...ownerCard, beacon: null }; return json(204, {}); }
      if (req.method === "PUT") {
        let raw = "";
        req.on("data", chunk => { raw += chunk; });
        req.on("end", () => {
          const created_at = new Date().toISOString();
          const beacon = { text: JSON.parse(raw).text, created_at, expires_at: new Date(Date.now() + 7 * 86400000).toISOString() };
          ownerCard = { ...ownerCard, beacon };
          return json(200, { beacon });
        });
        return;
      }
    }
    if (/^\/cards\/by-handle\/audit(?:-expired)?(?:\/view)?$/.test(path)) {
      const handle = path.includes("audit-expired") ? "audit-expired" : "audit";
      const start = Date.now() - (handle === "audit-expired" ? 8 : 0) * 86400000;
      const beacon = { text: "Seeking early builders to test a developer tool", created_at: new Date(start).toISOString(), expires_at: new Date(start + 7 * 86400000).toISOString() };
      const card = { ...cardFixture(handle), beacon,
        identity: { name: "Alice Chen", headline: "Engineer", location: "Bangalore", avatar_url: "", links: {} },
        skills: [{ name: "general", level: "intermediate", evidence_count: 0 }, { name: "TypeScript", level: "advanced", evidence_count: 1, evidence: [{ label: "alice/typescript-tool", url: "https://github.com/alice/typescript-tool", kind: "repository" }] }],
        calendly_url: "https://calendly.com/alice/example",
        zynd_memory: [{ predicate: "is_learning", object: "Founder of Example, a developer community" }],
      };
      return json(200, path.endsWith("/view") ? { ...card, facts: [{ type: "has_expertise_in", text: "general" }, { type: "is_learning", text: "Founder of Example, a developer community" }], cite_as: `http://127.0.0.1:3010/p/${handle}` } : card);
    }
    if (path === "/__s12/reset") { intro = initialIntro(); sentIntros = []; retryKeys.clear(); return json(200, {}); }
    if (path.endsWith("/intro-eligibility")) return json(200, { available: !path.includes("unclaimed"), agent_id: "test-agent" });
    if (path === "/cards/mine/intros") return json(200, { intros: url.searchParams.get("outgoing") === "true" ? sentIntros : [intro] });
    if (req.method === "POST" && (path.endsWith("/intro") || path.endsWith("/respond"))) {
      let raw = "";
      req.on("data", chunk => { raw += chunk; });
      req.on("end", () => {
        const body = JSON.parse(raw || "{}");
        if (path.endsWith("/intro")) {
          if (retryKeys.has(body.idempotency_key)) return json(200, retryKeys.get(body.idempotency_key));
          const sent = { ...initialIntro(), handle: "claimed", requester_name: "Alice Chen", owner_name: "Dan",
            requester_uid: "11111111-1111-4111-8111-111111111111", owner_uid: "22222222-2222-4222-8222-222222222222", why: body.why, asks: body.asks };
          retryKeys.set(body.idempotency_key, sent); sentIntros.push(sent); return json(200, sent);
        }
        intro.status = body.action === "accept" || body.action === "propose_time" ? "accepted" : body.action === "decline" ? "declined" : "blocked";
        intro.permissions.can_request_meetings = body.action === "propose_time" || body.allow_meetings === true;
        if (body.start_time) intro.meeting_task_id = "55555555-5555-4555-8555-555555555555";
        return json(200, intro);
      });
      return;
    }
    if (path === "/__s10/reset") {
      namedVisitIds.clear();
      ownerCard = cardFixture("owner"); hasDuplicate = true; anonymousMode = true; humanViews = 12; namedVisits = 0; prefs = { weekly_digest: true, email_nudges: false, morning_digest: true };
      return json(200, {});
    }
    if (path === "/events") {
      let raw = "";
      req.on("data", chunk => { raw += chunk; });
      req.on("end", () => {
        const events = JSON.parse(raw || "{}").events || [];
        for (const event of events) if (event.event === "view" && event.handle === "owner" && event.meta?.endpoint === "profile-page" && (req.headers["user-agent"] || "").includes("Mozilla/")) humanViews++;
        return json(204, {});
      });
      return;
    }
    if (path === "/cards/mine/visitor-privacy") {
      if (req.method === "PATCH") {
        let raw = "";
        req.on("data", chunk => { raw += chunk; });
        req.on("end", () => { const next = JSON.parse(raw).anonymous_mode; if (next !== anonymousMode) namedVisits = 0; anonymousMode = next; return json(200, { anonymous_mode: anonymousMode }); });
        return;
      }
      return json(200, { anonymous_mode: anonymousMode });
    }
    if (path.endsWith("/visit") && req.method === "POST") {
      let raw = "";
      req.on("data", chunk => { raw += chunk; });
      req.on("end", () => {
        const { visit_id } = JSON.parse(raw || "{}");
        const recorded = !anonymousMode && !namedVisitIds.has(visit_id);
        if (recorded) { namedVisitIds.add(visit_id); namedVisits++; }
        return json(200, { recorded });
      });
      return;
    }
    if (path === "/auth/v1/user") return json(200, { id: "11111111-1111-4111-8111-111111111111", aud: "authenticated", role: "authenticated", email: "owner@example.test", user_metadata: { name: "Alice Chen" } });
    if (path === "/cards/mine/status") return json(200, ownerStatus());
    if (path === "/cards/mine/digest-preview") return json(200, { html: "<h1>Your week on Zynd</h1><p>12 views</p>" });
    if (req.method === "POST" && path === "/cards/mine/summary-draft") {
      return json(200, {
        draft: "Alice Chen builds Verusa and is working on LinkedIn outreach. She is an expert in compliance engineering.",
        based_on: ["Building: Verusa", "Working on right now: LinkedIn outreach", "Expert in: Compliance engineering"],
      });
    }
    if (path === "/cards/mcp/suggestions") return json(200, { suggestions: [] });
    if (path === "/cards/mcp/card-facts") return json(200, { facts: OWNER_FACTS });
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
    if (path === "/cards/by-handle/memorycard") {
      // Public memory snapshot with one venture, one work stream and one tool, so the
      // card must put each in its own section (not fold them into "Currently building").
      const approved_at = new Date().toISOString();
      return json(200, {
        ...cardFixture("memorycard"),
        zynd_memory: [
          { predicate: "is_building", object: "Verusa", source: "declared", confidence: 0.97, approved_at },
          { predicate: "is_working_on", object: "LinkedIn outreach", source: "declared", confidence: 0.9, approved_at },
          { predicate: "uses_tool", object: "Codex", source: "declared", confidence: 0.9, approved_at },
          { predicate: "has_expertise_in", object: "Compliance engineering", source: "declared", confidence: 0.94, approved_at },
        ],
      });
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
