import assert from "node:assert/strict";
import test from "node:test";

import { applyEdits, buildUserAnswers, cleanHandle, detectKind, finalizeCard, liveIdentity, normalizeUrl, statusLine, workKey } from "./model.ts";

const source = (url: string, preview: object, state = "done") => ({ url, kind: detectKind(url), state, preview }) as never;

const card = (over: Record<string, unknown> = {}) => ({
  identity: { name: "Ada", headline: "Engineer", location: "London", avatar_url: "", links: {} },
  summary: "Writes compilers.",
  citation_snippet: "Ada, on Zynd.",
  skills: [{ name: "Rust", level: "advanced", evidence_count: 3 }],
  projects: [{ name: "a", url: "https://a", description: "", source: "github" }, { name: "b", url: "https://b", description: "", source: "github" }],
  writing_samples: [{ platform: "x", excerpt: "one", url: "", posted_at: "" }, { platform: "x", excerpt: "two", url: "", posted_at: "" }],
  searchable_facts: ["Ada — Rust — Zynd"],
  working_on: [], can_help_with: [], connect_with: [], love_talking_about: [],
  ...over,
}) as never;

const none = { working_on: [], can_help_with: [], connect_with: [], love_talking_about: [] };

test("links are normalised, and a bare profile host asks for a username", () => {
  assert.deepEqual(normalizeUrl("github.com/ada"), { url: "https://github.com/ada" });
  assert.deepEqual(normalizeUrl("  "), null);
  assert.ok("error" in normalizeUrl("https://www.linkedin.com/")!);
  assert.ok("error" in normalizeUrl("nonsense")!);
  assert.equal(detectKind("https://www.linkedin.com/in/ada"), "linkedin");
});

test("handles are lower-cased, stripped and length-checked", () => {
  assert.equal(cleanHandle("Ada_Lovelace!"), "adalovelace");
  assert.equal(cleanHandle("a"), "");
});

test("the live identity takes each field from the strongest finished source", () => {
  const sources = [
    source("https://github.com/ada", { name: "ada", headline: "Compilers", avatar: "gh.jpg", facts: ["9 public repos"] }),
    source("https://www.linkedin.com/in/ada", { name: "Ada Lovelace", avatar: "li.jpg", posts: ["A post"] }),
    source("https://x.com/ada", { name: "AdaL", avatar: "x.jpg" }, "reading"),
  ];
  const live = liveIdentity(sources);
  assert.equal(live.name, "Ada Lovelace");
  assert.equal(live.avatar, "li.jpg");
  assert.equal(live.headline, "Compilers"); // LinkedIn had none, so GitHub's bio fills in
  assert.deepEqual(live.facts, ["9 public repos"]);
  assert.deepEqual(live.posts, ["A post"]);
});

test("the status line follows the stage", () => {
  const reading = [source("https://github.com/ada", {}, "reading"), source("https://x.com/ada", {}, "reading")];
  assert.equal(statusLine(reading, "reading"), "Reading 2 sources…");
  assert.equal(statusLine([], "synthesizing"), "Writing your summary and skills…");
  assert.match(statusLine([], "ready"), /Draft ready/);
});

test("edits sit on top of the newest build, so a rebuild never undoes them", () => {
  const rebuilt = card({ summary: "Fresh from LinkedIn.", skills: [] });
  rebuilt.identity.headline = "Fresh headline";
  const out = applyEdits(rebuilt, { name: "Countess Ada", summary: "My own words.", edition: null });
  assert.equal(out.identity.name, "Countess Ada");
  assert.equal(out.summary, "My own words.");
  assert.equal(out.identity.edition, null);
  assert.equal(out.identity.headline, "Fresh headline");
  assert.equal(out.skills.length, 0);
  assert.equal(applyEdits(rebuilt, { summary: "" }).summary, ""); // emptied on purpose is still an edit
});

test("publishing applies the person's picks, an emptied group included", () => {
  const draft = card({ working_on: ["Open source"], can_help_with: ["Hiring"] });
  const out = finalizeCard(draft, { ...none, can_help_with: ["Code review", "rust"] }, "  Pune  ", new Set(["project:https://a", "sample:1"]));
  assert.deepEqual(out.working_on, []); // unticked: must not fall back to the LLM's guess
  assert.deepEqual(out.can_help_with, ["Code review", "rust"]);
  assert.deepEqual(out.skills.map((s) => s.name), ["Rust", "Code review"]); // "rust" already a skill
  assert.equal(out.identity.location, "Pune");
  assert.deepEqual(out.projects.map((p) => p.name), ["b"]);
  assert.deepEqual(out.writing_samples.map((w) => w.excerpt), ["one"]);
});

test("a blank location never wipes the scraped one", () => {
  assert.equal(finalizeCard(card(), none, "   ", new Set()).identity.location, "London");
});

test("answers sent with publish use the keys the API reads", () => {
  assert.deepEqual(
    buildUserAnswers({ ...none, working_on: ["A", "B"], can_help_with: ["C"] }, "Pune", "", "https://cal"),
    { working_on: "A, B", can_help: "C", location: "Pune", google_calendar_url: "https://cal" },
  );
});

test("newsletters and design portfolios are told apart from plain websites", () => {
  assert.equal(detectKind("https://ada.substack.com/archive"), "writing");
  assert.equal(detectKind("https://medium.com/@ada"), "writing");
  assert.equal(detectKind("https://www.behance.net/ada"), "portfolio");
  assert.equal(detectKind("https://dribbble.com/ada"), "portfolio");
  assert.equal(detectKind("https://ada.dev"), "website");
  assert.ok("error" in normalizeUrl("https://www.behance.net/")!);
  assert.deepEqual(normalizeUrl("behance.net/ada"), { url: "https://behance.net/ada" });
});

test("a newsletter's posts and a portfolio's covers show before the card is written", () => {
  const live = liveIdentity([
    source("https://ada.substack.com", { posts: ["How I hire designers who ship"], headline: "Ada's notes" }),
    source("https://www.behance.net/ada", { images: ["https://cdn/a.jpg", "https://cdn/b.jpg"], facts: ["2 projects"] }),
  ]);
  assert.deepEqual(live.posts, ["How I hire designers who ship"]);
  assert.deepEqual(live.images, ["https://cdn/a.jpg", "https://cdn/b.jpg"]);
  assert.equal(live.headline, "Ada's notes");
  assert.deepEqual(live.facts, ["2 projects"]);
});

test("a project cover the person removed is not published", () => {
  const withWork = card({ work_gallery: [
    { title: "Orbit", url: "https://b/1", image_url: "https://cdn/a.jpg", source: "behance" },
    { title: "Posters", url: "https://b/2", image_url: "https://cdn/b.jpg", source: "behance" },
  ] });
  const out = finalizeCard(withWork, none, "", new Set([workKey(1)]));
  assert.deepEqual(out.work_gallery?.map((w) => w.title), ["Orbit"]);
  assert.deepEqual(finalizeCard(card(), none, "", new Set()).work_gallery, []);
});

test("who the person wants to meet is saved, but never searchable as who they are", () => {
  const out = finalizeCard(card(), { ...none, connect_with: ["Investors"], love_talking_about: ["Startups"] }, "", new Set());
  assert.deepEqual(out.connect_with, ["Investors"]);
  assert.ok(!out.searchable_facts.some((f) => /connect with/i.test(f)));
  assert.ok(out.searchable_facts.some((f) => /loves talking about Startups/.test(f)));
});
