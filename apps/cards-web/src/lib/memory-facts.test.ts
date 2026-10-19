import assert from "node:assert/strict";
import test from "node:test";

import {
  groupMemoryFacts,
  memoryFactKey,
  ownerFactCount,
  ownerFactGroups,
} from "./memory-facts.ts";

test("memoryFactKey collapses skill family and case", () => {
  assert.equal(
    memoryFactKey("has_skill", "Stocks"),
    memoryFactKey("has_expertise_in", "stocks"),
  );
});

test("memoryFactKey keeps working-on separate from building", () => {
  assert.notEqual(
    memoryFactKey("is_working_on", "SendPilot"),
    memoryFactKey("is_building", "sendpilot"),
  );
});

test("working-on and tools get their own groups, not Currently building", () => {
  const groups = groupMemoryFacts([
    { predicate: "is_building", object: "Verusa" },
    { predicate: "is_working_on", object: "LinkedIn outreach" },
    { predicate: "uses_tool", object: "Codex" },
  ]);
  const byKey = Object.fromEntries(groups.map((g) => [g.key, g]));
  assert.deepEqual(byKey.is_building.items.map((i) => i.object), ["Verusa"]);
  assert.deepEqual(byKey.is_working_on.items.map((i) => i.object), ["LinkedIn outreach"]);
  assert.equal(byKey.uses_tool.label, "Tools I use");
  assert.deepEqual(byKey.uses_tool.items.map((i) => i.object), ["Codex"]);
});

test("building comes before working on, tools come after expertise", () => {
  const keys = groupMemoryFacts([
    { predicate: "uses_tool", object: "Codex" },
    { predicate: "has_expertise_in", object: "Compliance" },
    { predicate: "is_working_on", object: "Outreach" },
    { predicate: "is_building", object: "Verusa" },
  ]).map((g) => g.key);
  assert.deepEqual(keys, ["is_building", "is_working_on", "has_expertise_in", "uses_tool"]);
});

test("unknown predicates are skipped, not rendered", () => {
  assert.deepEqual(groupMemoryFacts([{ predicate: "believes", object: "x" }]), []);
});

test("ownerFactGroups: count equals what is listed, nothing is silently capped", () => {
  const facts = Array.from({ length: 9 }, (_, i) => ({ predicate: "has_expertise_in", object: `Skill ${i}` }));
  const groups = ownerFactGroups(facts);
  assert.equal(ownerFactCount(groups), 9);
  assert.equal(groups[0].items.length, 9);
});

test("ownerFactGroups: dedupes across the skill family and skips unknown predicates", () => {
  const groups = ownerFactGroups([
    { predicate: "has_skill", object: "Stocks" },
    { predicate: "has_expertise_in", object: "stocks" },
    { predicate: "believes", object: "x" },
  ]);
  assert.equal(ownerFactCount(groups), 1);
});

test("ownerFactGroups: provenance and evidence come from details, falling back to the fact", () => {
  const groups = ownerFactGroups(
    [
      { predicate: "uses_tool", object: "Codex", provenance: "inferred" },
      { predicate: "is_building", object: "Verusa", provenance: "profile" },
    ],
    { [memoryFactKey("uses_tool", "Codex")]: { provenance: "agent", evidence: "The user has a tool: Codex" } },
  );
  const byKey = Object.fromEntries(groups.map((g) => [g.key, g.items[0]]));
  assert.equal(byKey.uses_tool.provenance, "agent");
  assert.equal(byKey.uses_tool.provenanceLabel, "Reported by your coding agent");
  assert.equal(byKey.uses_tool.evidence, "The user has a tool: Codex");
  assert.equal(byKey.is_building.provenance, "profile");
  assert.equal(byKey.is_building.evidence, undefined);
});

