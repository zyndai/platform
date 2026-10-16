import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

test.describe("S10 owner home", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ context, request }) => {
    await request.post("http://127.0.0.1:3030/__s10/reset");
    await signIn(context);
  });

  test("shows real activity, review count and editable preferences", async ({
    page,
  }) => {
    await page.goto("/home");
    await expect(
      page.getByRole("heading", { name: "Welcome back, Alice." }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "3 facts to review" }),
    ).toBeVisible();
    expect(
      await page
        .getByRole("heading", { name: "Welcome back, Alice." })
        .evaluate((el) => getComputedStyle(el).webkitTextFillColor),
    ).toBe("rgb(23, 32, 51)");
    await expect(page.getByText("12", { exact: true })).toBeVisible();
    await expect(page.getByText("4", { exact: true })).toBeVisible();
    const questionHistory = page.getByRole("region", { name: "Recent assistant questions" });
    await expect(questionHistory.getByText("What projects is Alice building?", { exact: true })).toBeVisible();
    await expect(questionHistory.getByText('<img src=x onerror="window.questionHistoryXss=1">', { exact: true })).toBeVisible();
    await expect(questionHistory.locator("img")).toHaveCount(0);
    expect(await page.evaluate(() => "questionHistoryXss" in window)).toBe(false);
    await page.getByRole("checkbox", { name: /Weekly digest/ }).uncheck();
    await expect(page.getByRole("status").first()).toHaveText("Saved");
    await page.reload();
    await expect(
      page.getByRole("checkbox", { name: /Weekly digest/ }),
    ).not.toBeChecked();
    await page.screenshot({
      path: "/tmp/zynd-s10-home-desktop.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: "/tmp/zynd-s10-home-mobile.png",
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });

  test("merges cards and redirects the archived URL with 301", async ({
    page,
    request,
  }) => {
    await page.goto("/home");
    await page.getByRole("button", { name: "Merge cards" }).click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: "Choose your canonical card" }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Merge and archive" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Merge cards" })).toHaveCount(
      0,
    );
    const response = await request.get("/p/old-owner", { maxRedirects: 0 });
    expect(response.status()).toBe(301);
    expect(response.headers().location).toContain("/p/owner");
  });

  test("autosaves the latest edits before navigating away", async ({
    page,
    request,
  }) => {
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Alice Updated");
    await page.getByRole("link", { name: "Owner home", exact: true }).click();
    await expect(page).toHaveURL(/\/home$/);
    const saved = await request.get(
      "http://127.0.0.1:3030/cards/by-handle/owner",
    );
    expect((await saved.json()).identity.name).toBe("Alice Updated");
  });

  test("failed autosave keeps the draft and blocks navigation", async ({
    page,
  }) => {
    await page.route("**/cards/by-handle/owner/sections/identity", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Section changed in another session. Reload before saving.",
        }),
      }),
    );
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Unsaved Alice");
    await page.getByRole("link", { name: "Owner home", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Not saved");
    await expect(page.getByLabel("Full name", { exact: true })).toHaveValue(
      "Unsaved Alice",
    );
    await expect(page).toHaveURL(/\/p\/owner\/edit$/);
  });

  test("autosave preserves a private card", async ({ page, request }) => {
    await page.goto("/home");
    await page.getByRole("checkbox", { name: /Public card/ }).uncheck();
    await expect(page.getByRole("status").first()).toHaveText("Saved");
    await page.getByRole("link", { name: "Edit your card" }).click();
    await page.getByLabel("Full name", { exact: true }).fill("Private Alice");
    await page.getByRole("link", { name: "Owner home", exact: true }).click();
    await expect(page).toHaveURL(/\/home$/);
    const saved = await request.get(
      "http://127.0.0.1:3030/cards/by-handle/owner",
    );
    expect((await saved.json()).status).toBe("private");
  });

  test("offers unsaved draft recovery after reload", async ({
    page,
    request,
  }) => {
    await page.route("**/cards/by-handle/owner/sections/identity", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Temporarily unavailable" }),
      }),
    );
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Recovered Alice");
    await expect(page.getByRole("status")).toContainText("Not saved");
    page.on("dialog", (dialog) => dialog.accept());
    await page.reload();
    await expect(
      page.getByText("You have unsaved changes from your last visit."),
    ).toBeVisible();
    await page.unroute("**/cards/by-handle/owner/sections/identity");
    await page.getByRole("button", { name: "Restore unsaved changes" }).click();
    await expect
      .poll(
        async () =>
          (
            await (
              await request.get("http://127.0.0.1:3030/cards/by-handle/owner")
            ).json()
          ).identity.name,
      )
      .toBe("Recovered Alice");
  });
});

test("owner home sends anonymous visitors to sign-in", async ({ page }) => {
  await page.goto("/home");
  await expect(page).toHaveURL(/\/auth\?next=/);
});
