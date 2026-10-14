import { expect, test } from "@playwright/test";

/**
 * A venture, a current work stream and a tool must each get their own group in the
 * public memory tile. Before this, work streams were folded into "Currently building"
 * and a tool could only appear as "Expert in".
 */
test("venture, work stream and tool render in separate memory groups", async ({ page }) => {
  await page.goto("/p/memorycard");

  // Scope to the memory tile: "Working on" also appears in an unrelated static section.
  const tile = page.locator(".pf-social-card").filter({ hasText: "MEMORY FACTS" });
  await expect(tile).toBeVisible();
  await expect(tile.getByText("4 MEMORY FACTS")).toBeVisible();

  // The tile shows three groups until expanded; four groups exist here.
  await tile.getByRole("button", { name: /See all/ }).click();

  for (const label of ["Currently building", "Working on", "Expert in", "Tools I use"]) {
    await expect(tile.getByText(label, { exact: true })).toBeVisible();
  }

  // Each fact sits in its own group: Verusa is building, outreach is work, Codex is a tool.
  const groupOf = async (fact: string) =>
    tile.locator("div", { has: page.getByText(fact, { exact: true }) })
      .filter({ has: page.locator("span", { hasText: /^▼$/ }) })
      .last()
      .textContent();
  expect(await groupOf("Verusa")).toContain("Currently building");
  expect(await groupOf("Verusa")).not.toContain("LinkedIn outreach");
  expect(await groupOf("LinkedIn outreach")).toContain("Working on");
  expect(await groupOf("LinkedIn outreach")).not.toContain("Currently building");
  expect(await groupOf("Codex")).toContain("Tools I use");
  expect(await groupOf("Codex")).not.toContain("Expert in");

  // Order: building, working on, expertise, tools (textContent ignores CSS uppercase).
  const text = (await tile.textContent()) ?? "";
  const order = ["Currently building", "Working on", "Expert in", "Tools I use"].map((l) => text.indexOf(l));
  expect(order.every((i) => i >= 0)).toBe(true);
  expect([...order].sort((a, b) => a - b)).toEqual(order);
});
