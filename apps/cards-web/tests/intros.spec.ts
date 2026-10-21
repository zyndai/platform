import { test, expect, type BrowserContext } from "@playwright/test";

async function signIn(context: BrowserContext) {
  const user = { id: "11111111-1111-4111-8111-111111111111", email: "owner@example.test", aud: "authenticated", role: "authenticated", user_metadata: { name: "Alice Chen" } };
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const token = [Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString("base64url"),
    Buffer.from(JSON.stringify({ sub: user.id, email: user.email, aud: "authenticated", role: "authenticated", exp })).toString("base64url"), "smoke-fixture-signature"].join(".");
  await context.addCookies([{ name: "sb-127-auth-token", value: "base64-" + Buffer.from(JSON.stringify({
    access_token: token, refresh_token: "smoke-refresh", token_type: "bearer", expires_at: exp, expires_in: 3600, user,
  })).toString("base64url"), url: "http://127.0.0.1:3010", sameSite: "Lax" }]);
}

test.describe("S12 human introductions", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ context, request }) => {
    await request.post("http://127.0.0.1:3030/__s12/reset");
    await signIn(context);
  });

  // New profile requests are Cards-native; send/retry coverage lives in network.spec.ts.

  test("accepting without a meeting grant does not offer a call proposal", async ({ page }) => {
    await page.goto("/intros");
    expect(await page.getByRole("heading", { name: "Intro requests", exact: true }).evaluate(element => getComputedStyle(element).webkitTextFillColor)).not.toBe("rgba(0, 0, 0, 0)");
    await expect(page.getByLabel("Allow coordinating a call")).not.toBeChecked();
    await page.getByRole("button", { name: "Accept intro", exact: true }).click();
    await expect(page.getByRole("heading", { name: "From Bob · accepted" })).toBeVisible();
    await expect(page.getByText("Connected. No meeting booked.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Propose time" })).toHaveCount(0);
  });

  test("owner can approve a call and propose a time separately", async ({ page }) => {
    await page.goto("/intros");
    await page.getByLabel("Allow coordinating a call").check();
    await page.getByRole("button", { name: "Accept intro", exact: true }).click();
    await page.getByLabel("Propose a 20-minute call (your local time)").fill(new Date(Date.now() + 86_400_000).toISOString().slice(0, 16));
    await page.getByRole("button", { name: "Propose time", exact: true }).click();
    await expect(page.getByText("Meeting proposed; confirm it in Persona.")).toBeVisible();
    await page.screenshot({ path: "/tmp/zynd-s12-intro-inbox.png", fullPage: true });
  });

  test("unclaimed cards have no connection action", async ({ page }) => {
    await page.goto("/p/unclaimed");
    await expect(page.getByRole("button", { name: "Connect", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Connect", exact: true })).toHaveCount(0);
  });
});