test("ownerFactGroups: items read as the fact alone, the group heading carries the label", () => {
  const groups = ownerFactGroups([
    { predicate: "uses_tool", object: "Codex" },
    { predicate: "is_building", object: "building Verusa" },
    { predicate: "is_seeking", object: "co_founder" },
  ]);
  const texts = groups.flatMap((g) => g.items.map((i) => i.text)).sort();
  assert.deepEqual(texts, ["Codex", "Verusa", "a co-founder"]);
});

test("ownerFactGroups: free-text facts from an older import land in Notes", () => {
  const groups = ownerFactGroups([{ content: "Prefers async work" }, { content: "prefers async work" }]);
  assert.deepEqual(groups.map((g) => g.key), ["notes"]);
  assert.equal(ownerFactCount(groups), 1);
});

// ── De-duplication across predicates (Memory write-path unification, safety net) ──

test("memoryFactKey folds tools into the tech family but keeps working-on apart", () => {
  assert.equal(memoryFactKey("uses_tool", "Docker"), memoryFactKey("has_expertise_in", "docker"));
  assert.equal(memoryFactKey("uses_tool", "javascript"), memoryFactKey("has_skill", "JS"));
  assert.notEqual(memoryFactKey("is_working_on", "SendPilot"), memoryFactKey("is_building", "sendpilot"));
  assert.notEqual(memoryFactKey("uses_tool", "Docker"), memoryFactKey("uses_tool", "Kubernetes"));
});

test("memoryFactKey ignores versions and aliases for technologies only", () => {
  assert.equal(memoryFactKey("has_skill", "Python 3.12"), memoryFactKey("has_skill", "python"));
  assert.equal(memoryFactKey("has_skill", "Next.js"), memoryFactKey("uses_tool", "nextjs"));
  assert.notEqual(memoryFactKey("is_building", "Next"), memoryFactKey("is_building", "Next.js"));
});

test("learning a technology folds into it; learning a field does not", () => {
  assert.equal(memoryFactKey("is_learning", "Rust"), memoryFactKey("has_skill", "rust"));
  assert.notEqual(
    memoryFactKey("is_learning", "machine learning"),
    memoryFactKey("has_expertise_in", "machine learning"),
  );
});

test("groupMemoryFacts shows a duplicated technology once, under the stronger predicate", () => {
  const groups = groupMemoryFacts([
    { predicate: "uses_tool", object: "javascript" },
    { predicate: "has_skill", object: "JavaScript" },
    { predicate: "is_learning", object: "JavaScript" },
    { predicate: "uses_tool", object: "Figma" },
  ]);
  const byKey = Object.fromEntries(groups.map((g) => [g.key, g.items.map((i) => i.object)]));
  assert.deepEqual(byKey.has_expertise_in, ["JavaScript"]);   // has_skill displays as expertise
  assert.deepEqual(byKey.uses_tool, ["Figma"]);
  assert.equal(byKey.is_learning, undefined);
});

test("groupMemoryFacts keeps a tool that is not also a skill, and a field being learned", () => {
  const groups = groupMemoryFacts([
    { predicate: "uses_tool", object: "Docker" },
    { predicate: "has_expertise_in", object: "machine learning" },
    { predicate: "is_learning", object: "machine learning" },
  ]);
  assert.deepEqual(groups.map((g) => g.key).sort(), ["has_expertise_in", "is_learning", "uses_tool"]);
});

test("ownerFactGroups: a duplicate technology counts once", () => {
  const groups = ownerFactGroups([
    { predicate: "uses_tool", object: "Docker" },
    { predicate: "has_expertise_in", object: "docker" },
  ]);
  assert.equal(ownerFactCount(groups), 1);
  assert.equal(groups[0].key, "has_expertise_in");
});

test("a trailing number is only a version for a known technology", () => {
  assert.notEqual(memoryFactKey("has_skill", "Skill 1"), memoryFactKey("has_skill", "Skill 2"));
  assert.notEqual(memoryFactKey("uses_tool", "Phase 2"), memoryFactKey("uses_tool", "Phase 3"));
  assert.equal(memoryFactKey("has_skill", "React 18"), memoryFactKey("uses_tool", "react"));
});
