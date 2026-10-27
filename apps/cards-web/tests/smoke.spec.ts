import { expect, test } from "@playwright/test";
import { LINK_PLACEHOLDER } from "./fixtures/create";

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

/** Create is two steps on one page: paste a link, then review the card as it fills in. No Build button, no quiz. */
test("create builds the card on one page, suggests the answers, and publishes them", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/create");

  // #given pasting a link is the whole first step
  await expect(page.getByRole("button", { name: "Build my card" })).toHaveCount(0);
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.fill("github.com/bob");
  await input.press("Enter");

  // #then the source reports what was read, and the card fills in beside it
  const row = page.locator(".cr-source", { hasText: "github.com/bob" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Bob Okafor")).toBeVisible({ timeout: 15_000 });
  const editor = page.getByTestId("card-editor");
  await expect(editor.getByText("Bob Okafor")).toBeVisible();

  // #and the draft arrives editable in place, with the AI's answers already chosen: one from the list, one of its own
  const name = editor.getByLabel("Name", { exact: true });
  await expect(name).toHaveValue("Alice Chen", { timeout: 20_000 });
  await expect(editor.getByRole("button", { name: "Remove Code review" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Remove Agent tooling" })).toBeVisible();

  // #when they rename themselves on the card, drop a suggestion, and publish
  await name.fill("Alice C. Chen");
  await editor.getByRole("button", { name: "Remove Code review" }).click();
  await expect(editor.getByRole("button", { name: "Add Code review" })).toBeVisible();
  const publish = page.getByRole("button", { name: /Publish my card/ });
  await expect(publish).toBeEnabled();
  const publishRequest = page.waitForRequest((r) => r.url().endsWith("/onboard/job1/publish"));
  await publish.click();

  // #then what they changed is what is published
  const body = (await publishRequest).postDataJSON();
  expect(body.card.identity.name).toBe("Alice C. Chen");
  expect(body.card.can_help_with).toEqual([]);
  expect(body.card.working_on).toEqual(["Agent tooling"]);
  await expect(page.getByText("You're live")).toBeVisible();
});

/** The public card shows the proof a person has: a designer's project grid and newsletter, and no GitHub block. */
test("a designer's profile shows their work grid and newsletter instead of a code graph", async ({ page }) => {
  await page.goto("/p/designer");

  const work = page.locator(".pf-gallery");
  await expect(work).toBeVisible();
  await expect(work).toContainText("BEHANCE · 2 PROJECTS");
  await expect(work.getByRole("link", { name: /Brand system for Orbit/ })).toHaveAttribute("href", "https://www.behance.net/gallery/1/Orbit");
  await expect(work.locator("img")).toHaveCount(2);

  const writing = page.locator(".pf-posts");
  await expect(writing).toContainText("RECENT WRITING");
  await expect(writing).toContainText("Substack");
  await expect(writing).toContainText("How I hire designers who ship");

  await expect(page.getByText("CONTRIBUTION ACTIVITY")).toHaveCount(0);
});

/** A designer is not offered engineering jargon: the options follow the persona, and the proof follows the links. */
test("create tailors the options and the proof to who the person is", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/create");

  // #given a design portfolio, a link a developer-first form would ignore
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.fill("behance.net/ada");
  await input.press("Enter");
  const row = page.locator(".cr-source", { hasText: "behance.net/ada" });
  await expect(row.getByText("2 projects")).toBeVisible({ timeout: 15_000 });

  // #then the draft is a designer's: their persona, their vocabulary, their work
  const editor = page.getByTestId("card-editor");
  await expect(editor.getByLabel("Name", { exact: true })).toHaveValue("Alice Chen", { timeout: 20_000 });
  const persona = editor.getByLabel("Options tailored for");
  await expect(persona).toHaveValue("product_design");
  await expect(editor.getByRole("button", { name: "Remove Brand identity" })).toBeVisible();
  await expect(editor.getByRole("group", { name: "Can help with" }).getByRole("button", { name: "Remove Design systems" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Add Code review" })).toHaveCount(0);
  await expect(editor.getByRole("region", { name: "Work" }).getByRole("listitem")).toHaveCount(2);
  await expect(editor.getByRole("region", { name: "Recent writing" })).toContainText("Substack");

  // #when they say they are in marketing instead, the options change and their answers stay
  await persona.selectOption("marketing_sales");
  await expect(editor.getByRole("button", { name: "Add Content marketing" })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Remove Brand identity" })).toBeVisible();

  // #and dropping one project cover leaves it out of what is published
  await editor.getByRole("button", { name: "Remove Poster series" }).click();
  const publishRequest = page.waitForRequest((r) => r.url().endsWith("/onboard/job1/publish"));
  await page.getByRole("button", { name: /Publish my card/ }).click();
  const body = (await publishRequest).postDataJSON();
  expect(body.card.work_gallery.map((w: { title: string }) => w.title)).toEqual(["Brand system for Orbit"]);
  expect(body.card.writing_samples[0].platform).toBe("substack");
});

/** While the person edits the working-on line, the writing rule is on screen. */
test("create coaches the working-on line while it is being edited", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/create");
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.fill("github.com/bob");
  await input.press("Enter");
  const editor = page.getByTestId("card-editor");
  await expect(editor.getByLabel("Name", { exact: true })).toHaveValue("Alice Chen", { timeout: 20_000 });

  const tip = editor.getByText("Write for the person who will meet you next, not your whole career history.");
  await expect(tip).toBeHidden();
  await editor.getByLabel("Add your own: Working on").focus();
  await expect(tip).toBeVisible();
});

/** Pasting is the whole first step: a link pasted into the empty box is added without Enter. */
test("create adds a pasted link straight away and starts reading it", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/create");
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.evaluate((el) => {
    const data = new DataTransfer();
    data.setData("text", "https://github.com/bob");
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
  });
  const row = page.locator(".cr-source", { hasText: "github.com/bob" });
  await expect(row).toBeVisible();
  await expect(row.getByText("Bob Okafor")).toBeVisible({ timeout: 15_000 });
});

/** S08 claim-first: LinkedIn lookalike surfaces before build. */
test("create flow offers claim candidate for matching LinkedIn", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/create");

  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
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

/** S08 mobile: create at 390px has no horizontal overflow, empty or with a source read. */
test("create at 390px has no horizontal scroll", async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/create");

  const overflow = () => page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  expect(await overflow()).toBe(false);

  // #when a source has been read, its row and the search bar must still sit inside their card
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.fill("github.com/bob");
  await input.press("Enter");
  const row = page.locator(".cr-source", { hasText: "github.com/bob" });
  await expect(row.getByText("Bob Okafor")).toBeVisible({ timeout: 15_000 });
  expect(await overflow()).toBe(false);
  const inside = await page.evaluate(() => {
    const card = document.querySelector(".cr-card")!.getBoundingClientRect();
    return [".cr-source", ".dc-search"].every((s) => document.querySelector(s)!.getBoundingClientRect().right <= card.right);
  });
  expect(inside).toBe(true);

  // #and so must the editable card once the draft is written: its chips, rows and fields wrap rather than push the page
  await expect(page.getByTestId("card-editor").getByLabel("Name", { exact: true })).toHaveValue("Alice Chen", { timeout: 20_000 });
  await page.getByTestId("card-editor").getByRole("button", { name: /Show all \d+ options/ }).first().click();
  expect(await overflow()).toBe(false);
  const fits = await page.evaluate(() => {
    const frame = document.querySelector(".cr-profile")!.getBoundingClientRect();
    return [...document.querySelectorAll(".cr-profile *")].every((el) => el.getBoundingClientRect().right <= frame.right + 1);
  });
  expect(fits).toBe(true);
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
