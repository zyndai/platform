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
    await expect(visitors.getByText("Alice Chen", { exact: true })).toBeVisible();
    const revoke = page.waitForResponse(res => res.url().endsWith("/api/visitor-privacy") && res.request().method() === "PATCH");
    await page.getByRole("checkbox", { name: "Anonymous browsing" }).check();
    expect((await revoke).status()).toBe(200);
    await page.reload();
    await expect(visitors.getByText("Alice Chen", { exact: true })).toHaveCount(0);
    await expect(visitors.getByText("No visitors have chosen to share their name in the last 7 days.")).toBeVisible();
  });
});
