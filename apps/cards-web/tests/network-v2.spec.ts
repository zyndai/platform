import { test, expect } from "@playwright/test";
import { signIn } from "./fixtures/sign-in";
import { mockNetwork } from "./fixtures/network";

test("v2 accepts a request and sends an optimistic DM with retry", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  await expect(page.getByText("Can we discuss Python APIs?")).toBeVisible();
  await page.getByRole("button", { name: "Accept connection from Bob" }).click();
  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();

  state.failNextMessage = true;
  await page.getByLabel("Direct message", { exact: true }).fill("Hello Bob");
  await page.getByRole("button", { name: "Send direct message" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Message failed" })).toBeVisible();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveValue("Hello Bob");

  await page.getByRole("button", { name: "Send direct message" }).click();
  await expect(page.getByLabel("Direct messages", { exact: true })).toContainText("Hello Bob");
  expect(state.messages.at(-1)?.content).toBe("Hello Bob");
  expect(state.messages.at(-1)?.client_id).toBeTruthy();
});

test("v2 sends a connection request from the inbox", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Start a connection" }).click();
  await page.getByLabel("Card handle", { exact: true }).fill("dan");
  await page.getByLabel("Connection note", { exact: true }).fill("Let's connect");
  await page.getByRole("button", { name: "Send request", exact: true }).click();

  await expect(page.getByRole("status").filter({ hasText: "Connection request sent" })).toBeVisible();
  expect(state.connections.at(-1)?.partner.handle).toBe("dan");
});

test("v2 creates a group, invites a connection and sends a group message", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("API builders");
  await page.getByLabel("Group description", { exact: true }).fill("People building APIs");
  await page.getByRole("button", { name: "Create group", exact: true }).click();

  await expect(page.getByLabel("Group message", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Invite people to group" }).click();
  await page.getByRole("button", { name: "Search people to invite" }).click();
  await page.getByRole("button", { name: "Invite", exact: true }).click();
  expect(state.sentInvitations).toEqual(["bob"]);

  await page.getByLabel("Group message", { exact: true }).fill("Welcome, builders");
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("Welcome, builders");
  expect(state.groupMessages.at(-1)?.seq).toBe(1);
});

test("v2 has no horizontal overflow on a narrow phone", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/network?v2=1");
  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
