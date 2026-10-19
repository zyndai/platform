import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

test.describe("Profile views and visitor consent", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ request }) => { await request.post("http://127.0.0.1:3030/__s10/reset"); });

  test("anonymous browser view reaches the human counter through the same-origin proxy", async ({ page, request }) => {
    const event = page.waitForResponse(res => res.url().endsWith("/api/events") && res.request().method() === "POST");
    await page.goto("/p/owner");
    expect((await event).status()).toBe(204);
    await expect.poll(async () => (await (await request.get("http://127.0.0.1:3030/cards/mine/status")).json()).activity.views).toBe(13);
    await expect(page.getByRole("checkbox", { name: "Anonymous browsing" })).toHaveCount(0);
  });

  test("opt-in reveals the name; re-enabling anonymous mode hides old visits", async ({ page, context }) => {
    await signIn(context);
    await page.goto("/home");
    expect((await page.request.patch("http://127.0.0.1:3010/api/visitor-privacy", {
      headers: { Origin: "https://foreign.example" }, data: { anonymous_mode: false },
    })).status()).toBe(403);
    const setting = page.getByRole("checkbox", { name: "Anonymous browsing" });
    await expect(setting).toBeEnabled();
    await expect(setting).toBeChecked();
    const save = page.waitForResponse(res => res.url().endsWith("/api/visitor-privacy") && res.request().method() === "PATCH");
    await setting.uncheck();
    expect((await save).status()).toBe(200);
    const visit = page.waitForResponse(res => res.url().endsWith("/api/profile-visit") && res.request().method() === "POST");
    await page.goto("/p/claimed");
    expect((await visit).status()).toBe(200);
    await expect(page.getByRole("checkbox", { name: "Anonymous browsing" })).toHaveCount(0);
    await expect.poll(async () => (await (await page.request.get("http://127.0.0.1:3030/cards/mine/status")).json()).visitors.items.length).toBe(1);
    await page.goto("/home");
    const visitors = page.getByRole("region", { name: "People who visited" });
    await expect(visitors.getByRole("link", { name: "Alice Chen", exact: true })).toHaveAttribute("href", "/p/owner");
    await expect(visitors.getByText("@owner", { exact: false })).toBeVisible();
    await visitors.screenshot({ path: "/tmp/zynd-home-visitors-desktop.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    await visitors.screenshot({ path: "/tmp/zynd-home-visitors-mobile.png" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const revoke = page.waitForResponse(res => res.url().endsWith("/api/visitor-privacy") && res.request().method() === "PATCH");
    await page.getByRole("checkbox", { name: "Anonymous browsing" }).check();
    expect((await revoke).status()).toBe(200);
    await page.reload();
    await expect(visitors.getByText("Alice Chen", { exact: true })).toHaveCount(0);
    await expect(visitors.getByText("No visitors have chosen to share their name in the last 7 days.")).toBeVisible();
  });

  test("retries a temporary failure with the same visit ID", async ({ page, context, request }) => {
    await signIn(context);
    await request.patch("http://127.0.0.1:3030/cards/mine/visitor-privacy", { data: { anonymous_mode: false } });
    const ids: string[] = [];
    await page.route("**/api/profile-visit", route => {
      ids.push(route.request().postDataJSON().visit_id);
      return ids.length === 1
        ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Temporary outage" }) })
        : route.continue();
    });
    await page.goto("/p/claimed");
    await expect.poll(async () => (await (await request.get("http://127.0.0.1:3030/cards/mine/status")).json()).visitors.items[0]?.visits).toBe(1);
    expect(ids.length).toBeGreaterThanOrEqual(2);
    expect(new Set(ids).size).toBe(1);
  });

  test("records a visitor who signs in while the profile is open without another view", async ({ page, context, request }) => {
    await request.patch("http://127.0.0.1:3030/cards/mine/visitor-privacy", { data: { anonymous_mode: false } });
    let views = 0;
    page.on("request", req => {
      if (req.url().endsWith("/api/events") && req.method() === "POST") {
        // Chromium does not expose sendBeacon's Blob body through postDataJSON.
        views++;
      }
    });
    await page.goto("/p/claimed");
    await expect.poll(() => views).toBe(1);
    const session = await signIn(context);
    // Supabase notifies already-open tabs through this browser channel.
    await page.evaluate(session => {
      const channel = new BroadcastChannel("sb-127-auth-token");
      channel.postMessage({ event: "SIGNED_IN", session });
      channel.close();
    }, session);
    await expect.poll(async () => (await (await request.get("http://127.0.0.1:3030/cards/mine/status")).json()).visitors.items[0]?.visits).toBe(1);
    expect(views).toBe(1);
  });

  test("picks up sharing enabled in another tab without counting focus twice", async ({ page, context, request }) => {
    await signIn(context);
    const initialVisit = page.waitForResponse(res => res.url().endsWith("/api/profile-visit"));
    await page.goto("/p/claimed");
    expect(await (await initialVisit).json()).toEqual({ recorded: false });
    await request.patch("http://127.0.0.1:3030/cards/mine/visitor-privacy", { data: { anonymous_mode: false } });
    const recorded = page.waitForResponse(res => res.url().endsWith("/api/profile-visit"));
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    expect(await (await recorded).json()).toEqual({ recorded: true });
    const repeated = page.waitForResponse(res => res.url().endsWith("/api/profile-visit"));
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    expect(await (await repeated).json()).toEqual({ recorded: false });
    expect((await (await request.get("http://127.0.0.1:3030/cards/mine/status")).json()).visitors.items[0].visits).toBe(1);
  });
});
