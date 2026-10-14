import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

/**
 * The editor's Memory panel must explain itself and never disagree with itself: every
 * fact shows where it came from, agent-reported facts show the sentence behind them, and
 * the printed count equals what the list can show (it used to print 22 and list 6).
 */
test.describe("owner memory panel", () => {
  test.beforeEach(async ({ context }) => {
    await signIn(context);
  });

  test("count matches the list, with origin and evidence per fact", async ({ page }) => {
    await page.goto("/p/owner/edit");
    const panel = page.locator("section", { hasText: "ZYND Memory" });

    await expect(panel.getByText("8 facts on your public card")).toBeVisible();

    // Collapsed shows 6 of 8 and says so; nothing is silently hidden.
    await expect(panel.locator("[data-fact]")).toHaveCount(6);
    await panel.getByRole("button", { name: "Show all 8" }).click();
    await expect(panel.locator("[data-fact]")).toHaveCount(8);

    // Each fact sits in its own section, and tools / work streams are not under "building".
    for (const label of ["Currently building", "Working on", "Learning", "Expert in", "Tools I use"]) {
      await expect(panel.getByText(label, { exact: true })).toBeVisible();
    }

    // Origin chip and evidence for an agent-reported tool.
    const codex = panel.locator('[data-fact="Codex"]');
    await expect(codex.locator('[data-provenance="agent"]')).toHaveText("Reported by your coding agent");
    await expect(codex.getByText("Because: “The user has a tool: Codex”")).toBeVisible();

    // A fact with no recorded sentence shows its origin but no invented reason.
    const verusa = panel.locator('[data-fact="Verusa"]');
    await expect(verusa.locator('[data-provenance="profile"]')).toHaveText("From your profile import");
    await expect(verusa.getByText("Because:")).toHaveCount(0);

    await panel.getByRole("button", { name: "Show fewer" }).click();
    await expect(panel.locator("[data-fact]")).toHaveCount(6);
  });
});
