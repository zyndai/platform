import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activityLabel,
  applyAgentStream,
  clearUserStreams,
  dropFinishedStreams,
  parseAgentStream,
  pruneStaleStreams,
  STREAM_STALE_MS,
  visibleStreams,
  type AgentStreamSnapshot,
  type AgentStreams,
} from "./agent-stream.ts";

const JOB = "30000000-0000-4000-8000-000000000030";
const OTHER_JOB = "30000000-0000-4000-8000-000000000031";
const BOB = "22222222-2222-4222-8222-222222222222";
const ALICE = "11111111-1111-4111-8111-111111111111";

function snapshot(overrides: Partial<AgentStreamSnapshot> = {}): AgentStreamSnapshot {
  return {
    jobId: JOB, userId: BOB, messageId: "m1", attempt: 1, seq: 1,
    text: "", done: false, status: "writing", ...overrides,
  };
}

test("a server payload becomes a snapshot, and junk is rejected", () => {
  const parsed = parseAgentStream({
    job_id: JOB, group_id: "g", user_id: BOB, message_id: "m1", attempt: 2, seq: 7,
    text: "Hello", done: false, status: "writing",
    sources: { tools: [{ name: "get_group_members" }] },
  });
  assert.deepEqual(parsed, {
    jobId: JOB, userId: BOB, messageId: "m1", attempt: 2, seq: 7,
    text: "Hello", done: false, status: "writing",
    sources: { tools: [{ name: "get_group_members" }] },
  });
  assert.equal(parseAgentStream({ user_id: BOB, text: "no job" }), null);
  assert.equal(parseAgentStream({ job_id: JOB, text: "no user" }), null);
  // Unknown status falls back sensibly; a missing text is empty, not a crash.
  assert.equal(parseAgentStream({ job_id: JOB, user_id: BOB, status: "mystery" })?.status, "writing");
  assert.equal(parseAgentStream({ job_id: JOB, user_id: BOB, done: true })?.status, "done");
  assert.equal(parseAgentStream({ job_id: JOB, user_id: BOB })?.text, "");
  // Sources must be an object.
  assert.equal(parseAgentStream({ job_id: JOB, user_id: BOB, sources: "nope" })?.sources, undefined);
  assert.equal(parseAgentStream({ job_id: JOB, user_id: BOB, sources: [1] })?.sources, undefined);
});

test("full-text snapshots replace the text, so the latest one wins", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ seq: 1, text: "Hel" }), 10);
  streams = applyAgentStream(streams, snapshot({ seq: 2, text: "Hello there" }), 20);
  assert.equal(streams[JOB].text, "Hello there");
  assert.equal(streams[JOB].updatedAt, 20);
});

test("a late or repeated snapshot never rewinds the text", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ seq: 3, text: "Hello there, team" }), 10);
  const same = applyAgentStream(streams, snapshot({ seq: 3, text: "Hello there, team" }), 11);
  assert.equal(same, streams, "a duplicate leaves the state untouched");
  const late = applyAgentStream(streams, snapshot({ seq: 2, text: "Hello there" }), 12);
  assert.equal(late, streams);
  assert.equal(late[JOB].text, "Hello there, team");
});

test("the done snapshot is final within its attempt", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ seq: 4, text: "Final answer.", done: true, status: "done" }), 10);
  // A slow earlier "writing" snapshot arriving afterwards must not undo it.
  streams = applyAgentStream(streams, snapshot({ seq: 3, text: "Final ans" }), 20);
  assert.equal(streams[JOB].text, "Final answer.");
  assert.equal(streams[JOB].done, true);
});

test("a retried job starts over: a new attempt replaces the text even with a lower seq", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ attempt: 1, seq: 9, text: "Half an answ" }), 10);
  streams = applyAgentStream(streams, snapshot({ attempt: 2, seq: 1, text: "", status: "thinking" }), 20);
  assert.equal(streams[JOB].text, "");
  assert.equal(streams[JOB].status, "thinking");
  streams = applyAgentStream(streams, snapshot({ attempt: 2, seq: 2, text: "A fresh start" }), 30);
  assert.equal(streams[JOB].text, "A fresh start");
  // The failed first attempt cannot come back.
  streams = applyAgentStream(streams, snapshot({ attempt: 1, seq: 10, text: "Half an answer" }), 40);
  assert.equal(streams[JOB].text, "A fresh start");
});

test("a snapshot without a seq (an older server) is always applied", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ attempt: 0, seq: 0, text: "one" }), 10);
  streams = applyAgentStream(streams, snapshot({ attempt: 0, seq: 0, text: "one two" }), 20);
  assert.equal(streams[JOB].text, "one two");
});

