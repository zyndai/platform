import assert from "node:assert/strict";
import test from "node:test";

import { LENSES, lensPath, lensStyles, lensSummary, parseLens, type LensCardFields } from "./lenses.ts";

function card(overrides: Partial<LensCardFields> = {}): LensCardFields {
  return {
    name: "Ada Lovelace",
    working_on: [],
    can_help_with: [],
    connect_with: [],
    love_talking_about: [],
    experience_years: null,
    ...overrides,
  };
}

const lens = (id: string) => {
  const found = parseLens(id);
  assert.ok(found, `lens ${id}`);
  return found;
};

test("a lens value resolves case-insensitively, aliases included", () => {
  assert.equal(parseLens("investors")?.id, "investors");
  assert.equal(parseLens(" Hiring ")?.id, "hiring");
  assert.equal(parseLens("hires")?.id, "hiring");
  assert.equal(parseLens("client")?.id, "clients");
  assert.equal(parseLens("collaborator")?.id, "collaborators");
});

test("an unknown, empty or missing lens is the plain card", () => {
  assert.equal(parseLens(undefined), null);
  assert.equal(parseLens(""), null);
  assert.equal(parseLens("   "), null);
  assert.equal(parseLens("press"), null);
  assert.equal(parseLens("constructor"), null);
  assert.equal(parseLens([]), null);
});

test("a repeated lens param uses the first value", () => {
  assert.equal(parseLens(["clients", "investors"])?.id, "clients");
});

test("every lens is internally consistent", () => {
  for (const l of LENSES) {
    assert.equal(new Set(l.lead).size, l.lead.length, `${l.id} lead has repeats`);
    for (const id of l.highlight) assert.ok(l.lead.includes(id), `${l.id} highlights ${id} outside its lead`);
    for (const id of l.fold) assert.ok(!l.lead.includes(id), `${l.id} both leads with and folds ${id}`);
    assert.ok(!l.lead.includes("explore") && !l.fold.includes("explore"), `${l.id} moves the closing footer`);
  }
});

test("the lens link is the card path plus the canonical lens id", () => {
  assert.equal(lensPath("ada", "investors"), "/p/ada?lens=investors");
  assert.equal(lensPath("a b", "hiring"), "/p/a%20b?lens=hiring");
});

test("the summary says when the owner is looking for this reader", () => {
  const summary = lensSummary(lens("investors"), card({ connect_with: ["Founders", "investors"], working_on: ["Zynd", "Agents", "Third"] }));
  assert.equal(summary, "Ada wants to meet investors. Working on Zynd, Agents.");
});

test("the summary reads only the field each reader asks about first", () => {
  const fields = card({
    working_on: ["Zynd"],
    can_help_with: ["Pricing", "Hiring", "Fundraising"],
    love_talking_about: ["Typography"],
    experience_years: 12,
  });
  assert.equal(lensSummary(lens("hiring"), fields), "12 years of experience.");
  assert.equal(lensSummary(lens("clients"), fields), "Can help with Pricing, Hiring.");
  assert.equal(lensSummary(lens("collaborators"), fields), "Loves talking about Typography.");
  assert.equal(lensSummary(lens("hiring"), card({ experience_years: 1 })), "1 year of experience.");
  assert.equal(lensSummary(lens("hiring"), card({ experience_years: 0, can_help_with: ["Code review"] })), "Can help with Code review.");
  assert.equal(lensSummary(lens("collaborators"), card({ working_on: ["A book"] })), "Working on A book.");
});

test("an empty card gives an empty summary, and blank entries are skipped", () => {
  for (const l of LENSES) assert.equal(lensSummary(l, card()), "");
  assert.equal(lensSummary(lens("clients"), card({ can_help_with: ["  ", "Branding"] })), "Can help with Branding.");
});

test("a nameless card still reads as a sentence", () => {
  assert.equal(lensSummary(lens("clients"), card({ name: " ", connect_with: ["Clients"] })), "Wants to meet clients.");
});

test("styles pull the lead up in order and keep the footer last", () => {
  const css = lensStyles(lens("investors"));
  assert.match(css, /\[data-section\] \{ order: 5; \}/);
  assert.match(css, /\[data-section="projects"\] \{ order: 1; \}/);
  assert.match(css, /\[data-section="experience"\] \{ order: 4; \}/);
  assert.match(css, /\[data-section="gallery"\] \{ order: 6; \}/);
  assert.match(css, /\[data-section="explore"\] \{ order: 7; \}/);
  assert.match(css, /\[data-section="projects"\], [^{]*\[data-section="github"\] \{ border-radius/);
  assert.match(css, /\[data-section="gallery"\]:focus-within \{ max-height: none;/);
});
