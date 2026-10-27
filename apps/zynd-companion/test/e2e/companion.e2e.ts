import { chromium, expect, test, type BrowserContext, type Page } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { ORIGIN, startMock } from "./mock-zynd";

const extension = resolve(import.meta.dirname, "../../dist-e2e");
const mock = startMock();
let context: BrowserContext;
let id: string;
let usedState = "";

const ARTICLE = `<!doctype html><title>The Verge story</title>
<meta property="og:title" content="How chips got hot"><meta property="og:type" content="article">
<h1>Story</h1><p id="p">Some paragraph the reader selected.</p>`;

test.beforeAll(async () => {
  await mock.listen();
  context = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), "zynd-companion-")), {
    channel: "chromium",
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
  });
  const worker = context.serviceWorkers()[0] ?? (await context.waitForEvent("serviceworker"));
  id = new URL(worker.url()).host;
  // Sites the tests visit are served here, so no network is needed.
  await context.route("https://**/*", (route) => route.fulfill({ contentType: "text/html", body: ARTICLE }));
  await context.route("http://localhost:4777/**", (route) => route.fulfill({ contentType: "text/html", body: ARTICLE }));
});

test.afterAll(async () => {
  await context?.close();
  await mock.close();
});

/** Open the popup the way Chrome would for the page `under`: the popup reads the active tab. */
async function openPopup(under: Page, beforeReload?: () => Promise<void>): Promise<Page> {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  await under.bringToFront();
  await beforeReload?.(); // the first load above already used up anything set earlier
  await popup.reload(); // now the active tab is `under`, not the popup tab itself
  return popup;
}

test("an unpaired extension does nothing but offer to connect", async () => {
  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  const popup = await openPopup(page);
  await expect(popup.getByRole("button", { name: "Connect Zynd account" })).toBeVisible();
  await expect(popup.getByRole("textbox", { name: "Working on" })).toHaveCount(0);
  expect(mock.db.requests).toEqual([]);
  await popup.close();
  await page.close();
});

test("a grant that this extension did not ask for is refused", async () => {
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/companion/connect?state=${"c".repeat(32)}`);
  await page.evaluate(() => (window as unknown as { forge(t: string): void }).forge("zdc_" + "x".repeat(30)));
  await expect(page.locator("#s")).toContainText("rejected: This connection was not started from the extension");
  await expect(page.locator("#b")).toBeDisabled(); // and it never said ready
  await page.close();
});

test("pairing: start in the extension, confirm on the website, token kept", async () => {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  const [connectPage] = await Promise.all([
    context.waitForEvent("page"),
    popup.getByRole("button", { name: "Connect Zynd account" }).click(),
  ]);
  await connectPage.waitForLoadState();
  usedState = new URL(connectPage.url()).searchParams.get("state") ?? "";
  expect(usedState).toMatch(/^[a-f0-9]{32}$/);
  await expect(connectPage.locator("#s")).toHaveText("ready");
  await connectPage.locator("#b").click();
  await expect(connectPage.locator("#s")).toHaveText("paired");
  await connectPage.close();

  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  const again = await openPopup(page);
  await expect(again.getByText("Dil Asrafi")).toBeVisible();
  await again.close();
  await page.close();
});

test("a pairing cannot be replayed once it has been used", async () => {
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/companion/connect?state=${usedState}`);
  await page.evaluate(() => (window as unknown as { forge(t: string): void }).forge("zdc_" + "y".repeat(30)));
  await expect(page.locator("#s")).toContainText("rejected: This connection was not started from the extension");
  await page.close();
});

test("Working on: add and remove", async () => {
  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  const popup = await openPopup(page);
  await popup.getByRole("textbox", { name: "Working on" }).fill("Zynd Companion");
  await popup.getByRole("textbox", { name: "Working on" }).press("Enter");
  await expect(popup.getByRole("list", { name: "Your working on lines" }).getByText("Zynd Companion")).toBeVisible();
  expect(mock.db.workingOn).toEqual(["Zynd Companion"]);
  await popup.getByRole("button", { name: "Remove Zynd Companion" }).click();
  await expect(popup.getByText("Zynd Companion")).toHaveCount(0);
  expect(mock.db.workingOn).toEqual([]);
  await popup.close();
  await page.close();
});

