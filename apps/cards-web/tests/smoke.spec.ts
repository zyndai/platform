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

/** S13: /find was folded into the directory; old links land on its ranked search, on a light canvas (no invisible dark-on-dark text). */
test("find redirects into the directory's ranked search", async ({ page }) => {
  await page.goto("/find?q=react+engineer&limit=25");

  await expect(page).toHaveURL(/\/directory\?/);
  const url = new URL(page.url());
  expect(url.searchParams.get("q")).toBe("react engineer");
  expect(url.searchParams.get("limit")).toBe("25");
  expect(url.searchParams.get("match")).toBe("1");
  await expect(page.locator("li.dc-result")).toHaveCount(2);
  await expect(page.getByLabel("Matches to show")).toHaveValue("25");

  const main = page.locator("main").first();
  const bg = await main.evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(bg).toBe("rgb(243, 241, 251)");

  await page.goto("/find");
  await expect(page).toHaveURL(/\/directory$/);
});

/** /directory: the name search narrows the grid, keeps the query in the URL, and Escape clears it. */
test("directory search filters people by name", async ({ page }) => {
  await page.goto("/directory");
  const people = page.locator("li.dc-person");
  await expect(people).toHaveCount(3);

  const search = page.getByRole("searchbox", { name: "Search people by name" });
  await search.fill("chen");
  await expect(people).toHaveCount(1);
  await expect(people.first()).toContainText("Alice Chen");
  await expect(page).toHaveURL(/q=chen/);

  await search.press("Escape");
  await expect(people).toHaveCount(3);
});

/** /directory: a refine chip ranks people by match instead of filtering names; All people goes back. */
test("directory chips rank people with scores and reasons", async ({ page }) => {
  await page.goto("/directory");

  const chip = page.getByRole("button", { name: "Remote" });
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await chip.click();
  await expect(page).toHaveURL(/q=remote&match=1/);

  const rows = page.locator("li.dc-result");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Alice Chen");
  await expect(rows.first().getByRole("img", { name: "92% match" })).toBeVisible();
  await expect(rows.first()).toContainText("Matches your search terms");
  await expect(page.getByText("Search dimensions")).toBeVisible();
  await expect(page.getByText("2 results for “remote”")).toBeVisible();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("searchbox", { name: "Search people by name" })).toHaveValue("remote");

  await page.getByRole("button", { name: "Verified" }).click();
  await expect(rows).toHaveCount(1);

  await page.getByRole("button", { name: "All people" }).click();
  await expect(page).toHaveURL(/\/directory$/);
  await expect(page.locator("li.dc-person")).toHaveCount(3);
});

/** /directory: Match ranks what is typed; a name that matches no one offers it, and a miss says so. */
test("directory Match ranks a typed query", async ({ page }) => {
  await page.goto("/directory");
  const search = page.getByRole("searchbox", { name: "Search people by name" });
  const match = page.getByRole("button", { name: /Search by skills, location or availability/ });

  await search.fill("react engineer");
  await expect(page.getByText("No one named “react engineer”")).toBeVisible();
  await match.click();
  await expect(page).toHaveURL(/q=react\+engineer&match=1/);
  await expect(page.locator("li.dc-result")).toHaveCount(2);

  await search.fill("nobody at all");
  await search.press("Enter");
  await expect(page.getByText("No one matches that search")).toBeVisible();

  await search.press("Escape");
  await expect(page).toHaveURL(/\/directory$/);
  await expect(page.locator("li.dc-person")).toHaveCount(3);
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
