import { expect, test } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

test.describe("MCP OAuth setup", () => {
  test.beforeEach(async ({ context }) => { await signIn(context); });

  for (const viewport of [{ width: 1280, height: 850 }, { width: 390, height: 844 }]) {
    test(`secret-free setup and independent disconnect at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const requests: string[] = [];
      page.on("request", request => {
        if (request.url().includes("/token/exchange")) requests.push(request.url());
      });
      let rows = [
        { id: "oauth-1", label: "Claude Code", scopes: ["user"], created_at: null, last_used_at: null },
        { id: "legacy-2", label: "Older client", scopes: ["memory:write", "cards:read"], created_at: null, last_used_at: null },
      ];
      let listCalls = 0;
      await page.route("**/me/mcp/clients**", async route => {
        const request = route.request();
        if (request.method() === "DELETE") {
          rows = rows.filter(row => !request.url().endsWith(`/${row.id}`));
          await route.fulfill({ status: 200, json: {} });
        } else {
          listCalls++;
          await route.fulfill({ status: 200, json: { clients: rows } });
        }
      });
      await page.goto("/p/owner/edit");
      const panel = page.locator("#connect-mcp");
      await expect(panel.getByRole("heading", { name: "Connect an assistant" })).toBeVisible();
      await expect(panel.getByText("Full access (memory, card, integrations)")).toBeVisible();
      await expect(panel.getByText("memory:write, cards:read")).toBeVisible();
      expect(listCalls).toBeGreaterThan(0);
      rows.push({ id: "oauth-3", label: "Kilo", scopes: ["user"], created_at: null, last_used_at: null });
      await panel.getByRole("button", { name: "Refresh connected assistants" }).click();
      await expect(panel.getByText("Kilo", { exact: true })).toBeVisible();
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await expect.poll(() => listCalls).toBeGreaterThan(2);
      await expect(panel.locator("pre")).toContainText("claude mcp add");
      await panel.getByRole("combobox", { name: "Client" }).selectOption({ label: "Cursor" });
      const cursorConfig = await panel.locator("pre").innerText();
      expect(JSON.parse(cursorConfig)).toEqual({ mcpServers: { zynd: { url: "http://127.0.0.1:3030/mcp" } } });
      expect(cursorConfig).not.toMatch(/authorization|bearer|token|secret|headers/i);
      await panel.getByRole("combobox", { name: "Client" }).selectOption({ label: "Kilo CLI" });
      expect(JSON.parse(await panel.locator("pre").innerText())).toEqual({ mcp: { zynd: { type: "remote", url: "http://127.0.0.1:3030/mcp" } } });
      await panel.getByRole("combobox", { name: "Client" }).selectOption({ label: "ChatGPT" });
      await expect(panel.locator("pre")).toHaveText("http://127.0.0.1:3030/mcp");
      await panel.getByRole("combobox", { name: "Client" }).selectOption({ label: "Antigravity" });
      await expect(panel.locator("pre")).toHaveCount(0);
      await panel.getByRole("button", { name: "Disconnect", exact: true }).first().click();
      await expect(panel.getByRole("button", { name: "Disconnect", exact: true })).toHaveCount(2);
      await expect(panel.getByText("memory:write, cards:read")).toBeVisible();
      expect(requests).toEqual([]);
    });

    test(`empty and failed inventory at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      let fails = false;
      await page.route("**/me/mcp/clients**", async route => {
        if (fails) await route.fulfill({ status: 503, json: { detail: "Connection inventory unavailable" } });
        else await route.fulfill({ status: 200, json: { clients: [] } });
      });
      await page.goto("/p/owner/edit");
      const panel = page.locator("#connect-mcp");
      await expect(panel.getByText("No assistants connected yet.", { exact: false })).toBeVisible();
      fails = true;
      await panel.getByRole("button", { name: "Refresh connected assistants" }).click();
      await expect(panel.getByRole("alert")).toContainText("Connection inventory unavailable");
      await expect(panel.getByText("No assistants connected yet.", { exact: false })).toHaveCount(0);
      fails = false;
      await panel.getByRole("button", { name: "Refresh connected assistants" }).click();
      await expect(panel.getByText("No assistants connected yet.", { exact: false })).toBeVisible();
      await expect(panel.getByRole("alert")).toHaveCount(0);
    });
  }
});
