import { expect, test } from "@playwright/test";
import { LINK_PLACEHOLDER } from "./fixtures/create";
import { signIn } from "./fixtures/sign-in";

test("profile metadata, evidence and live booking use supported public data", async ({ page, request }) => {
  await page.route("https://calendly.com/**", route => route.fulfill({ contentType: "text/html", body: "Fixture booking page" }));
  await page.goto("/p/audit");
  await expect(page.getByLabel("Current broadcast beacon")).toBeVisible();
  await expect(page.getByRole("button", { name: "View evidence for general" })).toHaveCount(0);
  await page.getByRole("button", { name: "View evidence for TypeScript" }).click();
  await expect(page.getByRole("link", { name: "alice/typescript-tool" })).toHaveAttribute("href", "https://github.com/alice/typescript-tool");
  await expect(page.getByRole("region", { name: "TypeScript evidence" })).toHaveCSS("color", "rgb(15, 23, 42)");
  const metadata = await page.locator('script[type="application/ld+json"]').first().textContent();
  expect(JSON.parse(metadata!).mainEntity.knowsAbout).toEqual(["TypeScript"]);
  const entity = await (await request.get("/p/audit/data.json")).json();
  expect(entity.knowsAbout).toEqual(["TypeScript"]);
  expect(entity["zynd:beacon"].text).toContain("early builders");
  await page.getByRole("button", { name: "View live availability" }).click();
  await expect(page.getByRole("dialog", { name: "Book a call with Alice" })).toBeVisible();
  await expect(page.getByTitle("Live booking availability for Alice")).toBeVisible();
  await page.getByRole("button", { name: "Close booking" }).click();
  await page.screenshot({ path: "/tmp/zynd-beta-profile-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Current broadcast beacon")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/zynd-beta-profile-mobile.png", fullPage: true });
});

test("expired beacons disappear from profile and entity metadata", async ({ page, request }) => {
  await page.goto("/p/audit-expired");
  await expect(page.getByLabel("Current broadcast beacon")).toHaveCount(0);
  const entity = await (await request.get("/p/audit-expired/data.json")).json();
  expect(entity["zynd:beacon"]).toBeUndefined();
});

test("owner can publish, renew and dismiss a seven-day beacon", async ({ page, context, request }) => {
  await request.get("http://127.0.0.1:3030/__s10/reset");
  await signIn(context);
  await request.post("http://127.0.0.1:3030/__feed/reset");
  await page.goto("/p/owner/edit#beacon");
  // The edit page shows a summary and opens the same composer as the feed's Post button.
  await page.getByRole("button", { name: "Post an ask" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "Looking for early users" }).check();
  await dialog.getByRole("textbox", { name: "Your ask" }).fill("Seeking a design partner for my developer tool");
  await dialog.getByRole("button", { name: "Post", exact: true }).click();
  await expect(page.getByText("Your ask is live for 7 days.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("group", { name: "Your live ask" })).toContainText("Seeking a design partner for my developer tool");
  await expect(page.getByRole("group", { name: "Your live ask" })).toContainText("Looking for early users");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/zynd-beta-editor-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Edit your ask" }).click();
  await expect(dialog.getByText("Posting this replaces your current ask.")).toBeVisible();
  await dialog.getByRole("button", { name: "Take it down" }).click();
  await dialog.getByRole("button", { name: "Yes, take it down" }).click();
  await expect(page.getByText("Your ask is down.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Post an ask" })).toBeVisible();
});

test("expired onboarding job gives an actionable error and keeps inputs", async ({ page }) => {
  await page.route("http://127.0.0.1:3030/onboard/start", route => route.fulfill({ json: { job_id: "expired-build" } }));
  await page.route("http://127.0.0.1:3030/onboard/expired-build", route => route.fulfill({ status: 404, json: { detail: "job not found" } }));
  await page.route("http://127.0.0.1:3030/onboard/expired-build/cancel", route => route.fulfill({ json: { cancelled: false } }));
  await page.goto("/create");
  const input = page.getByPlaceholder(LINK_PLACEHOLDER);
  await input.fill("github.com/example-user");
  await input.press("Enter");
  await expect(page.getByText("This build expired or the server restarted. Your inputs are kept; please retry.")).toBeVisible();
  await expect(page.locator(".cr-source", { hasText: "github.com/example-user" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
});
