import assert from "node:assert/strict";
import test from "node:test";

import {
  actionFor,
  firstName,
  parseFilter,
  relativeTime,
  replyFor,
  safeHref,
  type FeedConnection,
  type FeedItem,
} from "./feed.ts";

const author = { handle: "ana", name: "Ana Rao", headline: "", avatar_url: null, location: "", claimed: true };
const base = { id: "x", at: "2026-10-28T12:00:00Z", earlier: false, reason: "", author, connection: null };

test("the first name is the first word, with a fallback", () => {
  assert.equal(firstName("  Ana  Rao "), "Ana");
  assert.equal(firstName(""), "there");
});

test("each kind gets its own action label and a message that starts the conversation", () => {
  const items: [FeedItem, string, string][] = [
    [{ ...base, kind: "ask", content: { text: "a React dev" } }, "I can help", 'Hi Ana, I can help with "a React dev": '],
    [{ ...base, kind: "working_on", content: { text: "voice agents" } }, "Me too", 'Hi Ana, "voice agents" caught my eye, I\'m into this too. '],
    [{ ...base, kind: "joined", content: { headline: "", can_help_with: [] } }, "Welcome", "Hi Ana, welcome to Zynd! "],
    [{ ...base, kind: "github", content: { type: "release", repo: "ana/lib", title: "v1.2", url: "" } }, "Congratulate", "Hi Ana, congrats on the v1.2 release! "],
    [{ ...base, kind: "github", content: { type: "pull_request", repo: "o/p", title: "Fix parser", url: "" } }, "Congratulate", 'Hi Ana, congrats on getting "Fix parser" merged into o/p! '],
    [{ ...base, kind: "github", content: { type: "repo", repo: "ana/new", title: "", url: "" } }, "Say hi", "Hi Ana, saw your new repo ana/new. "],
    [{ ...base, kind: "exploring", content: { title: "A paper", url: "", note: "", kind: "paper" } }, "Say hi", 'Hi Ana, saw you\'re exploring "A paper". '],
    [{ ...base, kind: "post", content: { platform: "linkedin", preview: "", url: "" } }, "Say hi", "Hi Ana, enjoyed your post on LinkedIn. "],
  ];
  for (const [item, label, prefill] of items) {
    const reply = replyFor(item);
    assert.equal(reply.label, label);
    assert.equal(reply.prefill, prefill);
  }
});

test("a prefilled message never exceeds the length the API accepts", () => {
  const long = "x".repeat(5000);
  assert.ok(replyFor({ ...base, kind: "ask", content: { text: long } }).prefill.length <= 2000);
});

test("the action depends on whether the viewer has a card and how they stand with the author", () => {
  const conn = (status: FeedConnection["status"], incoming = false): FeedConnection => ({ id: "c1", status, incoming });
  assert.deepEqual(actionFor(false, null), { kind: "create-card" });
  assert.deepEqual(actionFor(false, conn("accepted")), { kind: "create-card" });
  assert.deepEqual(actionFor(true, null), { kind: "reply", via: "request" });
  assert.deepEqual(actionFor(true, conn("accepted")), { kind: "reply", via: "dm", connectionId: "c1" });
  assert.deepEqual(actionFor(true, conn("pending")), { kind: "requested" });
  assert.deepEqual(actionFor(true, conn("pending", true)), { kind: "respond", connectionId: "c1" });
});

test("relative time reads naturally and tolerates junk", () => {
  const now = Date.parse("2026-10-28T12:00:00Z");
  assert.equal(relativeTime("2026-10-28T11:59:40Z", now), "just now");
  assert.equal(relativeTime("2026-10-28T11:15:00Z", now), "45m ago");
  assert.equal(relativeTime("2026-10-28T07:00:00Z", now), "5h ago");
  assert.equal(relativeTime("2026-10-25T12:00:00Z", now), "3d ago");
  assert.equal(relativeTime("2026-10-07T12:00:00Z", now), "3w ago");
  assert.equal(relativeTime("nonsense", now), "");
});

test("the filter param falls back to all and only http links are followed", () => {
  assert.equal(parseFilter("asks"), "asks");
  assert.equal(parseFilter(["network", "asks"]), "network");
  assert.equal(parseFilter("bogus"), "all");
  assert.equal(parseFilter(undefined), "all");
  assert.equal(safeHref("https://example.com/a"), "https://example.com/a");
  assert.equal(safeHref("javascript:alert(1)"), "");
});
