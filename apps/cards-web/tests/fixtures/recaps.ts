import type { IncomingMessage, ServerResponse } from "node:http";
import type { Recap } from "../../src/lib/recaps";

export const RECAP_ID = "33333333-3333-4333-8333-333333333333";

export function recapFixtureApi() {
  let recap: Recap | null = null;
  const draft = (): Recap => ({
    id: RECAP_ID, period: "2026-09", handle: "owner", published_at: null, can_publish: true,
    selected_ids: ["launch", "vue", "release", "pr", "github"], caption: "My September on Zynd. Shipped a project and explored Vue.",
    snapshot: { name: "Alice Chen", label: "September 2026", timezone: "Asia/Kolkata", in_progress: false,
      generated_at: "2026-10-01T06:00:00Z", github_available: true,
      github_activity: { releases: "complete", pull_requests: "partial", truncated: false },
      history_note: "Includes public GitHub releases, merged PRs, and dated milestones you confirmed.",
      highlights: [
        { id: "launch", kind: "shipped", title: "Launchpad", date: "2026-09-12", source: "owner_confirmed", url: "https://example.com/launch" },
        { id: "vue", kind: "exploring", title: "Vue", date: "2026-09-20", source: "public_card", url: "https://vuejs.org/" },
        { id: "release", kind: "release", title: "alice/launchpad: v1.0", date: "2026-09-20", source: "github", url: "https://github.com/alice/launchpad/releases/tag/v1.0" },
        { id: "pr", kind: "pull_request", title: "team/project: Fix auth redirect", date: "2026-09-22", source: "github", url: "https://github.com/team/project/pull/1" },
        { id: "github", kind: "github", title: "GitHub contributions", count: 34, source: "github", url: "https://github.com/alice" },
      ] },
  });
  return (req: IncomingMessage, res: ServerResponse, path: string): boolean => {
    const json = (status: number, body: unknown) => { res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" }); res.end(JSON.stringify(body)); };
    if (path === "/__recaps/reset") { recap = null; json(200, {}); return true; }
    if (path === "/cards/mine/recaps" && req.method === "GET") {
      json(200, { handle: "owner", recaps: recap ? [recap] : [], projects: [{ name: "Launchpad", url: "https://example.com/launch" }], periods: ["2026-09", "2026-Q3"] }); return true;
    }
    if (path === "/cards/mine/recaps" && req.method === "POST") { recap = draft(); json(200, recap); return true; }
    if (path === "/cards/mine/milestones") { json(200, {}); return true; }
    if (path === `/cards/mine/recaps/${RECAP_ID}/unpublish`) { if (recap) recap.published_at = null; json(200, recap); return true; }
    if (path === `/cards/mine/recaps/${RECAP_ID}`) {
      if (req.method === "PATCH") {
        let body = ""; req.on("data", (chunk) => body += chunk); req.on("end", () => {
          const edit = JSON.parse(body);
          if (recap) recap = { ...recap, caption: edit.caption, selected_ids: edit.selected_ids, published_at: edit.publish ? "2026-10-01T09:00:00Z" : null };
          json(200, recap);
        });
      } else json(recap ? 200 : 404, recap);
      return true;
    }
    if (path === `/cards/by-handle/owner/recaps/${RECAP_ID}`) {
      if (!recap?.published_at) json(404, { detail: "Recap not found" });
      else { const { selected_ids, can_publish: _canPublish, ...publicRecap } = recap; void _canPublish;
        json(200, { ...publicRecap, snapshot: { ...recap.snapshot, highlights: recap.snapshot.highlights.filter((h) => selected_ids?.includes(h.id)) } }); }
      return true;
    }
    return false;
  };
}
