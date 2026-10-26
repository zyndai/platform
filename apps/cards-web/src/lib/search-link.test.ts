import assert from "node:assert/strict";
import test from "node:test";

import { parseSearchRef, withSearch } from "./search-link.ts";

const SID = "3f2b8c4e-6a51-4c43-9d1e-0b5a1f7e2d90";

test("a profile link remembers the search and the person's place in it", () => {
  assert.equal(withSearch("/p/ada", SID, 2), `/p/ada?sid=${SID}&r=2`);
  assert.equal(withSearch("/p/ada?preview=visitor", SID, 1), `/p/ada?preview=visitor&sid=${SID}&r=1`);
});

test("without a usable search id or rank the link is left alone", () => {
  assert.equal(withSearch("/p/ada", undefined, 1), "/p/ada");
  assert.equal(withSearch("/p/ada", "not-an-id", 1), "/p/ada");
  assert.equal(withSearch("/p/ada", SID, 0), "/p/ada");
  assert.equal(withSearch("/p/ada", SID, 101), "/p/ada");
});

test("a search reference is read back only when both parts are well formed", () => {
  assert.deepEqual(parseSearchRef(SID, "3"), { searchId: SID, rank: 3 });
  assert.deepEqual(parseSearchRef(SID.toUpperCase(), ["4", "9"]), { searchId: SID, rank: 4 });
  for (const [sid, r] of [[undefined, "1"], [SID, undefined], ["x", "1"], [SID, "0"], [SID, "1.5"], [SID, "abc"], [SID, "500"]] as const) {
    assert.equal(parseSearchRef(sid, r), null);
  }
});
