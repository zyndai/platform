import { expect, test } from "@playwright/test";

/** S03: unclaimed cards are public to people but trimmed + quiet to agents. */
test("unclaimed profile shows claim banner and no chat", async ({ page }) => {
  await page.goto("/p/unclaimed");

  await expect(page.getByText("Is this you?")).toBeVisible();
  await expect(page.getByText("Claim with LinkedIn").first()).toBeVisible();
  await expect(page.getByText("This isn't", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("UNCLAIMED", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".pf-chat-fab")).toHaveCount(0);
});

test("claimed profile keeps the assistant", async ({ page }) => {
  await page.goto("/p/claimed");

  await expect(page.getByText("Is this you?")).toHaveCount(0);
  await expect(page.locator(".pf-chat-fab")).toHaveCount(1);
});

/** S13: /find renders with its own light canvas (no invisible dark-on-dark text). */
test("find page loads with a light canvas", async ({ page }) => {
  await page.goto("/find");

  const main = page.locator("main").first();
  await expect(main).toBeVisible();
  const bg = await main.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(247, 246, 242)");
});

/** S08: onboarding happy path — URL → auth nudge → continue → working → review. */
test("create flow reaches review with a mocked backend", async ({ page }) => {
  // First request through `next dev` compiles chunks on demand — generous timeout.
  test.setTimeout(120_000);
  await page.goto("/create");

  const input = page.getByPlaceholder("github.com/you  or  linkedin.com/in/you");
  await input.fill("github.com/alice");
  await input.press("Enter");

  await expect(page.getByText("github.com/alice", { exact: false }).first()).toBeVisible();

  const build = page.getByRole("button", { name: "Build my card" });
  await expect(build).toBeEnabled();
  await build.click();

  // S08 auth-before-build: the nudge appears before anything is scraped.
  await expect(page.getByText("Sign in before you build")).toBeVisible();
  await page.getByRole("button", { name: "Continue without signing in" }).click();

  // The mocked pipeline resolves to "ready" quickly — answer/skip the six
  // questions and the review phase lands with the scraped card.
  for (let i = 0; i < 6; i++) {
    await page.getByRole("button", { name: /Next|Done/ }).first().click();
  }
  await expect(page.getByRole("heading", { name: "Review your card" })).toBeVisible({ timeout: 45_000 });
});