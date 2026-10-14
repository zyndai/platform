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
