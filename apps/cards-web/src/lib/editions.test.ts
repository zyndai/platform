import assert from "node:assert/strict";
import test from "node:test";

import { isEditionPickable, readEdition } from "./editions.ts";

test("a stored edition is read with defaults filled in", () => {
  assert.deepEqual(readEdition({ id: "mumbai-26" }), { id: "mumbai-26", mood: "night", banner: "waterfront", here_for: null });
  assert.deepEqual(
    readEdition({ id: "mumbai-26", mood: "dusk", banner: "gateway", here_for: "hacking" }),
    { id: "mumbai-26", mood: "dusk", banner: "gateway", here_for: "hacking" },
  );
});

test("anything the page can't render reads as the classic card", () => {
  for (const raw of [undefined, null, "", "mumbai-26", [], {}, { id: "devcon-9" }, { id: "mumbai-26", mood: "neon" }, { id: "mumbai-26", here_for: "partying" }, { id: "mumbai-26", banner: "devcon" }]) {
    assert.equal(readEdition(raw), null, JSON.stringify(raw));
  }
});

test("the Mumbai edition can be picked through 30 Nov 2026 IST only", () => {
  assert.equal(isEditionPickable("mumbai-26", Date.parse("2026-11-30T23:59:00+05:30")), true);
  assert.equal(isEditionPickable("mumbai-26", Date.parse("2026-12-01T00:00:00+05:30")), false);
});
