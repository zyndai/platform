import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { CHIP_GROUPS, PERSONAS, PERSONA_VOCAB, addCustomValues, hasLabel, optionsFor } from "./chips.ts";

// The API prompts the model with the same vocabulary; the page renders it. They must not drift.
const TAXONOMY = new URL("../../../../../../services/cards-api/synthesis/taxonomy.py", import.meta.url);

test("every persona offers distinct labels for all four groups", () => {
  for (const { id } of PERSONAS) {
    for (const group of CHIP_GROUPS) {
      const labels = optionsFor(id, group);
      assert.ok(labels.length >= 8, `${id}/${group.field} has too few labels`);
      assert.equal(new Set(labels.map((l) => l.toLowerCase())).size, labels.length, `${id}/${group.field} repeats a label`);
    }
  }
});

test("the default offers no developer jargon", () => {
  const all = CHIP_GROUPS.flatMap((g) => optionsFor("general", g)).join(" ").toLowerCase();
  for (const word of ["rust", "wasm", "crdt", "open source", "code review", "b2b saas"]) assert.ok(!all.includes(word), word);
});

test("the persona vocabulary matches the one the API prompts with", { skip: !existsSync(TAXONOMY) }, () => {
  const source = readFileSync(TAXONOMY, "utf8");
  const json = /VOCAB_JSON = """([\s\S]*?)"""/.exec(source)?.[1];
  assert.ok(json, "VOCAB_JSON not found in taxonomy.py");
  assert.deepEqual(PERSONA_VOCAB, JSON.parse(json));
});

test("typed answers keep a preset's casing and skip repeats", () => {
  const options = optionsFor("marketing_sales", CHIP_GROUPS[0]);
  assert.deepEqual(addCustomValues(["Brand strategy"], options, "content marketing, BRAND STRATEGY, Podcasts"), ["Brand strategy", "Content marketing", "Podcasts"]);
  assert.ok(hasLabel(["Podcasts"], "podcasts"));
});
