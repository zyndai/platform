import assert from "node:assert/strict";
import test from "node:test";
import { generatedCaption, highlightLabel, recapStats, type Recap } from "./recaps.ts";

const recap: Recap = {
  id: "test", handle: "alice", period: "2026-10", published_at: null,
  selected_ids: ["release", "pr"], caption: "",
  snapshot: { name: "Alice", label: "October 2026", timezone: "UTC", generated_at: "2026-11-01T00:00:00Z",
    in_progress: false, github_available: false, history_note: "",
    highlights: [
      { id: "release", kind: "release", title: "alice/tool: v1", source: "github", url: "https://github.com/alice/tool/releases/tag/v1" },
      { id: "pr", kind: "pull_request", title: "team/repo: Fix", source: "github", url: "https://github.com/team/repo/pull/1" },
      { id: "hidden", kind: "shipped", title: "Hidden project", source: "owner_confirmed", url: "" },
    ] },
};

test("imported evidence has accurate labels and does not claim projects shipped", () => {
  assert.equal(highlightLabel(recap.snapshot.highlights[0]), "Released alice/tool: v1");
  assert.equal(highlightLabel(recap.snapshot.highlights[1]), "Merged PR team/repo: Fix");
  assert.equal(generatedCaption(recap), "My October 2026 on Zynd\nReleased alice/tool: v1.\nMerged PR team/repo: Fix.");
  assert.deepEqual(recapStats(recap.snapshot.highlights.slice(0, 2)), [
    { value: "1", label: "release" }, { value: "1", label: "merged PR" },
  ]);
  assert.equal(generatedCaption({ ...recap, selected_ids: ["pr"] }), "My October 2026 on Zynd\nMerged PR team/repo: Fix.");
});
