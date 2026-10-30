import { expect, test, type Page } from "@playwright/test";

// /p/pitchcard is a card whose owner asks for a pitch first; the fixture API answers
// /v1/chat/pitchcard/pitch: "devtools" passes, "again" is rate-limited, anything else declines.
async function openPitch(page: Page) {
  await page.goto("/p/pitchcard");
  await page.getByRole("button", { name: /Pitch to book a call/ }).first().click();
  await expect(page.getByTestId("pitch-step")).toBeVisible();
  return page.getByRole("textbox", { name: "Why do you want to meet Alice?" });
}

test.describe("pitch before booking", () => {
  test("the page carries no booking link before a pitch", async ({ page }) => {
    await page.goto("/p/pitchcard");
    await expect(page.getByRole("button", { name: /Pitch to book a call/ }).first()).toBeVisible();
    await expect(page.locator('a[href*="calendly.com"]')).toHaveCount(0);
  });

  test("a passing pitch reveals the booking link", async ({ page }) => {
    const pitch = await openPitch(page);
    await pitch.fill("I run a devtools startup and want to compare notes on agent runtimes.");
    await page.getByRole("button", { name: "Send pitch" }).click();

    await expect(page.getByText("Alice wants to meet devtools founders.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Book on Calendly" })).toHaveAttribute("href", "https://calendly.com/alice/pitched");

    // #and going back to chat keeps the unlocked link for the rest of the visit
    await page.getByRole("button", { name: "Back to chat" }).click();
    await page.evaluate(() => window.dispatchEvent(new Event("zynd:open-pitch")));
    await expect(page.getByRole("link", { name: "Book on Calendly" })).toBeVisible();
  });

  test("a declined pitch gets a friendly reason and another route, no link", async ({ page }) => {
    const pitch = await openPitch(page);
    await pitch.fill("Want to buy backlinks for your site?");
    await page.getByRole("button", { name: "Send pitch" }).click();

    await expect(page.getByText("Alice is looking for devtools founders right now.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask a question instead" })).toBeVisible();
    await expect(page.locator('a[href*="calendly.com"]')).toHaveCount(0);

    await page.getByRole("button", { name: "Ask a question instead" }).click();
    await expect(page.getByRole("textbox", { name: "Your question" })).toBeVisible();
  });

  test("a rate-limited pitch keeps the text and says when to retry", async ({ page }) => {
    const pitch = await openPitch(page);
    await pitch.fill("Trying again with the same note.");
    await page.getByRole("button", { name: "Send pitch" }).click();

    await expect(page.getByTestId("pitch-step").getByRole("alert")).toHaveText("You've sent a pitch recently. Try again in a few minutes.");
    await expect(pitch).toHaveValue("Trying again with the same note.");
  });

  test("cards without the opt-in keep their direct booking flow", async ({ page }) => {
    await page.goto("/p/claimed");
    await expect(page.getByRole("button", { name: /Pitch to book a call/ })).toHaveCount(0);
  });
});
