import assert from "node:assert/strict";
import test from "node:test";

import {
  briefIsEmpty,
  connectionState,
  parseConnectionParam,
  sharedSummary,
  type ConnectionBrief,
  type ConnectionSummary,
} from "./cards-network.ts";
import { safeNextPath } from "./auth/next-cookie.ts";

const empty: ConnectionBrief = {
  partner: { handle: "ann", name: "Ann", headline: "" },
  now: { you: [], them: [] },
  shared: { skills: [], industries: [], interests: [], location: "" },
  suggested_topics: [],
};

test("a brief with nothing in it is empty, and so is no brief", () => {
  assert.equal(briefIsEmpty(empty), true);
  assert.equal(briefIsEmpty(null), true);
  assert.equal(briefIsEmpty(undefined), true);
});

test("any one section makes the brief worth showing", () => {
  assert.equal(briefIsEmpty({ ...empty, suggested_topics: ["Ask about: a fund"] }), false);
  assert.equal(briefIsEmpty({ ...empty, now: { you: [], them: [{ text: "Looking for investment" }] } }), false);
  assert.equal(briefIsEmpty({ ...empty, shared: { ...empty.shared, location: "Pune" } }), false);
});

test("the shared summary joins what is in common and where", () => {
  assert.equal(sharedSummary({ skills: ["Python"], industries: ["AI"], interests: [], location: "Pune, India" }), "Python, AI · Pune, India");
  assert.equal(sharedSummary({ skills: [], industries: [], interests: [], location: "Pune" }), "Pune");
  assert.equal(sharedSummary(empty.shared), "");
});

const link = (status: ConnectionSummary["status"], incoming = false): ConnectionSummary => ({ id: "c", status, incoming });

test("a connection reads as none, connected, requested, wants-to-connect or closed", () => {
  assert.equal(connectionState(null), "none");
  assert.equal(connectionState(undefined), "none");
  assert.equal(connectionState(link("accepted")), "connected");
  assert.equal(connectionState(link("accepted", true)), "connected");
  assert.equal(connectionState(link("pending")), "requested");
  assert.equal(connectionState(link("pending", true)), "wants-to-connect");
});

test("declined, revoked and blocked are closed: no new request can follow them", () => {
  for (const status of ["declined", "revoked", "blocked"] as const) {
    assert.equal(connectionState(link(status)), "closed");
    assert.equal(connectionState(link(status, true)), "closed");
  }
});

test("only a real connection id is accepted from the ?c= deep link", () => {
  const id = "3f2c9d1e-5a4b-4c3d-8e7f-1a2b3c4d5e6f";
  assert.equal(parseConnectionParam(id), id);
  assert.equal(parseConnectionParam(id.toUpperCase()), id);
  assert.equal(parseConnectionParam([id, "ignored"]), id);
  for (const bad of [undefined, null, "", "bob", `${id}x`, ` ${id}`, `${id}&next=//evil.example`, "../etc/passwd", [] as string[]]) {
    assert.equal(parseConnectionParam(bad), null, String(bad));
  }
});

test("the sign-in return path keeps the deep link's query and still rejects off-site targets", () => {
  const id = "3f2c9d1e-5a4b-4c3d-8e7f-1a2b3c4d5e6f";
  const next = `/network?c=${id}`;
  assert.equal(safeNextPath(next), next);
  // the redirect and the next-cookie both URL-encode it; the callback decodes it back
  assert.equal(safeNextPath(encodeURIComponent(next)), next);
  for (const bad of ["//evil.example/network", "https://evil.example", "/\\evil.example", encodeURIComponent("//evil.example"), "network?c=1"]) {
    assert.equal(safeNextPath(bad), null, bad);
  }
});
