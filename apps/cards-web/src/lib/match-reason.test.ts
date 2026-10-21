import assert from "node:assert/strict";
import test from "node:test";

import { ageHint, formatMatchReason, verifiedLabels } from "./match-reason.ts";

test("plain reasons are shown as they are", () => {
  assert.equal(formatMatchReason("Based in Pune"), "Based in Pune");
  assert.equal(formatMatchReason({ type: "other", text: "Skills: AI" }), "Skills: AI");
  assert.equal(formatMatchReason({ type: "memory", text: "" }), "");
});

test("a memory reason says how current the approved fact is", () => {
  assert.equal(formatMatchReason({ type: "memory", text: "Backs dev tools", age_days: 2 }), "Memory: Backs dev tools (this week)");
  assert.equal(formatMatchReason({ type: "memory", text: "Backs dev tools", age_days: 14 }), "Memory: Backs dev tools (2 weeks ago)");
  assert.equal(formatMatchReason({ type: "memory", text: "Backs dev tools", age_days: 95 }), "Memory: Backs dev tools (3 months ago)");
});

test("an unknown age adds nothing and never throws", () => {
  for (const days of [undefined, null, -1, Number.NaN]) assert.equal(ageHint(days), "");
  assert.equal(formatMatchReason({ type: "memory", text: "x" }), "Memory: x");
});

test("verified labels use known providers only", () => {
  assert.deepEqual(verifiedLabels(["linkedin", "made_up", "work_email"]), ["LinkedIn", "work email"]);
  assert.deepEqual(verifiedLabels(undefined), []);
});
