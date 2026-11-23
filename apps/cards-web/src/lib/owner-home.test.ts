import assert from "node:assert/strict";
import test from "node:test";
import { ownerErrorMessage, ownerRequest } from "./owner-home.ts";

test("owner errors preserve application errors and format FastAPI validation details", () => {
  assert.equal(ownerErrorMessage("This period has not started yet"), "This period has not started yet");
  assert.equal(ownerErrorMessage([
    { loc: ["body", "period"], msg: "Field required", input: { token: "never display input" } },
    { loc: ["body", "refresh"], msg: "Input should be a valid boolean" },
  ]), "period: Field required; refresh: Input should be a valid boolean");
  for (const detail of [null, undefined, {}, [], [{ input: "private" }]]) {
    assert.equal(ownerErrorMessage(detail), "Could not save. Please try again.");
  }
});

test("a rejected recap request throws a readable error without losing the validation reason", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ detail: [
    { loc: ["body", "period"], msg: "String should have at most 7 characters", input: "invalid period" },
  ] }), { status: 422, headers: { "Content-Type": "application/json" } }));
  await assert.rejects(ownerRequest("mine/recaps", "test-only", "POST", { period: "invalid period" }), {
    message: "period: String should have at most 7 characters",
  });
});
