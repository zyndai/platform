import assert from "node:assert/strict";
import test from "node:test";

import { ASK_KINDS, endsIn, hostnameOf, isAskKind, kindLabel, liveFromBeacon, safeAskUrl, validateAskUrl } from "./asks.ts";

test("the kinds and their labels match the server's list", () => {
  assert.deepEqual(
    ASK_KINDS.map((k) => [k.id, k.label]),
    [
      ["team", "Building a team"],
      ["cofounder", "Looking for a co-founder"],
      ["hiring", "Hiring"],
      ["work", "Open to work"],
      ["feedback", "Want feedback"],
      ["users", "Looking for early users"],
      ["investors", "Raising money"],
      ["other", "Something else"],
    ],
  );
  assert.ok(ASK_KINDS.every((k) => k.placeholder.length > 10));
});

test("a missing or unknown kind reads as something else", () => {
  assert.equal(kindLabel("hiring"), "Hiring");
  assert.equal(kindLabel(undefined), "Something else");
  assert.equal(kindLabel(null), "Something else");
  assert.equal(kindLabel("crypto"), "Something else");
  assert.equal(isAskKind("team"), true);
  assert.equal(isAskKind("toString"), false);
});

test("a link is optional and must be http or https", () => {
  assert.deepEqual(validateAskUrl(""), { ok: true, url: null });
  assert.deepEqual(validateAskUrl("   "), { ok: true, url: null });
  assert.deepEqual(validateAskUrl(" https://ethglobal.com/events/bangkok "), { ok: true, url: "https://ethglobal.com/events/bangkok" });
  assert.deepEqual(validateAskUrl("http://localhost:3000/x"), { ok: true, url: "http://localhost:3000/x" });
  for (const bad of ["javascript:alert(1)", "ftp://files.test/a", "data:text/html,hi", "example.com", "https://", "https://a.test/has space", "mailto:a@b.test"]) {
    assert.equal(validateAskUrl(bad).ok, false, bad);
  }
  assert.equal(validateAskUrl("https://a.test/" + "x".repeat(500)).ok, false);
  assert.equal(validateAskUrl("https://a.test/" + "x".repeat(400)).ok, true);
});

test("only http links are drawn and the host is what people see", () => {
  assert.equal(safeAskUrl("https://www.ethglobal.com/x"), "https://www.ethglobal.com/x");
  assert.equal(safeAskUrl("javascript:alert(1)"), "");
  assert.equal(safeAskUrl(null), "");
  assert.equal(hostnameOf("https://www.ethglobal.com/events/bangkok"), "ethglobal.com");
  assert.equal(hostnameOf("not a url"), "not a url");
});

test("the time left says days, then today", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  assert.equal(endsIn("2026-11-04T12:00:00Z", now), "Ends in 7 days");
  assert.equal(endsIn("2026-10-30T13:00:00Z", now), "Ends in 2 days");
  assert.equal(endsIn("2026-11-04T11:59:00Z", now), "Ends in 7 days");
  assert.equal(endsIn("2026-10-29T13:00:00Z", now), "Ends in 1 day");
  assert.equal(endsIn("2026-10-28T20:00:00Z", now), "Ends today");
  assert.equal(endsIn("2026-10-28T11:00:00Z", now), "Ended");
});

test("a live ask comes from a beacon that is in its window, with a known kind or none", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  const beacon = { id: "a1", text: "Hi", kind: "team", url: "https://a.test", created_at: "2026-10-27T12:00:00Z", expires_at: "2026-11-03T12:00:00Z" };
  assert.deepEqual(liveFromBeacon(beacon, now), { ...beacon, routed: 0, offer_count: 0 });
  assert.equal(liveFromBeacon({ ...beacon, kind: "nope" }, now)?.kind, null);
  assert.equal(liveFromBeacon({ ...beacon, kind: undefined, url: undefined }, now)?.url, null);
  assert.equal(liveFromBeacon({ ...beacon, expires_at: "2026-10-28T11:00:00Z" }, now), null);
  assert.equal(liveFromBeacon(null, now), null);
});
