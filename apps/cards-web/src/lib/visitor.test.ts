import assert from "node:assert/strict";
import test from "node:test";

import { forwardedClientIp, isAiAgent, visitorFrom } from "./visitor.ts";

test("AI agents are told apart from browsers, search bots and scripts", () => {
  for (const ua of [
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)",
    "Mozilla/5.0 (compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)",
    "Mozilla/5.0 (compatible; gptbot/1.2)",
  ]) {
    assert.equal(isAiAgent(ua), true, ua);
  }
  for (const ua of [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "curl/8.7.1", "", null, undefined,
  ]) {
    assert.equal(isAiAgent(ua), false, String(ua));
  }
});

test("the client IP is the last X-Forwarded-For entry, the one Caddy wrote", () => {
  assert.equal(forwardedClientIp("203.0.113.5"), "203.0.113.5");
  assert.equal(forwardedClientIp("160.79.104.10, 203.0.113.5"), "203.0.113.5");
  assert.equal(forwardedClientIp(" 2001:db8::1 ,"), "2001:db8::1");
  assert.equal(forwardedClientIp(""), null);
  assert.equal(forwardedClientIp(null), null);
});

test("visitorFrom reads both headers", () => {
  const headers = new Headers({ "user-agent": "Claude-User/1.0", "x-forwarded-for": "203.0.113.5" });
  assert.deepEqual(visitorFrom(headers), { userAgent: "Claude-User/1.0", ip: "203.0.113.5" });
  assert.deepEqual(visitorFrom(new Headers()), { userAgent: null, ip: null });
});
