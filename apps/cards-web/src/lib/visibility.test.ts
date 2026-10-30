import assert from "node:assert/strict";
import test from "node:test";

import {
  displayUrl,
  parseVisibilityReport,
  validateVisibilityInput,
  visibilityCta,
  visibilityStatus,
  type VisibilityReport,
} from "./visibility.ts";

function report(overrides: Partial<VisibilityReport> = {}): VisibilityReport {
  return {
    model: "perplexity/sonar",
    model_label: "Perplexity Sonar",
    found: true,
    answer: "Ada is an engineer.",
    cited_urls: [],
    cites_zynd: false,
    zynd_card: null,
    cached: false,
    checked_at: "2026-10-28T00:00:00Z",
    ...overrides,
  };
}

test("the status line follows what the AI found", () => {
  assert.equal(visibilityStatus(report({ found: false })), "not_found");
  assert.equal(visibilityStatus(report()), "found_without_zynd");
  assert.equal(visibilityStatus(report({ cites_zynd: true })), "cites_zynd");
});

test("no card: create one, carrying the link the visitor gave", () => {
  assert.deepEqual(visibilityCta(report(), null), { label: "Get your Zynd card", href: "/create?ref=visibility" });
  assert.deepEqual(visibilityCta(report(), "https://example.org/ada?x=1&y=2"), {
    label: "Get your Zynd card",
    href: "/create?ref=visibility&url=https%3A%2F%2Fexample.org%2Fada%3Fx%3D1%26y%3D2",
  });
});

test("an existing card: claim it when unclaimed, view it when claimed", () => {
  const unclaimed = report({ zynd_card: { handle: "ada-lovelace", name: "Ada Lovelace", claimed: false } });
  assert.deepEqual(visibilityCta(unclaimed, "https://example.org"), { label: "This is you? Claim it", href: "/p/ada-lovelace" });
  const claimed = report({ zynd_card: { handle: "ada-lovelace", name: "Ada Lovelace", claimed: true } });
  assert.deepEqual(visibilityCta(claimed, null), { label: "View your card", href: "/p/ada-lovelace" });
});

test("input is checked the same way the API checks it", () => {
  assert.equal(validateVisibilityInput("Ada Lovelace", ""), null);
  assert.equal(validateVisibilityInput("Ada", "https://example.org/ada"), null);
  assert.match(validateVisibilityInput(" a ", "") ?? "", /at least 2/);
  assert.match(validateVisibilityInput("x".repeat(101), "") ?? "", /at most 100/);
  assert.match(validateVisibilityInput("Ada", "example.org") ?? "", /http/);
  assert.match(validateVisibilityInput("Ada", "javascript:alert(1)") ?? "", /http/);
  assert.match(validateVisibilityInput("Ada", `https://example.org/${"a".repeat(300)}`) ?? "", /at most 300/);
});

test("source links are shown short and without www", () => {
  assert.equal(displayUrl("https://www.example.org/"), "example.org");
  assert.equal(displayUrl("https://en.wikipedia.org/wiki/Ada"), "en.wikipedia.org/wiki/Ada");
  assert.ok(displayUrl(`https://example.org/${"a".repeat(100)}`).endsWith("…"));
});

test("only a well-formed report is accepted, and only http(s) sources survive", () => {
  assert.equal(parseVisibilityReport(null), null);
  assert.equal(parseVisibilityReport({ found: "yes" }), null);
  assert.equal(parseVisibilityReport({ ...report(), zynd_card: { handle: 3 } }), null);
  const parsed = parseVisibilityReport({ ...report(), cited_urls: ["https://example.org", "javascript:alert(1)", 4] });
  assert.deepEqual(parsed?.cited_urls, ["https://example.org"]);
  const withCard = parseVisibilityReport({ ...report(), zynd_card: { handle: "ada", claimed: true } });
  assert.deepEqual(withCard?.zynd_card, { handle: "ada", name: "", claimed: true });
});
