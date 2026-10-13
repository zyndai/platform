import assert from "node:assert/strict";
import test from "node:test";

import { memoryFactKey } from "./memory-facts.ts";

test("memoryFactKey collapses skill family and case", () => {
  assert.equal(
    memoryFactKey("has_skill", "Stocks"),
    memoryFactKey("has_expertise_in", "stocks"),
  );
});

test("memoryFactKey folds working-on into building", () => {
  assert.equal(
    memoryFactKey("is_working_on", "SendPilot"),
    memoryFactKey("is_building", "sendpilot"),
  );
});
