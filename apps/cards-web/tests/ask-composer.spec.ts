import { test, expect, type Page } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

const MOCK = "http://127.0.0.1:3030";
const TEXT = "Building a team for ETHGlobal Bangkok, need a Solidity dev and a designer";
const LINK = "https://ethglobal.com/events/bangkok";

test.beforeEach(async ({ context, request }) => {
  await request.post(`${MOCK}/__feed/reset`);
  await signIn(context);
});

async function configure(page: Page, config: Record<string, unknown>) {
  await page.request.post(`${MOCK}/__feed/config`, { data: config });
}

const live = (extra: Record<string, unknown> = {}) => ({
  id: "ask-live-0",
  text: "Hiring a product designer for a seed-stage startup",
  kind: "hiring",
  url: null,
  created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  expires_at: new Date(Date.now() + 5 * 86_400_000 + 3_600_000).toISOString(),
  routed: 3,
  offer_count: 2,
  ...extra,
});

const insideDialog = (page: Page) => page.evaluate(() => !!document.activeElement?.closest("[role=dialog]"));

test("the Post button opens the composer, focus moves in and stays in, Esc closes and focus returns", async ({ page }) => {
  await page.goto("/feed");
  const fab = page.getByRole("button", { name: "Post an ask" });
  await expect(fab).toBeVisible();
  await expect(fab).toContainText("Post");
  await fab.click();

  const dialog = page.getByRole("dialog", { name: "Post an ask" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(dialog.getByRole("radio")).toHaveCount(8);
  await expect(dialog.getByRole("radio", { checked: true })).toHaveCount(0);          // nothing preselected
  await expect(dialog.getByRole("button", { name: "Post", exact: true })).toBeDisabled();
  await expect(dialog.getByRole("radio").first()).toBeFocused();

  for (let i = 0; i < 24; i++) {
    await page.keyboard.press("Tab");
    expect(await insideDialog(page)).toBe(true);
  }
  for (let i = 0; i < 24; i++) {
    await page.keyboard.press("Shift+Tab");
    expect(await insideDialog(page)).toBe(true);
  }

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(fab).toBeFocused();

  await fab.click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(4, 4);                                                    // the backdrop
  await expect(dialog).toHaveCount(0);
  await expect(fab).toBeFocused();
});

test("the kinds are a radio group a keyboard can drive", async ({ page }) => {
  await page.goto("/feed");
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await page.keyboard.press("ArrowDown");
  await expect(dialog.getByRole("radio", { checked: true })).toHaveCount(1);
  await expect(dialog.getByRole("radio", { name: "Looking for a co-founder" })).toBeChecked();
});

test("pick a kind, write, see the preview, post: the API gets the ask and the live ask card appears", async ({ page, request }) => {
  await page.goto("/feed");
  await expect(page.getByRole("heading", { name: "Your live ask" })).toHaveCount(0);
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");

  await dialog.getByRole("radio", { name: "Building a team" }).check();
  const box = dialog.getByRole("textbox", { name: "Your ask" });
  await expect(box).toHaveAttribute("placeholder", /ETHGlobal Bangkok/);
  await box.fill(TEXT);
  await expect(dialog.getByText(`${TEXT.length}/280`)).toBeVisible();
  await dialog.getByRole("textbox", { name: /Link/ }).fill(LINK);

  const preview = dialog.getByRole("group", { name: "How it will look" });
  await expect(preview).toContainText(TEXT);
  await expect(preview).toContainText("Building a team");
  await expect(preview).toContainText("ethglobal.com");
  await expect(preview).toContainText("Alice Chen");
  await expect(dialog).toContainText("Visible for 7 days · sent to people who match");

  const post = dialog.getByRole("button", { name: "Post", exact: true });
  await expect(post).toBeEnabled();
  await post.click();

  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Your ask is live" })).toBeVisible();
  const card = page.getByRole("region", { name: "Your live ask" });
  await expect(card).toContainText(TEXT);
  await expect(card).toContainText("Building a team");
  await expect(card).toContainText("Ends in 7 days");
  await expect(card.getByRole("link", { name: "Manage" })).toHaveAttribute("href", "/home#ask-closeout");
  await expect(card.getByRole("link", { name: /ethglobal.com/ })).toHaveAttribute("rel", "noopener noreferrer nofollow ugc");

  const { posts } = await (await request.get(`${MOCK}/__feed/posts`)).json();
  expect(posts).toEqual([{ kind: "team", text: TEXT, url: LINK }]);
  await expect(page.getByRole("button", { name: "Post an ask" })).toBeFocused();
});

test("a bad link is refused in the page and nothing is sent", async ({ page, request }) => {
  await page.goto("/feed");
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "Hiring" }).check();
  await dialog.getByRole("textbox", { name: "Your ask" }).fill("Hiring a Go engineer");
  await dialog.getByRole("textbox", { name: /Link/ }).fill("javascript:alert(1)");
  await dialog.getByRole("button", { name: "Post", exact: true }).click();
  await expect(dialog).toContainText("Use a web address that starts with http:// or https://");
  const { posts } = await (await request.get(`${MOCK}/__feed/posts`)).json();
  expect(posts).toEqual([]);
});

