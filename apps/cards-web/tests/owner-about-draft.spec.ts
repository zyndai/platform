import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

const DRAFT = "Alice Chen builds Verusa and is working on LinkedIn outreach. She is an expert in compliance engineering.";

/**
 * "Refresh About from memory" proposes a new About paragraph. It must be a preview: the text
 * the owner wrote is untouched until they click "Use this draft".
 */
test.describe("About draft from memory", () => {
  test.beforeEach(async ({ context }) => {
    await signIn(context);
  });

  test("previews without changing the text; keep mine discards; use this draft applies", async ({ page }) => {
    await page.goto("/p/owner/edit");
    const about = page.locator("section", { hasText: "A few sentences on what you do" });
    const box = page.getByPlaceholder("Write a short professional summary");
    const original = await box.inputValue();
    expect(original).toBe("Engineer.");

    await about.getByRole("button", { name: "Refresh About from memory" }).click();
    const preview = page.getByTestId("about-draft");
    await expect(preview).toContainText(DRAFT);
    await expect(preview).toContainText("Based on: Building: Verusa");
    await expect(preview).toContainText("Working on right now: LinkedIn outreach");
    expect(await box.inputValue()).toBe(original); // a preview never edits the text

    await preview.getByRole("button", { name: "Keep mine" }).click();
    await expect(page.getByTestId("about-draft")).toHaveCount(0);
    expect(await box.inputValue()).toBe(original);

    await about.getByRole("button", { name: "Refresh About from memory" }).click();
    await page.getByTestId("about-draft").getByRole("button", { name: "Use this draft" }).click();
    await expect(page.getByTestId("about-draft")).toHaveCount(0);
    expect(await box.inputValue()).toBe(DRAFT);
  });
});
