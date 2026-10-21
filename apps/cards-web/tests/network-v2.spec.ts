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

test("v2 reuses the cached conversation instead of reloading it", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Cache one");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  await page.getByLabel("Group message", { exact: true }).fill("cache one message");
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("cache one message");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Cache two");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  await page.getByLabel("Group message", { exact: true }).fill("cache two message");
  await page.getByRole("button", { name: "Send group message" }).click();

  const firstGroup = state.groups.find((group) => group.name === "Cache one")!;
  const before = state.messageCalls.filter((url) => url.includes(firstGroup.id)).length;
  await page.getByRole("button").filter({ hasText: "Cache one" }).click();
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("cache one message");
  await expect(page.getByLabel("Group messages", { exact: true })).not.toContainText("Loading");
  const after = state.messageCalls.filter((url) => url.includes(firstGroup.id));
  expect(after.length).toBeGreaterThan(before);
  expect(after.at(-1)).toContain("after_seq=1");
});

test("v2 remembers a message in the accent colour and shows group memory", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Memory group");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  const group = state.groups[0];
  const bob = state.people[0];
  state.members.push({ id: "bob-member", user_id: bob.user_id, role: "member", card: bob });
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Memory group" }).click();
  await expect(page.getByText(/2 members/)).toBeVisible();

  await page.getByLabel("Group message", { exact: true }).fill("@");
  await expect(page.getByRole("listbox", { name: "Tag a group member" })).toBeVisible();
  await expect(page.getByRole("option", { name: /Bob/ })).toBeVisible();
  await page.getByRole("option", { name: /Bob/ }).click();
  await expect(page.getByLabel("Group message", { exact: true })).toHaveValue("@bob ");
  await page.getByLabel("Group message", { exact: true }).fill("@bob can you review this?");
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.getByText("AI assistant for Bob")).toBeVisible();

  await page.getByLabel("Group message", { exact: true }).fill("Remember: ship Friday");
  await expect(page.getByText("This message will be saved to group memory")).toBeVisible();
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.getByText("Saved to memory")).toBeVisible();
  await expect(page.locator(".nv2-bubble.is-remembered")).toContainText("Remember: ship Friday");

  await page.getByRole("button", { name: "Group memory", exact: true }).click();
  await expect(page.locator(".nv2-memory-panel")).toContainText("Remember: ship Friday");

  state.groupMessages.push({
    id: "agent-message",
    group_id: group.id,
    seq: ++state.groupSeq,
    sender_user_id: bob.user_id,
    sender_kind: "agent",
    agent_for_user_id: bob.user_id,
    content: "Friday works for me.",
    created_at: new Date().toISOString(),
  });
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Memory group" }).click();
  await expect(page.getByText("AI assistant for Bob")).toBeVisible();
  await expect(page.getByLabel("Group messages", { exact: true })).toContainText("Friday works for me.");
});

test("v2 has no horizontal overflow on a narrow phone", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/network?v2=1");
  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