test("sources accumulate within an attempt and reset on a new one", () => {
  const sources = { tools: [{ name: "search_group_memory", ok: true, summary: "2 results" }] };
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ seq: 1, status: "tool", sources }), 10);
  streams = applyAgentStream(streams, snapshot({ seq: 2, text: "Friday." }), 20);
  assert.deepEqual(streams[JOB].sources, sources, "text snapshots carry no sources and keep the known ones");
  const fuller = { ...sources, context: { recent_messages: 12 } };
  streams = applyAgentStream(streams, snapshot({ seq: 3, text: "Friday.", done: true, status: "done", sources: fuller }), 30);
  assert.deepEqual(streams[JOB].sources, fuller);
  streams = applyAgentStream(streams, snapshot({ attempt: 2, seq: 1, status: "thinking" }), 40);
  assert.equal(streams[JOB].sources, undefined, "a retry does not inherit the failed attempt's trace");
});

test("only streams with text, and without their final message, are drawn", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ jobId: JOB, text: "Writing" }), 20);
  streams = applyAgentStream(streams, snapshot({ jobId: OTHER_JOB, userId: ALICE, status: "thinking", text: "" }), 10);
  assert.deepEqual(visibleStreams(streams, []).map((stream) => stream.jobId), [JOB]);
  streams = applyAgentStream(streams, snapshot({ jobId: OTHER_JOB, userId: ALICE, seq: 2, text: "Second" }), 30);
  assert.deepEqual(visibleStreams(streams, []).map((stream) => stream.jobId), [JOB, OTHER_JOB]);
  // Whitespace alone is not a bubble.
  streams = applyAgentStream(streams, snapshot({ jobId: OTHER_JOB, userId: ALICE, seq: 3, text: " \n " }), 40);
  assert.deepEqual(visibleStreams(streams, []).map((stream) => stream.jobId), [JOB]);
});

test("the stream bubble goes as soon as the final message is in the conversation, in either order", () => {
  const final = { client_id: JOB };
  let streams: AgentStreams = {};
  // Snapshot first, then the message (the usual order).
  streams = applyAgentStream(streams, snapshot({ seq: 5, text: "Done.", done: true, status: "done" }), 10);
  assert.equal(visibleStreams(streams, []).length, 1);
  assert.equal(visibleStreams(streams, [final]).length, 0);
  assert.deepEqual(dropFinishedStreams(streams, [final]), {});
  // Message first, then a late snapshot: it never shows, even before any pruning.
  const late = applyAgentStream({}, snapshot({ seq: 6, text: "Done." }), 20);
  assert.equal(visibleStreams(late, [final]).length, 0);
  // Messages with no client id, or another job's, do not match.
  assert.equal(visibleStreams(streams, [{ client_id: null }, {}, { client_id: OTHER_JOB }]).length, 1);
  assert.equal(dropFinishedStreams(streams, [{ client_id: OTHER_JOB }]), streams);
});

test("a retry or a failure clears that user's streams only", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ jobId: JOB, userId: BOB, text: "Bob's draft" }), 10);
  streams = applyAgentStream(streams, snapshot({ jobId: OTHER_JOB, userId: ALICE, text: "Alice's draft" }), 10);
  const cleared = clearUserStreams(streams, BOB);
  assert.deepEqual(Object.keys(cleared), [OTHER_JOB]);
  assert.equal(clearUserStreams(cleared, BOB), cleared, "nothing to clear leaves the state as is");
});

test("a stream that stops updating is forgotten", () => {
  let streams: AgentStreams = {};
  streams = applyAgentStream(streams, snapshot({ jobId: JOB, text: "Stuck" }), 1_000);
  streams = applyAgentStream(streams, snapshot({ jobId: OTHER_JOB, userId: ALICE, text: "Fresh" }), 1_000 + STREAM_STALE_MS);
  const pruned = pruneStaleStreams(streams, 1_000 + STREAM_STALE_MS + 1);
  assert.deepEqual(Object.keys(pruned), [OTHER_JOB]);
  assert.equal(pruneStaleStreams(pruned, 1_000 + STREAM_STALE_MS + 2), pruned);
});

test("the tool step names what is running only when the server sent sources", () => {
  const withSources = applyAgentStream({}, snapshot({
    seq: 1, status: "tool",
    sources: { tools: [
      { name: "get_group_members", ok: true, summary: "2 members" },
      { name: "search_group_memory", running: true },
    ] },
  }), 10)[JOB];
  assert.equal(activityLabel(withSources), "Searching group memory…");
  const bare = applyAgentStream({}, snapshot({ seq: 1, status: "tool" }), 10)[JOB];
  assert.equal(activityLabel(bare), "Looking things up…");
  const unknown = applyAgentStream({}, snapshot({ seq: 1, status: "tool", sources: { tools: [{ name: "x", running: true }] } }), 10)[JOB];
  assert.equal(activityLabel(unknown), "Looking things up…");
  assert.equal(activityLabel(applyAgentStream({}, snapshot({ status: "writing", text: "hi" }), 10)[JOB]), null);
  assert.equal(activityLabel(undefined), null);
});
