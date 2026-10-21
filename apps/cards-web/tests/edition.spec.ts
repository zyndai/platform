import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

/**
 * Mumbai Builder Week '26 edition: an owner can pick it, everyone who opens the
 * card sees it, and a card that never picked it looks exactly as before.
 */
test.describe("limited-edition card style", () => {
  test.beforeEach(async ({ request }) => {
    await request.post("http://127.0.0.1:3030/__s10/reset");
  });

  test("a classic card shows no edition banner", async ({ page }) => {
    // #given the fixture owner has never picked an edition
    // #when a visitor opens the card
    await page.goto("/p/owner?preview=visitor");

    // #then the classic hero is there and nothing edition-only is
    await expect(page.getByText("I'm", { exact: true })).toBeVisible();
    await expect(page.locator(".ed-hero")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Show my QR" })).toHaveCount(0);
  });

  test("owner picks the edition in the editor and visitors see it", async ({ page, context }) => {
    // #given a signed-in owner on the Profile tab
    await signIn(context);
    await page.goto("/p/owner/edit");
    const style = page.locator("#style");
    await expect(style.getByRole("button", { name: /^Classic/ })).toHaveAttribute("aria-pressed", "true");

    // #when they pick the edition and a reason, and save
    await style.getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await expect(style.getByRole("button", { name: "Dusk", exact: true })).toHaveCount(0);
    await style.getByRole("button", { name: "Speaking", exact: true }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();

    // #then the public card shows the edition banner with the chosen reason
    await page.goto("/p/owner?preview=visitor");
    const hero = page.locator(".ed-hero");
    await expect(hero).toBeVisible();
    await expect(hero.getByText("Here for · Speaking")).toBeVisible();
    await expect(hero.getByText("Alice Chen")).toBeVisible();
    await expect(hero.getByText("MUMBAI BUILDER WEEK")).toBeVisible();
    // the classic purple hero is replaced, not shown twice
    await expect(page.locator(".pf-hero")).toHaveCount(0);

    // #and reopening the editor shows the saved choice without unsaved changes
    await page.goto("/p/owner/edit");
    await expect(style.getByRole("button", { name: /Mumbai Builder Week/ })).toHaveAttribute("aria-pressed", "true");
    await expect(style.getByRole("button", { name: "Speaking", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Save changes" }).first()).toBeDisabled();
  });

  test("switching back to classic removes the edition", async ({ page, context, request }) => {
    // #given an owner whose card uses the edition
    await signIn(context);
    await page.goto("/p/owner/edit");
    const style = page.locator("#style");
    await style.getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();

    // #when they pick Classic and save
    await style.getByRole("button", { name: /^Classic/ }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();

    // #then the stored card has no edition and the public card is classic again
    const card = await (await request.get("http://127.0.0.1:3030/cards/by-handle/owner")).json();
    expect(card.identity.edition ?? null).toBeNull();
    await page.goto("/p/owner?preview=visitor");
    await expect(page.locator(".ed-hero")).toHaveCount(0);
  });

  test("the QR screen opens, closes with Escape and returns focus", async ({ page, context }) => {
    // #given a card on the edition
    await signIn(context);
    await page.goto("/p/owner/edit");
    await page.locator("#style").getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();
    await context.clearCookies();
    await page.goto("/p/owner");

    // #when a visitor taps Show my QR
    const trigger = page.getByRole("button", { name: "Show my QR" });
    await trigger.click();

    // #then a dialog shows the QR on its own panel with the card link
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(".ed-qr-panel svg")).toBeVisible();
    await expect(dialog.locator(".ed-qr-url")).toContainText("/p/owner");

    // #and keyboard focus stays inside the dialog
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    }

    // #and Escape closes it and puts focus back on the button
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("the QR screen saves a phone wallpaper", async ({ page, context }) => {
    // #given the QR screen of a card on the edition
    await signIn(context);
    await page.goto("/p/owner/edit");
    await page.locator("#style").getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await page.getByRole("button", { name: "Save changes" }).first().click();
    await expect(page.getByText("Changes saved", { exact: true })).toBeVisible();
    await page.goto("/p/owner?preview=visitor");
    await page.getByRole("button", { name: "Show my QR" }).click();

    // #when the owner saves it as a wallpaper (desktop: a download)
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Save as phone wallpaper" }).click(),
    ]);

    // #then they get a phone-sized PNG
    expect(download.suggestedFilename()).toBe("zynd-owner-mumbai-26-wallpaper.png");
    const png = await readFile(await download.path());
    expect(png.subarray(1, 4).toString()).toBe("PNG");
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1170, 2532]);
  });

  test("create flow offers the style last and publishes the choice", async ({ page }) => {
    // #given a new card in review
    await page.goto("/create");
    const input = page.getByPlaceholder("github.com/you  or  linkedin.com/in/you");
    await input.fill("github.com/bob");
    await input.press("Enter");
    await page.getByRole("button", { name: "Build my card" }).click();
    await page.getByRole("button", { name: "Continue without signing in" }).click();
    const style = page.locator(".zc-card", { has: page.getByText("Card style", { exact: true }) });
    await expect(style).toBeVisible({ timeout: 45_000 });

    // #then Card style is the last section, right before Publish
    await expect(page.locator(".zc-card:has-text('Card style') + .zc-ctarow")).toHaveCount(1);

    // #when they pick the edition and publish
    await style.getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await style.getByRole("button", { name: "Building", exact: true }).click();
    const publishRequest = page.waitForRequest((r) => r.url().endsWith("/onboard/job1/publish"));
    await page.getByRole("button", { name: /Publish my card/ }).click();

    // #then the published card carries the edition
    const body = (await publishRequest).postDataJSON();
    expect(body.card.identity.edition).toEqual({ id: "mumbai-26", mood: "night", here_for: "building" });
  });

  test("mobile: banner and QR fit the screen", async ({ browser }) => {
    // #given a card on the edition opened on a phone-sized screen
    const owner = await browser.newContext();
    await signIn(owner);
    const editor = await owner.newPage();
    await editor.goto("/p/owner/edit");
    await editor.locator("#style").getByRole("button", { name: /Mumbai Builder Week/ }).click();
    await editor.getByRole("button", { name: "Save changes" }).first().click();
    await expect(editor.getByText("Changes saved", { exact: true })).toBeVisible();
    await owner.close();

    const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const page = await phone.newPage();
    await page.goto("/p/owner");

    // #then nothing scrolls sideways, before or after opening the QR
    const overflows = () => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    await expect(page.locator(".ed-hero")).toBeVisible();
    expect(await overflows()).toBe(false);
    await page.getByRole("button", { name: "Show my QR" }).click();
    await expect(page.getByRole("dialog").locator(".ed-qr-panel svg")).toBeVisible();
    expect(await overflows()).toBe(false);
    await phone.close();
  });
});
