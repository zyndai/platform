import assert from "node:assert/strict";
import test from "node:test";

import { isWorkingOnStale, parseWorkingOnStamp, STALE_DAYS } from "./stale-signals.ts";

const NOW = Date.parse("2026-10-28T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW - days * 86_400_000).toISOString();

test("a card without a stamp is never stale", () => {
  for (const stamp of [undefined, null, "", "not a date", 42]) {
    assert.equal(isWorkingOnStale(stamp, ["Zynd Cards"], NOW), false, String(stamp));
  }
});

test("stale from STALE_DAYS on", () => {
  assert.equal(isWorkingOnStale(daysAgo(STALE_DAYS - 1), ["Zynd Cards"], NOW), false);
  assert.equal(isWorkingOnStale(daysAgo(STALE_DAYS), ["Zynd Cards"], NOW), true);
  assert.equal(isWorkingOnStale(daysAgo(400), ["Zynd Cards"], NOW), true);
});

test("an empty list has nothing to dim", () => {
  assert.equal(isWorkingOnStale(daysAgo(400), [], NOW), false);
  assert.equal(isWorkingOnStale(daysAgo(400), ["  "], NOW), false);
});

test("reads the API's microsecond ISO stamps", () => {
  assert.equal(parseWorkingOnStamp("2026-07-01T09:30:12.123456Z"), Date.parse("2026-07-01T09:30:12.123Z"));
  assert.equal(parseWorkingOnStamp("2026-07-01T09:30:12.123456+05:30"), Date.parse("2026-07-01T04:00:12.123Z"));
});
