import assert from "node:assert/strict";
import test from "node:test";
import { generatedCaption, highlightLabel, recapStats, type Recap } from "./recaps.ts";

const recap: Recap = {
  id: "test", handle: "alice", period: "2026-10", published_at: null,
  selected_ids: ["repo", "github", "shipped", "learned"], caption: "",
  snapshot: { name: "Alice", label: "October 2026", timezone: "UTC", generated_at: "2026-11-01T00:00:00Z",
    in_progress: false, github_available: true, history_note: "",
    highlights: [
      { id: "repo", kind: "repository", title: "alice/tool", source: "github", url: "https://github.com/alice/tool" },
      { id: "github", kind: "github", title: "GitHub contributions", count: 34, source: "github", url: "https://github.com/alice" },
      { id: "shipped", kind: "shipped", title: "Launchpad", source: "owner_confirmed", url: "" },
      { id: "learned", kind: "learned", title: "Vue", source: "owner_confirmed", url: "" },
    ] },
};

test("selected facts form one short paragraph with accurate repository labels", () => {
  assert.equal(highlightLabel(recap.snapshot.highlights[0]), "New public repository alice/tool");
  assert.equal(generatedCaption(recap), "Hi connections, in October 2026, I created 1 new public repository (alice/tool), made 34 GitHub contributions, shipped Launchpad and learned Vue. Looking forward to sharing what comes next.");
  assert.deepEqual(recapStats(recap.snapshot.highlights.slice(0, 2)), [
    { value: "1", label: "new public repository" }, { value: "34", label: "GitHub contributions" },
  ]);
  assert.equal(generatedCaption({ ...recap, selected_ids: ["github"] }), "Hi connections, in October 2026, I made 34 GitHub contributions. Looking forward to sharing what comes next.");
  assert.equal(generatedCaption({ ...recap, selected_ids: [] }), "My October 2026 on Zynd: no highlights recorded yet.");
});

test("unknown contributions are omitted and an observed zero remains zero", () => {
  const missing = { ...recap, selected_ids: ["repo"] };
  assert.equal(generatedCaption(missing), "Hi connections, in October 2026, I created 1 new public repository (alice/tool). Looking forward to sharing what comes next.");
  const zero = { ...recap, selected_ids: ["github"], snapshot: { ...recap.snapshot,
    highlights: recap.snapshot.highlights.map((h) => h.kind === "github" ? { ...h, count: 0 } : h) } };
  assert.equal(generatedCaption(zero), "Hi connections, in October 2026, I made 0 GitHub contributions. Looking forward to sharing what comes next.");
});
