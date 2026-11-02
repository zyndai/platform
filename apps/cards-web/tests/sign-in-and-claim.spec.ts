import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";

/** Sign-in offers Google, LinkedIn and an email code; anyone signed in can claim an unclaimed card. */

function claimRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/cards/by-handle/unclaimed/claim")) seen.push(req.url());
  });
  return seen;
}

test("the sign-in page offers Google, LinkedIn and an email code", async ({ page }) => {
  await page.goto("/auth?next=%2Fp%2Funclaimed");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with LinkedIn" })).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeVisible();
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect(page.locator(".da-error")).toHaveText("Enter a valid email address.");
});

test("signed out, the claim banner sends people to the sign-in page and back to the card", async ({ page }) => {
  await page.goto("/p/unclaimed");
  await page.getByRole("button", { name: "Sign in to claim" }).click();
  await expect(page).toHaveURL(/\/auth\?next=%2Fp%2Funclaimed$/);
  expect(await page.evaluate(() => sessionStorage.getItem("zynd_claim_intent"))).toBe("unclaimed");
});

test("a signed-in visitor is never claimed just by opening an unclaimed card", async ({ page, context }) => {
  await signIn(context);
  const claims = claimRequests(page);
  await page.goto("/p/unclaimed");
  await expect(page.getByRole("button", { name: "Claim this card" })).toBeVisible();
  await page.waitForTimeout(1000);
  expect(claims).toHaveLength(0);

  await page.getByRole("button", { name: "Claim this card" }).click();
  await expect.poll(() => claims.length).toBe(1);
});

test("returning from a sign-in that started on Claim finishes the claim by itself", async ({ page, context }) => {
  await signIn(context);
  const claims = claimRequests(page);
  await page.addInitScript(() => sessionStorage.setItem("zynd_claim_intent", "unclaimed"));
  await page.goto("/p/unclaimed");
  await expect.poll(() => claims.length).toBe(1);
});