test("Currently exploring: the page is read, shown, and only sent when added", async () => {
  const page = await context.newPage();
  await page.goto("https://www.theverge.com/2026/10/1/chips?utm_source=newsletter&fbclid=abc#comments");
  await page.evaluate(() => {
    const range = document.createRange();
    range.selectNodeContents(document.getElementById("p")!);
    getSelection()!.removeAllRanges();
    getSelection()!.addRange(range);
  });
  const popup = await openPopup(page);
  await expect(popup.getByLabel("Title")).toHaveValue("How chips got hot");
  await expect(popup.getByRole("button", { name: "News", pressed: true })).toBeVisible();
  await expect(popup.getByLabel("Note")).toHaveValue("Some paragraph the reader selected.");
  await expect(popup.getByText("Public link: theverge.com/2026/10/1/chips")).toBeVisible();
  expect(mock.db.exploring).toEqual([]); // looking is not sending

  await popup.getByRole("button", { name: "Blog" }).click();
  await popup.getByRole("button", { name: "Add to my card" }).click();
  await expect(popup.getByRole("list", { name: "Recently added" })).toContainText("How chips got hot");
  expect(mock.db.exploring).toHaveLength(1);
  expect(mock.db.exploring[0]).toMatchObject({ url: "https://www.theverge.com/2026/10/1/chips", kind: "blog", title: "How chips got hot" });
  await popup.getByRole("button", { name: /Remove How chips/ }).click();
  await expect(popup.getByRole("list", { name: "Recently added" })).toHaveCount(0);
  expect(mock.db.exploring).toEqual([]);
  await popup.close();
  await page.close();
});

test("a page on the person's own computer cannot be added", async () => {
  const page = await context.newPage();
  await page.goto("http://localhost:4777/internal-tool");
  const popup = await openPopup(page);
  await expect(popup.getByText(/private network/)).toBeVisible();
  await expect(popup.getByRole("button", { name: "Add to my card" })).toHaveCount(0);
  await popup.close();
  await page.close();
});

test("revoked on the website: the extension notices and asks to connect again", async () => {
  mock.db.tokens.clear();
  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  const popup = await openPopup(page);
  await expect(popup.getByRole("button", { name: "Connect Zynd account" })).toBeVisible();
  await expect(popup.getByText("no longer connected")).toBeVisible();
  const kept = await context.serviceWorkers()[0]!.evaluate(() => chrome.storage.local.get("token"));
  expect(kept.token).toBeUndefined();
  await popup.close();
  await page.close();
});

test("a card left alone for too long gets a nudge, and one click settles it", async () => {
  // Pair again (the previous test revoked the token), then make the last change look old.
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  const [connectPage] = await Promise.all([context.waitForEvent("page"), popup.getByRole("button", { name: "Connect Zynd account" }).click()]);
  await expect(connectPage.locator("#s")).toHaveText("ready");
  await connectPage.locator("#b").click();
  await expect(connectPage.locator("#s")).toHaveText("paired");
  await connectPage.close();

  const worker = context.serviceWorkers()[0]!;
  await worker.evaluate(() => chrome.storage.local.set({ touchedAt: Date.now() - 11 * 86_400_000 }));
  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  await popup.close();
  const again = await openPopup(page);
  await expect(again.getByText("Still working on this?")).toBeVisible();
  await again.getByRole("button", { name: "Yes, keep it" }).click();
  await expect(again.getByText("Still working on this?")).toHaveCount(0);
  const { touchedAt } = (await worker.evaluate(() => chrome.storage.local.get("touchedAt"))) as { touchedAt: number };
  expect(Date.now() - touchedAt).toBeLessThan(60_000);
  await again.close();
  await page.close();
});

test("a clip started from the right-click menu opens prefilled for checking, and is not sent", async () => {
  const worker = context.serviceWorkers()[0]!;
  const page = await context.newPage();
  await page.goto("https://news.example.com/2026/story");
  const sent = mock.db.exploring.length;
  const popup = await openPopup(page, () => worker.evaluate(() => chrome.storage.session.set({
    draft: { url: "https://github.com/zyndai/platform?utm_source=x", title: "", note: "worth a read" },
  })));
  await expect(popup.getByRole("button", { name: "Repo", pressed: true })).toBeVisible();
  await expect(popup.getByLabel("Note")).toHaveValue("worth a read");
  await expect(popup.getByText("Public link: github.com/zyndai/platform")).toBeVisible();
  expect(mock.db.exploring.length).toBe(sent);
  const left = await worker.evaluate(() => chrome.storage.session.get("draft"));
  expect(left.draft).toBeUndefined(); // used once
  await popup.close();
  await page.close();
});
