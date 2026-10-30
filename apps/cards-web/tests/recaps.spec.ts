import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";
import { RECAP_ID } from "./fixtures/recaps";

test.beforeEach(async ({ context, request }) => {
  await request.post("http://127.0.0.1:3030/__recaps/reset");
  await signIn(context);
});

test("review, render a PNG, publish selected highlights and unpublish", async ({ page, request }) => {
  await page.goto("/home/recaps");
  await expect(page.getByRole("heading", { name: /A little less blank page/ })).toBeVisible();
  await page.getByRole("button", { name: "Generate recap" }).click();
  await expect(page.getByText("Private draft", { exact: true })).toBeVisible();
  const publicPath = `/p/owner/recaps/${RECAP_ID}`;
  expect((await request.get(publicPath)).status()).toBe(404);
  await page.getByRole("checkbox", { name: /Explored: Vue/ }).uncheck();
  await page.getByRole("textbox", { name: "Your caption" }).fill("September: shipped Launchpad and made 34 GitHub contributions.");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status").first()).toHaveText("Private draft saved.");
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PNG" }).click();
  const download = await downloading;
  const { readFile } = await import("node:fs/promises");
  const png = await readFile((await download.path())!);
  expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  expect(png.readUInt32BE(16)).toBe(1200);
  expect(png.readUInt32BE(20)).toBe(630);
  await page.getByRole("button", { name: "Publish recap" }).click();
  await expect(page.getByRole("button", { name: "Unpublish to edit" })).toBeVisible();
  await page.goto(publicPath);
  await expect(page.getByRole("heading", { name: "Alice Chen’s chapter." }).or(page.getByRole("heading", { name: "Alice Chen's chapter." }))).toBeVisible();
  await expect(page.getByRole("list").getByText("Shipped Launchpad", { exact: true })).toBeVisible();
  await expect(page.getByText("Explored Vue", { exact: true })).toHaveCount(0);
  const meta = page.locator('meta[property="og:image"]');
  await expect(meta).toHaveAttribute("content", new RegExp(`/api/recaps/${RECAP_ID}/image`));
  await page.screenshot({ path: "/tmp/zynd-recap-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "/tmp/zynd-recap-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.goto("/home/recaps");
  await page.getByRole("button", { name: "Unpublish to edit" }).click();
  expect((await request.get(publicPath)).status()).toBe(404);
  expect((await request.get(`/api/recaps/${RECAP_ID}/image?handle=owner`)).status()).toBe(404);
});

test("record a milestone and keep owner downloads private", async ({ page, browser }) => {
  await page.goto("/home/recaps");
  await page.getByLabel("Project name").fill("Launchpad");
  await page.getByLabel("Date", { exact: true }).fill("2026-09-12");
  await page.getByRole("button", { name: "Confirm milestone" }).click();
  await expect(page.getByRole("status").first()).toContainText("Milestone recorded");
  await page.getByRole("button", { name: "Generate recap" }).click();
  const anonymous = await browser.newContext();
  const response = await anonymous.request.get(`http://127.0.0.1:3010/api/recaps/${RECAP_ID}/image?preview=1`);
  expect(response.status()).toBe(401);
  await anonymous.close();
});
