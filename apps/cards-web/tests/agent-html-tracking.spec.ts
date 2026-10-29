import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:3030/__s10/reset");
});

for (const agent of ["ChatGPT-User/1.0", "Claude-User/1.0", "PerplexityBot/1.0"]) {
  test(`records an HTML fetch without JavaScript from ${agent}`, async ({ request }) => {
    const response = await request.get("/p/owner", { headers: { "User-Agent": agent } });
    expect(response.ok()).toBe(true);
    expect(await response.text()).toContain("Alice Chen");
    await expect.poll(async () => (await request.get("http://127.0.0.1:3030/__s10/events")).json()).toEqual([
      { event: "agent_fetch", handle: "owner", meta: { endpoint: "profile-page" }, userAgent: agent },
    ]);
    const status = await (await request.get("http://127.0.0.1:3030/cards/mine/status")).json();
    expect(status.activity.views).toBe(12);
  });
}

// Browsers are counted by ProfileView's view beacon instead; scripts are not counted from the page.
for (const visitor of ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", "node"]) {
  test(`does not record an HTML fetch from ${visitor}`, async ({ request }) => {
    const response = await request.get("/p/owner", { headers: { "User-Agent": visitor } });
    expect(response.ok()).toBe(true);
    expect(await (await request.get("http://127.0.0.1:3030/__s10/events")).json()).toEqual([]);
  });
}

test("does not record missing profiles or prefetches", async ({ request }) => {
  await request.get("/p/does-not-exist", { headers: { "User-Agent": "ChatGPT-User/1.0" } });
  await request.get("/p/owner", { headers: { "User-Agent": "ChatGPT-User/1.0", purpose: "prefetch" } });
  expect(await (await request.get("http://127.0.0.1:3030/__s10/events")).json()).toEqual([]);
});
