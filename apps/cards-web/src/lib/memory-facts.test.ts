import assert from "node:assert/strict";
import test from "node:test";

import { groupMemoryFacts, memoryFactKey } from "./memory-facts.ts";

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
