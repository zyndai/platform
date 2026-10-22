import { expect, test } from "@playwright/test";

// Anthropic's directory links to this page as the plugin's public documentation, so it must
// render for a signed-out visitor and keep describing the same six tools the server exposes.
const TOOLS = [
  "recall_memories",
  "propose_memory",
  "get_proposal_status",
  "list_pending_facts",
  "propose_card_fact",
  "get_public_card",
];

test("Claude connector page is public and documents the connector", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/claude");
  await expect(page).toHaveURL(/\/claude$/);
  await expect(page.getByRole("heading", { level: 1, name: "Zynd for Claude" })).toBeVisible();
  await expect(page.getByText("https://api.zynd.ai/claude/mcp").first()).toBeVisible();
  for (const tool of TOOLS) await expect(page.getByText(tool, { exact: true })).toBeVisible();
  await expect(page.getByText("Add custom connector")).toBeVisible();
  await expect(page.getByText("Proposals expire after 24 hours", { exact: false })).toBeVisible();
  for (const [name, href] of [["Support", "/support"], ["Privacy Policy", "/privacy"], ["Terms of Service", "/terms"]]) {
    await expect(page.getByRole("link", { name }).first()).toHaveAttribute("href", href);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("the review page no longer tells Claude users to go back to ChatGPT", async ({ page }) => {
  await page.goto("/review/proposal-1");
  await expect(page.getByText("connected to your AI assistant")).toBeVisible();
  await expect(page.getByText("ChatGPT")).toHaveCount(0);
});
