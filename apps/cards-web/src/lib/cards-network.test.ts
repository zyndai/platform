import assert from "node:assert/strict";
import test from "node:test";

import { briefIsEmpty, sharedSummary, type ConnectionBrief } from "./cards-network.ts";

const empty: ConnectionBrief = {
  partner: { handle: "ann", name: "Ann", headline: "" },
  now: { you: [], them: [] },
  shared: { skills: [], industries: [], interests: [], location: "" },
  suggested_topics: [],
};

test("a brief with nothing in it is empty, and so is no brief", () => {
  assert.equal(briefIsEmpty(empty), true);
  assert.equal(briefIsEmpty(null), true);
  assert.equal(briefIsEmpty(undefined), true);
});

test("any one section makes the brief worth showing", () => {
  assert.equal(briefIsEmpty({ ...empty, suggested_topics: ["Ask about: a fund"] }), false);
  assert.equal(briefIsEmpty({ ...empty, now: { you: [], them: [{ text: "Looking for investment" }] } }), false);
  assert.equal(briefIsEmpty({ ...empty, shared: { ...empty.shared, location: "Pune" } }), false);
});

test("the shared summary joins what is in common and where", () => {
  assert.equal(sharedSummary({ skills: ["Python"], industries: ["AI"], interests: [], location: "Pune, India" }), "Python, AI · Pune, India");
  assert.equal(sharedSummary({ skills: [], industries: [], interests: [], location: "Pune" }), "Pune");
  assert.equal(sharedSummary(empty.shared), "");
});
