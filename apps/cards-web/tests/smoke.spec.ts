import { expect, test } from "@playwright/test";

/** Force S08 v1 (quiz) or v2 (live preview) via sticky cookie. */
async function setS08(page: import("@playwright/test").Page, on: boolean) {
  await page.context().addCookies([{
    name: "zynd_s08",
    value: on ? "1" : "0",
    domain: "127.0.0.1",
    path: "/",
  }]);
}

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

/** S07: share sheet opens with tabs; copy + QR download affordances present. */
test("share sheet opens with tabs and QR actions", async ({ page }) => {
  await page.goto("/p/claimed");

  await page.getByRole("button", { name: "Share", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: /Alice Chen|Share/i });
  await expect(dialog).toBeVisible();

  await expect(page.getByRole("tab", { name: "Link" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "QR" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Card image" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Embed & email" })).toBeVisible();

  await page.getByRole("button", { name: "Copy", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Copied", exact: true }).first()).toBeVisible();

  await page.getByRole("tab", { name: "QR" }).click();
  await expect(page.getByText("Scan to view profile")).toBeVisible();
  await expect(page.getByRole("button", { name: "SVG" })).toBeVisible();
  await expect(page.getByRole("button", { name: "PNG" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Fullscreen" })).toBeVisible();
});

/** S13: /find renders with its own light canvas (no invisible dark-on-dark text). */
test("find page loads with a light canvas", async ({ page }) => {
  await page.goto("/find");

  const main = page.locator("main").first();
  await expect(main).toBeVisible();
  const bg = await main.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(247, 246, 242)");
});

/** S08 v1 escape: quiz path still works when cookie forces off. */
test("create flow v1 quiz reaches review", async ({ page }) => {
  test.setTimeout(120_000);
  await setS08(page, false);
  await page.goto("/create");

  const input = page.getByPlaceholder("github.com/you  or  linkedin.com/in/you");
  await input.fill("github.com/alice");
  await input.press("Enter");

  await expect(page.getByText("github.com/alice", { exact: false }).first()).toBeVisible();

  const build = page.getByRole("button", { name: "Build my card" });
  await expect(build).toBeEnabled();
  await build.click();

  await expect(page.getByText("Sign in before you build")).toBeVisible();
  await page.getByRole("button", { name: "Continue without signing in" }).click();

  for (let i = 0; i < 6; i++) {
    await page.getByRole("button", { name: /Next|Done/ }).first().click();
  }
  await expect(page.getByRole("heading", { name: "Review your card" })).toBeVisible({ timeout: 45_000 });
});

/** S08 v2: no quiz — live preview then review. */
test("create flow v2 shows live preview without quiz", async ({ page }) => {
  test.setTimeout(120_000);
  await setS08(page, true);
  await page.goto("/create");

  const input = page.getByPlaceholder("github.com/you  or  linkedin.com/in/you");
  await input.fill("github.com/bob");
  await input.press("Enter");

  await page.getByRole("button", { name: "Build my card" }).click();
  await expect(page.getByText("Sign in before you build")).toBeVisible();
  await page.getByRole("button", { name: "Continue without signing in" }).click();

  await expect(page.getByTestId("s08-live-preview")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("1 of 6")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Review your card" })).toBeVisible({ timeout: 45_000 });
});

/** S08 claim-first: LinkedIn lookalike surfaces before build. */
test("create flow offers claim candidate for matching LinkedIn", async ({ page }) => {
  test.setTimeout(60_000);
  await setS08(page, true);
  await page.goto("/create");

  const input = page.getByPlaceholder("github.com/you  or  linkedin.com/in/you");
  await input.fill("linkedin.com/in/alice-chen");
  await input.press("Enter");

  await expect(page.getByText("We found a card that looks like yours")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: /Is this you/i })).toBeVisible();
});

/** S08 first-win: welcome shows seeded Ask demo + chat FAB. */
test("welcome first-win shows demo answer and ask CTA", async ({ page }) => {
  await page.goto("/p/claimed/welcome");

  await expect(page.getByText(/you're live/i)).toBeVisible();
  await expect(page.getByTestId("first-win-demo")).toBeVisible();
  await expect(page.getByText("Ask your card — live demo")).toBeVisible();
  await expect(page.getByRole("button", { name: /Ask about/i })).toBeVisible();
  await expect(page.getByText("Say what you're looking for")).toBeVisible();
  await expect(page.getByText("Share it")).toBeVisible();
  await expect(page.getByText("Connect your AI")).toBeVisible();

  await page.getByRole("button", { name: /Ask about/i }).click();
  await expect(page.locator(".pf-chat-panel")).toBeVisible();
});

/** S08 mobile: create at 390px has no horizontal overflow. */
test("create at 390px has no horizontal scroll", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await setS08(page, true);
  await page.goto("/create");

  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  expect(overflow).toBe(false);
});

test("welcome at 390px has no horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/p/claimed/welcome");

  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  expect(overflow).toBe(false);
});
