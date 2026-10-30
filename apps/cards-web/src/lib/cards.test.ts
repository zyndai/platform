import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { cardCanonicalUrl, profileUrl, profileUrlDisplay, type AgentProfileCard } from "./cards";

const ORIGINAL_SITE_URL = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  if (ORIGINAL_SITE_URL === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = ORIGINAL_SITE_URL;
});

test("a profile lives at cards.zynd.ai/p/<handle> when no site URL is configured", () => {
  delete process.env.NEXT_PUBLIC_SITE_URL;
  assert.equal(profileUrl("ada"), "https://cards.zynd.ai/p/ada");
  assert.equal(profileUrlDisplay("ada"), "cards.zynd.ai/p/ada");
});

test("the configured site origin wins, with any trailing slash dropped", () => {
  process.env.NEXT_PUBLIC_SITE_URL = "http://localhost:3002/";
  assert.equal(profileUrl("ada"), "http://localhost:3002/p/ada");
  assert.equal(profileUrlDisplay("ada"), "localhost:3002/p/ada");
});

test("a handle cannot break out of its path segment", () => {
  delete process.env.NEXT_PUBLIC_SITE_URL;
  assert.equal(profileUrl('ada/../x?"'), "https://cards.zynd.ai/p/ada%2F..%2Fx%3F%22");
});

test("the canonical card URL is the profile URL, or /profile/<id> before a handle exists", () => {
  delete process.env.NEXT_PUBLIC_SITE_URL;
  const card = { id: "c1", handle: "ada" } as AgentProfileCard;
  assert.equal(cardCanonicalUrl(card), "https://cards.zynd.ai/p/ada");
  assert.equal(cardCanonicalUrl({ ...card, handle: "" }), "https://cards.zynd.ai/profile/c1");
});