test("with a live ask the composer says posting replaces it, and it can be edited or taken down", async ({ page, request }) => {
  await configure(page, { live: live() });
  await page.goto("/feed");

  const card = page.getByRole("region", { name: "Your live ask" });
  await expect(card).toContainText("Hiring a product designer");
  await expect(card).toContainText("Sent to 3 people");
  await expect(card).toContainText("2 offered help");
  await expect(card).toContainText("Ends in 5 days");

  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Posting this replaces your current ask.")).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Your ask" })).toHaveValue("");
  await page.keyboard.press("Escape");

  await card.getByRole("button", { name: "Edit" }).click();
  await expect(dialog.getByRole("heading", { name: "Edit your ask" })).toBeVisible();
  await expect(dialog.getByRole("textbox", { name: "Your ask" })).toHaveValue("Hiring a product designer for a seed-stage startup");
  await expect(dialog.getByRole("radio", { name: "Hiring" })).toBeChecked();

  // Taking it down asks first.
  await dialog.getByRole("button", { name: "Take it down" }).click();
  await expect(dialog.getByRole("button", { name: "Yes, take it down" })).toBeFocused();
  await dialog.getByRole("button", { name: "Keep it" }).click();
  await expect(dialog.getByRole("button", { name: "Take it down" })).toBeVisible();
  await dialog.getByRole("button", { name: "Take it down" }).click();
  await dialog.getByRole("button", { name: "Yes, take it down" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your live ask" })).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Your ask is down" })).toBeVisible();
  const state = await (await request.get(`${MOCK}/cards/mine/asks`, { headers: { Authorization: "Bearer x" } })).json();
  expect(state.asks).toEqual([]);
});

test("a daily-limit error from the server shows inside the composer and keeps what was typed", async ({ page }) => {
  await configure(page, { postStatus: 429, postDetail: "You can post at most 5 asks a day. Try again tomorrow." });
  await page.goto("/feed");
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "Something else" }).check();
  await dialog.getByRole("textbox", { name: "Your ask" }).fill("Need an intro to a VC");
  await dialog.getByRole("button", { name: "Post", exact: true }).click();
  await expect(dialog.getByRole("alert")).toHaveText("You can post at most 5 asks a day. Try again tomorrow.");
  await expect(dialog.getByRole("textbox", { name: "Your ask" })).toHaveValue("Need an intro to a VC");
  await expect(page.getByRole("heading", { name: "Your live ask" })).toHaveCount(0);

  await configure(page, { postStatus: 409, postDetail: "Your card changed. Reload before publishing this beacon." });
  await dialog.getByRole("button", { name: "Post", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Your card changed");
});

test("at 360px the Post button never covers Load more and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto("/feed");
  const more = page.getByRole("button", { name: "Load more" });
  await more.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const fab = await page.getByRole("button", { name: "Post an ask" }).boundingBox();
  const target = await more.boundingBox();
  expect(fab && target).toBeTruthy();
  const overlaps = fab!.x < target!.x + target!.width && fab!.x + fab!.width > target!.x &&
    fab!.y < target!.y + target!.height && fab!.y + fab!.height > target!.y;
  expect(overlaps).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // The composer is a bottom sheet here, and it fits.
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "Raising money" }).check();
  await dialog.getByRole("textbox", { name: "Your ask" }).fill("Raising a pre-seed for a developer tool");
  const sheet = await dialog.boundingBox();
  expect(sheet!.x).toBe(0);
  expect(sheet!.width).toBe(360);
  expect(Math.round(sheet!.y + sheet!.height)).toBe(740);
  await expect(dialog.getByRole("button", { name: "Post", exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
});

test("someone without a card is asked to create one", async ({ page }) => {
  await configure(page, { hasCard: false });
  await page.goto("/feed");
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Create your card to post")).toBeVisible();
  await expect(dialog.getByRole("link", { name: "Create your card" })).toHaveAttribute("href", "/create");
  await expect(dialog.getByRole("radio")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("the asks tab filters by kind, ask items show the kind, the link and a per-kind reply, and can be reported", async ({ page, request }) => {
  await page.goto("/feed?filter=asks");
  const kinds = page.getByRole("navigation", { name: "Type of ask" });
  await expect(kinds.getByRole("link")).toHaveCount(9);
  await expect(kinds.getByRole("link", { name: "All" })).toHaveAttribute("aria-current", "true");

  const sarah = page.getByRole("article").filter({ hasText: "Sarah Iyer" });
  await expect(sarah.getByText("Building a team", { exact: true })).toBeVisible();
  const link = sarah.getByRole("link", { name: /ethglobal.com/ });
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow ugc");
  await expect(sarah.getByRole("button", { name: "I'm in" })).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "Ravi Das" }).getByRole("button", { name: "I can help" })).toBeVisible();

  await sarah.getByRole("button", { name: "I'm in" }).click();
  await expect(sarah.getByRole("textbox")).toHaveValue("Hi Sarah, I'd like to join your team: ");

  await sarah.getByRole("button", { name: /^Report/ }).click();
  await sarah.getByRole("radio", { name: "Spam or an ad" }).check();
  await sarah.getByRole("button", { name: "Send report" }).click();
  await expect(sarah.getByText("Thanks, we'll take a look.")).toBeVisible();
  const { reports } = await (await request.get(`${MOCK}/__feed/posts`)).json();
  expect(reports).toEqual([{ handle: "sarah", reason: "spam" }]);

  await kinds.getByRole("link", { name: "Hiring" }).click();
  await expect(page).toHaveURL(/filter=asks&kind=hiring/);
  await expect(page.getByRole("article").filter({ hasText: "Dan Wu" })).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "Sarah Iyer" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Type of ask" }).getByRole("link", { name: "Hiring" })).toHaveAttribute("aria-current", "true");
});
