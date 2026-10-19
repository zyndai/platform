import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

/**
 * The editor is split into tabs. Old /edit#<section> links (owner home, completeness
 * actions, notification emails) must still land on the right tab, and the AI tab
 * shows how many facts wait for review.
 */
test.describe("card editor tabs", () => {
  test.beforeEach(async ({ context }) => {
    await signIn(context);
  });

  test("opens on Profile and switches tabs by click and keyboard", async ({ page }) => {
    await page.goto("/p/owner/edit");
    const tabs = page.getByRole("tablist", { name: "Edit sections" });
    await expect(tabs.getByRole("tab", { name: "Profile" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByLabel("Full name", { exact: true })).toBeVisible();
    await expect(page.locator("#skills")).toBeHidden();

    await tabs.getByRole("tab", { name: "Interests & Skills" }).click();
    await expect(page).toHaveURL(/#interests$/);
    await expect(page.locator("#skills")).toBeVisible();
    await expect(page.getByLabel("Full name", { exact: true })).toBeHidden();

    await page.keyboard.press("ArrowRight");
    await expect(tabs.getByRole("tab", { name: "Imported" })).toHaveAttribute("aria-selected", "true");
    await expect(tabs.getByRole("tab", { name: "Imported" })).toBeFocused();
    await expect(page.locator("#career")).toBeVisible();
  });

  for (const [anchor, tab] of [["skills", "Interests & Skills"], ["projects", "Imported"], ["avatar", "Profile"], ["connect-mcp", "AI & Memory"]]) {
    test(`#${anchor} deep link opens ${tab}`, async ({ page }) => {
      await page.goto(`/p/owner/edit#${anchor}`);
      await expect(page.getByRole("tab", { name: new RegExp(`^${tab.replace("&", "\\&")}`) })).toHaveAttribute("aria-selected", "true");
      await expect(page.locator(`#${anchor}`)).toBeVisible();
    });
  }

  test("inbox link opens the review list and the tab counts what's waiting", async ({ page }) => {
    await page.route("**/cards/mcp/suggestions", (route) => route.fulfill({
      status: 200,
      json: { suggestions: [
        { predicate: "has_expertise_in", object: "Postgres", confidence: 0.9, group: "right" },
        { predicate: "is_building", object: "Zynd Cards", confidence: 0.8, group: "right" },
      ] },
    }));
    await page.route("**/cards/mcp/dismiss", (route) => route.fulfill({ status: 200, json: {} }));
    await page.goto("/p/owner/edit#inbox");
    const aiTab = page.getByRole("tab", { name: /^AI & Memory/ });
    await expect(aiTab).toHaveAttribute("aria-selected", "true");
    await expect(aiTab).toHaveAccessibleName("AI & Memory, 2 to review");
    const inbox = page.locator("#inbox");
    await expect(inbox.getByText("Expert in: Postgres")).toBeVisible();
    await inbox.getByRole("button", { name: "Dismiss", exact: true }).first().click();
    await expect(aiTab).toHaveAccessibleName("AI & Memory, 1 to review");
  });

  test("fits a phone screen without sideways scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const hash of ["profile", "interests", "imported", "ai"]) {
      await page.goto(`/p/owner/edit#${hash}`);
      await expect(page.getByRole("tab", { selected: true })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `#${hash} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
    }
  });
});
