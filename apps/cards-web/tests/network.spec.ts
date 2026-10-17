import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";
import { mockNetwork } from "./fixtures/network";

test("signed-out network preserves the sign-in return path", async ({ page }) => {
  await page.goto("/network");
  await expect(page).toHaveURL(/\/auth\?next=(%2F|\/)network/);
});

test("profile request preserves a failed note and reports duplicate state honestly", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.failNextRequest = true;
  await page.goto("/p/claimed");
  await page.getByRole("button", { name: "Request connection", exact: true }).click();
  await page.getByLabel("Connection note").fill("Can we discuss APIs?");
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.locator(".intro-request").getByRole("alert")).toHaveText("Temporarily unavailable");
  await expect(page.getByLabel("Connection note")).toHaveValue("Can we discuss APIs?");
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.locator(".intro-request")).toContainText("Connection request sent");
  expect(state.connections.at(-1)?.request_message).toBe("Can we discuss APIs?");
  state.connections.at(-1)!.status = "accepted";
  await page.reload();
  await page.getByRole("button", { name: "Request connection", exact: true }).click();
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.locator(".intro-request")).toContainText("You are already connected");
});

test("accepting a selected request enables DMs and new replies appear without reload", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network");
  await expect(page.getByText("Can we discuss Python APIs?")).toBeVisible();
  await page.getByRole("button", { name: /Bob @bob pending/ }).click();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Accept connection from Bob" }).click();
  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();
  state.failNextMessage = true;
  await page.getByLabel("Direct message", { exact: true }).fill("Hello Bob");
  await page.getByRole("button", { name: "Send direct message" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Message failed" })).toBeVisible();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveValue("Hello Bob");
  await page.getByRole("button", { name: "Send direct message" }).click();
  await expect(page.getByLabel("Direct messages", { exact: true })).toContainText("Hello Bob");
  state.messages.push({ id: "reply", sender_user_id: "bob", content: "Hello Alice", created_at: new Date().toISOString() });
  await expect(page.getByLabel("Direct messages", { exact: true })).toContainText("Hello Alice", { timeout: 10_000 });
  state.connections[0].status = "revoked";
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveCount(0, { timeout: 10_000 });
});

test("group creation, invitations and messages stay in Cards", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network");
  await page.getByRole("button", { name: "Groups", exact: true }).click();
  await page.getByLabel("Group name", { exact: true }).fill("API builders");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  await page.getByRole("button", { name: /API builders owner/ }).click();
  await page.getByRole("button", { name: "Search people to invite" }).click();
  await page.getByRole("button", { name: "Invite", exact: true }).click();
  expect(state.sentInvitations).toEqual(["bob"]);
  expect(state.members).toHaveLength(1); // An invitation is not membership.
  await page.getByLabel("Group message", { exact: true }).fill("Welcome, builders");
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("Welcome, builders");
  state.groupMessages.push({ id: "group-reply", sender_user_id: "bob", content: "Thanks for inviting me", created_at: new Date().toISOString() });
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("Thanks for inviting me", { timeout: 10_000 });
});

test("incoming group invitations refresh with a name and members cannot invite", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network");
  await page.getByRole("button", { name: "Groups", exact: true }).click();
  state.invitations.push({ id: "incoming", group_id: "another-group", invitee_user_id: "alice", inviter_user_id: "bob", status: "pending", created_at: new Date().toISOString(), expires_at: new Date(Date.now() + 86400000).toISOString(), group: { id: "another-group", name: "Bob's group" } });
  await page.getByRole("button", { name: "Accept invitation to Bob's group" }).click({ timeout: 10_000 });
  await page.getByRole("button", { name: /Bob's group member/ }).click();
  await expect(page.getByLabel("Group message", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Search people to invite" })).toHaveCount(0);
});

test("network has no horizontal overflow on a narrow phone", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/network");
  await expect(page.getByRole("heading", { name: "Your connections." })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
