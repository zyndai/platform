import { test, expect, type Page } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

async function recordCompletion(page: Page) {
  await page.addInitScript(() => {
    const frames: { number: number; fill: number }[] = [];
    (window as Window & { completionFrames?: typeof frames }).completionFrames = frames;
    new MutationObserver(() => {
      const ring = document.querySelector<HTMLElement>(".oh-ring");
      const fill = ring?.style.background.match(/([\d.]+)%/);
      if (ring && fill && frames.length < 300) {
        frames.push({ number: Number.parseInt(ring.textContent || "0", 10), fill: Number(fill[1]) });
      }
    }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["style"] });
  });
}

test.describe("S10 owner home", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ context, request }) => {
    await request.post("http://127.0.0.1:3030/__s10/reset");
    await signIn(context);
  });

  test("filters agent traffic and exports the visible real counts", async ({ page }) => {
    await page.goto("/home");
    const panel = page.getByRole("region", { name: "Which agents fetched your card" });
    await expect(panel.locator(".oh-agent-row")).toHaveCount(4);
    for (const provider of ["claude", "openai"]) {
      const logo = panel.locator(`img[src="/assets/agents/${provider}.svg"]`);
      await expect(logo).toBeVisible();
      await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    }
    await panel.getByRole("button", { name: /^MCP/ }).click();
    await expect(panel.locator(".oh-agent-row")).toHaveCount(1);
    await expect(panel.getByText("Zynd-MCP", { exact: true })).toBeVisible();
    await expect(panel.getByText("42.9% of requests", { exact: true })).toBeVisible();
    await panel.getByRole("textbox", { name: "Search agent traffic" }).fill("Claude");
    await expect(panel.getByText("No clients match your filters.")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Export CSV" })).toBeDisabled();
    await panel.getByRole("button", { name: "Clear filters" }).click();
    await panel.getByRole("textbox", { name: "Search agent traffic" }).fill("OpenAI");
    await expect(panel.locator(".oh-agent-row")).toHaveCount(1);
    const downloading = page.waitForEvent("download");
    await panel.getByRole("button", { name: "Export CSV" }).click();
    const download = await downloading;
    const { readFile } = await import("node:fs/promises");
    const csv = await readFile((await download.path())!, "utf8");
    expect(csv).toContain('"ChatGPT / OpenAI","GPTBot","Crawlers","1"');
    expect(csv).not.toContain("Zynd-MCP");
    await panel.getByRole("button", { name: "Clear agent search" }).click();
    await panel.getByRole("button", { name: /^Crawlers/ }).click();
    await expect(panel.getByText("GPTBot", { exact: true })).toBeVisible();
    await expect(panel.locator(".oh-agent-row")).toHaveCount(1);
    await panel.getByRole("button", { name: /^All clients/ }).click();
    await panel.screenshot({ path: "/tmp/zynd-agent-traffic-desktop.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    await panel.screenshot({ path: "/tmp/zynd-agent-traffic-mobile.png" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
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
    await expect(page.locator(".oh-discovery-agent strong").filter({ hasText: /^7$/ })).toBeVisible();
    const agentBreakdown = page.getByRole("region", { name: "Which agents fetched your card" });
    await expect(agentBreakdown.getByText("Claude-User", { exact: true })).toBeVisible();
    await expect(agentBreakdown.getByText("GPTBot", { exact: true })).toBeVisible();
    await expect(agentBreakdown.getByText("2 requests", { exact: true })).toBeVisible();
    const unidentified = page.getByRole("region", { name: "Unidentified profile requests" });
    await expect(unidentified.getByText("Node.js", { exact: true })).toBeVisible();
    await expect(unidentified.getByText("3 requests", { exact: true })).toBeVisible();
    await expect(unidentified.getByText(/Provider unknown/)).toBeVisible();
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

  test("animates the completion number and ring together", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await recordCompletion(page);
    await page.goto("/home");
    await expect(page.getByRole("img", { name: "Card completeness 75%" })).toHaveText("75%");
    const frames = await page.evaluate(() => (window as Window & { completionFrames?: { number: number; fill: number }[] }).completionFrames || []);
    expect(frames.some(frame => frame.number > 0 && frame.number < 75)).toBe(true);
    expect(frames.every(frame => frame.number === Math.round(frame.fill))).toBe(true);
    expect(frames.every((frame, index) => index === 0 || frame.fill >= frames[index - 1].fill)).toBe(true);
    await expect(page.getByRole("region", { name: "What people asked the assistant", exact: true })).toHaveCount(0);
    await expect(page.getByText("Setting", { exact: true })).toBeVisible();
    await expect(page.locator(".oh-attention")).toHaveCSS("background-color", "rgb(255, 255, 255)");
  });

  test("shows final completion without counting up when reduced motion is enabled", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await recordCompletion(page);
    await page.goto("/home");
    await expect(page.getByRole("img", { name: "Card completeness 75%" })).toHaveText("75%");
    const frames = await page.evaluate(() => (window as Window & { completionFrames?: { number: number; fill: number }[] }).completionFrames || []);
    expect(frames.every(frame => frame.number === 0 || frame.number === 75)).toBe(true);
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

  test("saves edits only when Save changes is clicked", async ({
    page,
    request,
  }) => {
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Alice Updated");
    await expect(page.locator(".pe-save-state")).toContainText("Unsaved changes");
    // Nothing is saved in the background.
    await page.waitForTimeout(1500);
    const before = await request.get("http://127.0.0.1:3030/cards/by-handle/owner");
    expect((await before.json()).identity.name).not.toBe("Alice Updated");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.locator(".pe-save-state")).toContainText("All changes saved");
    const saved = await request.get("http://127.0.0.1:3030/cards/by-handle/owner");
    expect((await saved.json()).identity.name).toBe("Alice Updated");
  });

  test("discard reverts unsaved edits without saving them", async ({
    page,
    request,
  }) => {
    await page.goto("/p/owner/edit");
    const name = page.getByLabel("Full name", { exact: true });
    const original = await name.inputValue();
    await name.fill("Accidental edit");
    await page.getByRole("button", { name: "Discard" }).click();
    await expect(name).toHaveValue(original);
    await expect(page.locator(".pe-save-state")).toContainText("All changes saved");
    await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
    const saved = await request.get("http://127.0.0.1:3030/cards/by-handle/owner");
    expect((await saved.json()).identity.name).toBe(original);
  });

  test("asks before leaving with unsaved changes", async ({ page }) => {
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Unsaved Alice");
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.getByRole("link", { name: "Owner home", exact: true }).click();
    await expect(page).toHaveURL(/\/p\/owner\/edit$/);
    await expect(page.getByLabel("Full name", { exact: true })).toHaveValue("Unsaved Alice");
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("link", { name: "Owner home", exact: true }).click();
    await expect(page).toHaveURL(/\/home$/);
  });

  test("failed save keeps the draft", async ({ page }) => {
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
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.locator(".pe-save-state")).toContainText("Not saved");
    await expect(page.getByLabel("Full name", { exact: true })).toHaveValue(
      "Unsaved Alice",
    );
    await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
    await expect(page).toHaveURL(/\/p\/owner\/edit$/);
  });

  test("saving preserves a private card", async ({ page, request }) => {
    await page.goto("/home");
    await page.getByRole("checkbox", { name: /Public card/ }).uncheck();
    await expect(page.getByRole("status").first()).toHaveText("Saved");
    await page.getByRole("link", { name: "Edit your card" }).click();
    await page.getByLabel("Full name", { exact: true }).fill("Private Alice");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.locator(".pe-save-state")).toContainText("All changes saved");
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
    await page.goto("/p/owner/edit");
    await page.getByLabel("Full name", { exact: true }).fill("Recovered Alice");
    await expect(page.locator(".pe-save-state")).toContainText("Unsaved changes");
    page.on("dialog", (dialog) => dialog.accept());
    await page.reload();
    await expect(
      page.getByText("You have unsaved changes from your last visit."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Restore unsaved changes" }).click();
    await expect(page.getByLabel("Full name", { exact: true })).toHaveValue("Recovered Alice");
    await page.getByRole("button", { name: "Save changes" }).click();
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
