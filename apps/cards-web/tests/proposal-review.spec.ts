import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

test("signed-out review preserves the login return path", async ({ page }) => {
  await page.goto("/review/proposal-1");
  await expect(page.getByRole("link", { name: "Sign in to review" })).toHaveAttribute("href", "/auth?next=%2Freview%2Fproposal-1");
});

for (const action of ["publish_card_fact", "save_memory"] as const) {
  test(`${action} requires preview before exact confirmation`, async ({ page, context }) => {
    await signIn(context);
    await page.setViewportSize({ width: 390, height: 844 });
    const decisions: object[] = [];
    const expires_at = new Date(Date.now() + 60_000).toISOString();
    await page.route("**/me/plugin/proposals/proposal-1**", async (route) => {
      expect(route.request().headers().authorization).toMatch(/^Bearer /);
      const url = route.request().url();
      if (url.endsWith("/decision")) {
        decisions.push(route.request().postDataJSON());
        await route.fulfill({ json: { status: action === "save_memory" ? "saved_privately" : "sync_pending" } });
      } else {
        await route.fulfill({ json: {
          id: "proposal-1", action, text: "Private source text", public_text: "Builds robots",
          status: "pending_review", expires_at, version: 1,
          ...(url.endsWith("/preview") ? { nonce: "server-bound-nonce" } : {}),
        } });
      }
    });
    await page.goto("/review/proposal-1");
    await page.getByRole("button", { name: action === "save_memory" ? "Review private save" : "Step 1: Preview publication" }).click();
    expect(decisions).toEqual([]);
    const confirmation = page.getByRole("button", { name: action === "save_memory" ? "Save to private memory" : "Publish this exact text" });
    await expect(confirmation).toBeVisible();
    await expect(page.getByText(action === "save_memory" ? "This exact text will be saved privately:" : "This exact text will be public:")).toBeVisible();
    await confirmation.click();
    await expect(page.getByRole("heading", { name: action === "save_memory" ? "Saved to private memory" : "Publication approved" })).toBeVisible();
    expect(decisions).toEqual([{ nonce: "server-bound-nonce", decision: "approve" }]);
    if (action === "publish_card_fact") await expect(page.getByText("Your exact text was approved. Your public card update is pending.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

test("reject obtains a nonce without approving", async ({ page, context }) => {
  await signIn(context);
  const decisions: object[] = [];
  await page.route("**/me/plugin/proposals/proposal-1**", async (route) => {
    if (route.request().url().endsWith("/decision")) {
      decisions.push(route.request().postDataJSON());
      await route.fulfill({ json: { status: "rejected" } });
    } else await route.fulfill({ json: {
      id: "proposal-1", action: "save_memory", text: "Do not save this",
      status: "pending_review", expires_at: new Date(Date.now() + 60_000).toISOString(), version: 1,
      nonce: "reject-nonce",
    } });
  });
  await page.goto("/review/proposal-1");
  await page.getByRole("button", { name: "Reject proposal" }).click();
  await expect(page.getByRole("heading", { name: "Proposal rejected" })).toBeVisible();
  expect(decisions).toEqual([{ nonce: "reject-nonce", decision: "reject" }]);
});

test("expired proposals cannot be approved", async ({ page, context }) => {
  await signIn(context);
  await page.route("**/me/plugin/proposals/proposal-1", route => route.fulfill({ json: {
    id: "proposal-1", action: "save_memory", text: "Expired text", status: "pending_review",
    expires_at: new Date(Date.now() - 1000).toISOString(), version: 1,
  } }));
  await page.goto("/review/proposal-1");
  await expect(page.getByText("This proposal has expired. Ask ChatGPT for a new proposal.")).toBeVisible();
  await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
});

for (const status of [401, 403, 409]) {
  test(`failed proposal request (${status}) exposes no approval controls`, async ({ page, context }) => {
    await signIn(context);
    await page.route("**/me/plugin/proposals/proposal-1", route => route.fulfill({ status, json: {} }));
    await page.goto("/review/proposal-1");
    if (status === 401) await expect(page.getByRole("link", { name: "Sign in to review" })).toBeVisible();
    else await expect(page.getByRole("main").getByRole("alert")).toContainText(status === 403 ? "another account" : "already decided");
    await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
  });
}
