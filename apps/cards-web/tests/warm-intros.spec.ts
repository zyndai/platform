import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";
import { mockNetwork } from "./fixtures/network";

test.beforeEach(async ({ context, request }) => {
  await request.post("http://127.0.0.1:3030/__s10/reset");
  await request.post("http://127.0.0.1:3030/__s10/warm-matches");
  await signIn(context);
});

test("reviews and edits a warm intro, preserves failed sends and waits for recipient consent", async ({ page }) => {
  let sends = 0;
  let failSend = true;
  let sentMessage = "";
  await page.route("**/cards/network/warm-intros/draft", route => route.fulfill({ json: {
    target_handle: "sarah", name: "Sarah", message: "Hi Sarah — could we connect about AI tools?",
    reasons: ["They are looking for go-to-market help; your profile lists growth advice.", '<img src=x onerror="window.introXss=1">'],
  } }));
  await page.route("**/cards/network/warm-intros", async route => {
    sends++;
    sentMessage = route.request().postDataJSON().message;
    if (failSend) return route.fulfill({ status: 503, json: { detail: "Could not send. Please try again." } });
    return route.fulfill({ json: { connection: { id: "warm-connection", status: "pending", incoming: false }, existing: false } });
  });
  await page.goto("/home#zynd-matches");
  await page.getByRole("button", { name: "Draft an intro to Sarah" }).click();
  const editor = page.getByRole("region", { name: "Intro draft for Sarah" });
  await expect(editor).toBeVisible();
  expect(sends).toBe(0);
  await expect(editor.locator("img")).toHaveCount(0);
  expect(await page.evaluate(() => "introXss" in window)).toBe(false);
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(sends).toBe(0);
  await page.getByRole("button", { name: "Draft an intro to Sarah" }).click();
  await editor.getByRole("textbox").fill("   ");
  await expect(editor.getByRole("button", { name: "Send intro request" })).toBeDisabled();
  await editor.getByRole("textbox").fill("Sarah, I can help with growth. Shall we connect?");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(editor).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await editor.screenshot({ path: "/tmp/zynd-warm-intro-mobile.png" });
  await editor.getByRole("button", { name: "Send intro request" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Could not send" })).toBeVisible();
  await expect(editor.getByRole("textbox")).toHaveValue("Sarah, I can help with growth. Shall we connect?");
  failSend = false;
  await editor.getByRole("button", { name: "Send intro request" }).click();
  await expect(page.getByText("Intro request sent. Your conversation opens when they accept.")).toBeVisible();
  expect(sends).toBe(2);
  expect(sentMessage).toBe("Sarah, I can help with growth. Shall we connect?");
  await expect(page.getByRole("link", { name: "View request →" })).toHaveAttribute("href", "/network?c=warm-connection");
  await expect(editor).toHaveCount(0);
});

test("shows a stale match error without sending an introduction", async ({ page }) => {
  await page.route("**/cards/network/warm-intros/draft", route => route.fulfill({ status: 409, json: { detail: "An introduction to this person is not available" } }));
  await page.goto("/home");
  await page.getByRole("button", { name: "Draft an intro to Sarah" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "An introduction to this person is not available" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send intro request" })).toHaveCount(0);
});

test("opens the editor immediately and shows API failures with a retry", async ({ page }) => {
  let respond: (() => void) | undefined;
  await page.route("**/cards/network/warm-intros/draft", async route => {
    await new Promise<void>(resolve => { respond = resolve; });
    await route.fulfill({ status: 403, json: { detail: "Use your shared Zynd account for Cards networking" } });
  });
  await page.goto("/home");
  await page.getByRole("button", { name: "Draft an intro to Sarah" }).click();
  const editor = page.getByRole("region", { name: "Intro draft for Sarah" });
  await expect(editor).toBeVisible();
  await expect(editor.getByRole("status")).toContainText("Nothing has been sent");
  await expect.poll(() => Boolean(respond)).toBe(true);
  respond!();
  await expect(editor.getByRole("alert")).toContainText("Use your shared Zynd account");
  await expect(editor.getByRole("button", { name: "Try drafting again" })).toBeVisible();
});

test("a stalled draft times out visibly instead of waiting forever", async ({ page }) => {
  await page.route("**/cards/network/warm-intros/draft", async () => { /* Hold the request open. */ });
  await page.goto("/home");
  await page.clock.install();
  await page.getByRole("button", { name: "Draft an intro to Sarah" }).click();
  const editor = page.getByRole("region", { name: "Intro draft for Sarah" });
  await expect(editor.getByRole("status")).toContainText("drafting an introduction");
  await page.clock.fastForward(30_001);
  await expect(editor.getByRole("alert")).toContainText("Drafting took too long");
  await expect(editor.getByRole("button", { name: "Try drafting again" })).toBeEnabled();
});

test("recipient reads the intro and accepts before the conversation opens", async ({ page }) => {
  const state = await mockNetwork(page);
  state.connections[0].request_message = "Sarah, I can help with growth. Shall we connect?";
  await page.goto("/network?v2=1");
  await expect(page.getByText("Sarah, I can help with growth. Shall we connect?")).toBeVisible();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Accept connection from Bob" }).click();
  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();
  expect(state.connections[0].status).toBe("accepted");
});
