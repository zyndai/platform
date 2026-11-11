import assert from "node:assert/strict";
import { test } from "node:test";
import { helpTopic, parseHelpOffer } from "./help-offer.ts";

test("a topic with a price separated by a middle dot is an offer", () => {
  assert.deepEqual(parseHelpOffer("Code review · $50"), { topic: "Code review", price: "$50" });
  assert.deepEqual(parseHelpOffer("System design review · $150"), { topic: "System design review", price: "$150" });
});

test("the other separators and currencies work, and thousands separators are kept", () => {
  assert.deepEqual(parseHelpOffer("Writing | £1,200.50"), { topic: "Writing", price: "£1,200.50" });
  assert.deepEqual(parseHelpOffer("Consulting • €75"), { topic: "Consulting", price: "€75" });
  assert.deepEqual(parseHelpOffer("Advisory · ₹1,500"), { topic: "Advisory", price: "₹1,500" });
});

test("surrounding spaces are ignored", () => {
  assert.deepEqual(parseHelpOffer("  Code review   ·   $50  "), { topic: "Code review", price: "$50" });
});

test("a plain topic is not an offer", () => {
  assert.equal(parseHelpOffer("Pricing strategy"), null);
  assert.equal(parseHelpOffer("Pricing: $50"), null, "needs the separator");
});

test("a malformed or free price is not an offer", () => {
  assert.equal(parseHelpOffer("Code review · 50"), null, "no currency symbol");
  assert.equal(parseHelpOffer("Code review · $"), null, "no amount");
  assert.equal(parseHelpOffer("Code review · $0"), null, "zero is not a price");
  assert.equal(parseHelpOffer("Code review · $50."), null, "trailing text");
});

test("helpTopic strips the price and leaves plain topics alone", () => {
  assert.equal(helpTopic("Code review · $50"), "Code review");
  assert.equal(helpTopic("Pricing strategy"), "Pricing strategy");
});
