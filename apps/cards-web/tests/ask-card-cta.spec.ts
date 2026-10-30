import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

// The fixture API refuses /v1/chat/claimed, so answers are stubbed at the browser.
async function stubChat(page: Page, reply: string | null) {
  await page.route("**/api/chat/profile", (route) => reply === null
    ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "Chatbot unavailable" }) })
    : route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `data: ${JSON.stringify({ response: reply })}\n\ndata: [DONE]\n\n`,
    }));
}

async function ask(page: Page, question: string) {
  const input = page.getByRole("textbox", { name: "Your question" });
  await input.fill(question);
  await input.press("Enter");
}

test.describe("ask-the-card create CTA", () => {
  test("a visitor sees it once, after the first answer", async ({ page }) => {
    await stubChat(page, "Alice is building agent tooling.");
    await page.goto("/p/claimed");
    await page.locator(".pf-chat-fab").click();

    const cta = page.getByTestId("ask-card-create-cta");
    await expect(cta).toHaveCount(0);

    await ask(page, "What is Alice building?");
    await expect(cta).toHaveCount(1);
    await expect(cta.getByRole("link", { name: "Create your card" })).toHaveAttribute("href", "/create?ref=ask_card");

    await ask(page, "Anything else?");
    await expect(page.getByText("Alice is building agent tooling.")).toHaveCount(2);
    await expect(cta).toHaveCount(1);
  });

  test("a failed answer does not show it", async ({ page }) => {
    await stubChat(page, null);
    await page.goto("/p/claimed");
    await page.locator(".pf-chat-fab").click();

    await ask(page, "What is Alice building?");
    await expect(page.getByText("Chatbot unavailable")).toBeVisible();
    await expect(page.getByTestId("ask-card-create-cta")).toHaveCount(0);
  });

  test("a signed-in viewer who already has a card does not see it", async ({ context, page }) => {
    await signIn(context);
    await stubChat(page, "Alice is building agent tooling.");
    await page.goto("/p/claimed");
    await page.locator(".pf-chat-fab").click();

    await ask(page, "What is Alice building?");
    await expect(page.getByText("Alice is building agent tooling.")).toBeVisible();
    await expect(page.getByTestId("ask-card-create-cta")).toHaveCount(0);
  });
});
