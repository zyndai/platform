import { test, expect, type Page } from "@playwright/test";
import type { CardConnection } from "../src/lib/cards-network";
import { signIn } from "./fixtures/sign-in";
import { mockNetwork, NETWORK_USER } from "./fixtures/network";

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

test("v2 loads avatars through the /api/img proxy and falls back to the initial", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  // Never the raw CDN URL: it expires, and many browsers block the hotlink.
  const bob = page.locator(".nv2-item", { hasText: "Bob" }).locator(".nv2-avatar img");
  await expect(bob).toBeVisible();
  const src = (await bob.getAttribute("src"))!;
  expect(src).toMatch(/^\/api\/img\?/);
  expect(new URL(src, "http://x").searchParams.get("url")).toBe("https://avatars.githubusercontent.com/u/2?v=4");
  expect(new URL(src, "http://x").searchParams.get("handle")).toBe("bob");

  // The photo is a block that covers the whole circle.
  await expect(bob).toHaveCSS("display", "block");
  const photo = (await bob.boundingBox())!;
  const circle = (await bob.locator("..").boundingBox())!;
  expect(photo.width).toBeCloseTo(circle.width, 0);
  expect(photo.height).toBeCloseTo(circle.height, 0);

  // An expired photo (the proxy answers 404) gives way to the initial.
  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Avatar group");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  state.members.push({
    id: "carol-member", user_id: "33333333-3333-4333-8333-333333333334", role: "member",
    card: { card_id: "carol-card", handle: "carol", name: "Carol", avatar_url: "https://media.licdn.com/dms/expired.jpg" },
  });
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Avatar group" }).click();
  const carol = page.locator(".nv2-member-strip .nv2-avatar").filter({ hasText: "C" });
  await expect(carol).toBeVisible();
  await expect(carol.locator("img")).toHaveCount(0);
  expect(state.avatarRequests.some((url) => url.includes("expired.jpg") && url.includes("handle=carol"))).toBe(true);
});

test("v2 puts an assistant reply on its owner's side and renders markdown only for assistants", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  const remoteImages: string[] = [];
  page.on("request", (request) => { if (request.url().includes("tracker.example")) remoteImages.push(request.url()); });
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Assistants");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  const group = state.groups[0];
  const bob = state.people[0];
  state.members.push({ id: "bob-member", user_id: bob.user_id, role: "member", card: bob });
  const at = (offset: number) => new Date(Date.now() - offset * 1000).toISOString();
  state.groupMessages.push(
    {
      id: "human-md", group_id: group.id, seq: ++state.groupSeq, sender_user_id: NETWORK_USER, sender_kind: "user",
      content: "Plan **bold** and\n- not a list\n# not a heading", created_at: at(30),
    },
    {
      id: "bob-agent", group_id: group.id, seq: ++state.groupSeq, sender_user_id: bob.user_id, sender_kind: "agent",
      agent_for_user_id: bob.user_id, content: "Friday works for me.", created_at: at(20),
    },
    {
      id: "own-agent", group_id: group.id, seq: ++state.groupSeq, sender_user_id: NETWORK_USER, sender_kind: "agent",
      agent_for_user_id: NETWORK_USER, created_at: at(10),
      content: "## Summary\n\n- first point\n- second point with `code`\n\nSee [docs](https://example.com/docs), <b>raw html</b> and ![pic](https://tracker.example/pixel.png)",
    },
  );
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Assistants" }).click();
  const messages = page.getByLabel("Group messages", { exact: true });
  await expect(messages).toContainText("Friday works for me.");

  // A human message with markdown-looking text stays plain text.
  const human = messages.locator(".nv2-bubble").filter({ hasText: "Plan **bold**" });
  await expect(human).toContainText("not a list");
  await expect(human.locator("strong, ul, li, h1")).toHaveCount(0);

  // Someone else's assistant: left, owner's photo with a bot badge.
  const bobRow = messages.locator(".nv2-msg-row.is-agent").filter({ hasText: "Friday works for me." });
  await expect(bobRow).not.toHaveClass(/is-mine/);
  await expect(bobRow.locator(".nv2-msg-sender")).toContainText("AI assistant for Bob");
  await expect(bobRow.locator(".nv2-agent-avatar .nv2-agent-badge")).toBeVisible();
  expect(await bobRow.locator(".nv2-agent-avatar img").getAttribute("src")).toMatch(/^\/api\/img\?/);

  // Your own assistant: right, labelled, in its own bubble variant, with markdown.
  const ownRow = messages.locator(".nv2-msg-row.is-agent").filter({ hasText: "Summary" });
  await expect(ownRow).toHaveClass(/is-mine/);
  await expect(ownRow.locator(".nv2-msg-sender")).toHaveText("Your AI assistant");
  await expect(ownRow.locator(".nv2-agent-avatar")).toHaveCount(0);
  const ownBubble = ownRow.locator(".nv2-bubble");
  await expect(ownBubble).toHaveClass(/is-own/);
  await expect(ownBubble.locator("h2")).toHaveText("Summary");
  await expect(ownBubble.locator("li")).toHaveCount(2);
  await expect(ownBubble.locator("li code")).toHaveText("code");
  const link = ownBubble.getByRole("link", { name: "docs" });
  await expect(link).toHaveAttribute("href", "https://example.com/docs");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
  // Raw HTML is shown as text, and a remote image becomes a link to it.
  await expect(ownBubble).toContainText("<b>raw html</b>");
  await expect(ownBubble.locator("b, img")).toHaveCount(0);
  await expect(ownBubble.getByRole("link", { name: "pic" })).toHaveAttribute("href", "https://tracker.example/pixel.png");
  expect(remoteImages).toEqual([]);
  // The reply is not an ordinary human bubble, and it cannot be "remembered".
  await expect(ownBubble).toHaveCSS("background-image", /linear-gradient/);
  await expect(ownRow.getByRole("button", { name: "Save message to group memory" })).toHaveCount(0);

  // Sides, not just classes.
  const area = (await messages.boundingBox())!;
  const own = (await ownBubble.boundingBox())!;
  const theirs = (await bobRow.locator(".nv2-bubble").boundingBox())!;
  expect(own.x + own.width).toBeGreaterThan(area.x + area.width - 60);
  expect(theirs.x).toBeLessThan(area.x + 90);

  // The inbox line says whose assistant spoke last, without markdown syntax.
  const item = page.locator(".nv2-item", { hasText: "Assistants" });
  await expect(item).toContainText("Your AI: Summary");
  await expect(item).not.toContainText("##");
  await expect(item).not.toContainText("`");
  state.groupMessages.push({
    id: "bob-agent-2", group_id: group.id, seq: ++state.groupSeq, sender_user_id: bob.user_id, sender_kind: "agent",
    agent_for_user_id: bob.user_id, content: "**Friday** again", created_at: at(1),
  });
  await page.reload();
  const refreshed = page.locator(".nv2-item", { hasText: "Assistants" });
  await expect(refreshed).toContainText("AI: Friday again");
  await expect(refreshed).not.toContainText("Your AI");
});

test("v2 shows your own assistant thinking on your side", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");

  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Thinking group");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  const bob = state.people[0];
  state.members.push({ id: "bob-member", user_id: bob.user_id, role: "member", card: bob });
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Thinking group" }).click();
  await expect(page.getByText(/2 members/)).toBeVisible();

  await page.getByLabel("Group message", { exact: true }).fill("@alice and @bob compare notes");
  await page.getByRole("button", { name: "Send group message" }).click();

  const mine = page.locator(".nv2-typing-row.is-mine");
  await expect(mine).toContainText("Your AI assistant");
  const theirs = page.locator(".nv2-typing-row:not(.is-mine)");
  await expect(theirs).toContainText("AI assistant for Bob");
  await expect(theirs.locator(".nv2-agent-badge")).toBeVisible();
  const area = (await page.getByLabel("Group messages", { exact: true }).boundingBox())!;
  const mineBox = (await mine.boundingBox())!;
  const theirsBox = (await theirs.boundingBox())!;
  expect(mineBox.x + mineBox.width).toBeGreaterThan(area.x + area.width - 60);
  expect(theirsBox.x).toBeLessThan(area.x + 40);
});

// Realtime is switched off in these runs (no socket on the fake Supabase URL),
// so a broadcast is delivered the way use-network-realtime.ts allows: as a
// window event carrying the topic, event name and payload.
async function broadcast(page: Page, topic: string, event: string, payload: Record<string, unknown>) {
  await page.evaluate((detail) => window.dispatchEvent(new CustomEvent("zynd:test-broadcast", { detail })), { topic, event, payload });
}

const JOB = "30000000-0000-4000-8000-000000000030";

async function openGroupWithBob(page: Page, name: string, state: Awaited<ReturnType<typeof mockNetwork>>) {
  await page.goto("/network?v2=1");
  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  const bob = state.people[0];
  state.members.push({ id: "bob-member", user_id: bob.user_id, role: "member", card: bob });
  await page.reload();
  await page.getByRole("button").filter({ hasText: name }).click();
  await expect(page.getByText(/2 members/)).toBeVisible();
  return { group: state.groups[0], bob, topic: `cards:group:${state.groups[0].id}` };
}

test("v2 streams an assistant reply, keeps its sources, and swaps in the saved message", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  const { group, bob, topic } = await openGroupWithBob(page, "Streaming", state);
  const snapshot = (seq: number, extra: Record<string, unknown>) => ({
    job_id: JOB, group_id: group.id, user_id: bob.user_id, message_id: "trigger-1",
    attempt: 1, seq, text: "", done: false, status: "writing", ...extra,
  });

  await page.getByLabel("Group message", { exact: true }).fill("@bob plan the launch");
  await page.getByRole("button", { name: "Send group message" }).click();
  const thinking = page.locator(".nv2-typing-row:not(.is-mine)");
  await expect(thinking).toContainText("AI assistant for Bob");

  // Nothing written yet: still the "thinking" row, and a tool step says so.
  await broadcast(page, topic, "agent_stream", snapshot(1, { status: "thinking" }));
  await expect(thinking).toBeVisible();
  await broadcast(page, topic, "agent_stream", snapshot(2, { status: "tool" }));
  await expect(thinking).toContainText("Looking things up…");

  // Text arrives: a streaming bubble on Bob's side replaces the thinking row.
  await broadcast(page, topic, "agent_stream", snapshot(3, { text: "Here is the" }));
  const row = page.locator(".nv2-msg-row.is-agent");
  await expect(row).toHaveCount(1);
  await expect(row).not.toHaveClass(/is-mine/);
  await expect(row.locator(".nv2-msg-sender")).toContainText("AI assistant for Bob");
  await expect(row.locator(".nv2-agent-avatar .nv2-agent-badge")).toBeVisible();
  await expect(row.locator(".nv2-bubble")).toHaveClass(/is-streaming/);
  await expect(row.locator(".nv2-bubble")).toContainText("Here is the");
  await expect(row).toContainText("Writing…");
  await expect(thinking).toHaveCount(0);

  // Full-text snapshots: markdown renders as it grows, and the caret rides the last block.
  const plan = "Here is the **plan**:\n\n1. Ship the API\n2. Measure adoption";
  await broadcast(page, topic, "agent_stream", snapshot(4, { text: plan }));
  await expect(row.locator(".nv2-bubble strong")).toHaveText("plan");
  await expect(row.locator(".nv2-bubble ol li")).toHaveCount(2);
  const caret = await row.locator(".nv2-bubble ol li").last().evaluate((li) => getComputedStyle(li, "::after").content);
  expect(caret).toBe('""');

  // A snapshot that arrives late cannot rewind the text.
  await broadcast(page, topic, "agent_stream", snapshot(3, { text: "Here is the" }));
  await expect(row.locator(".nv2-bubble ol li")).toHaveCount(2);

  // No sources unless the server sent them.
  await expect(row.locator(".nv2-sources")).toHaveCount(0);

  // The final snapshot: exact text, plus the dev trace.
  const finalText = `${plan}\n\nDone.`;
  const sources = {
    context: {
      recent_messages: 12,
      summary: { present: true, preview: "The group is shipping on Friday." },
      group_facts: { count: 2, items: ["Alice owns launch", "Staging key is in the vault"] },
      member_facts: { member: "bob", connected: true, count: 1, items: ["is working on: Payments API"] },
    },
    tools: [{ name: "search_group_memory", args: { query: "launch date" }, ok: true, summary: "2 results: Ship on Friday | Alice owns launch" }],
  };
  await broadcast(page, topic, "agent_stream", snapshot(5, { text: finalText, done: true, status: "done", sources }));
  await expect(row).toContainText("Saving…");
  await expect(row.locator(".nv2-bubble")).toContainText("Done.");
  const panel = row.locator(".nv2-sources");
  await expect(panel.locator("summary")).toHaveText("Sources (dev)");
  await expect(panel.locator(".nv2-sources-body")).toBeHidden();
  await panel.locator("summary").click();
  await expect(panel).toContainText("12 recent messages");
  await expect(panel).toContainText("The group is shipping on Friday.");
  await expect(panel).toContainText("Saved group facts: 2");
  await expect(panel).toContainText("Alice owns launch");
  await expect(panel).toContainText("@bob's public memory: 1 facts");
  await expect(panel.locator("code")).toHaveText("search_group_memory");
  await expect(panel).toContainText("query: launch date");
  await expect(panel).toContainText("2 results: Ship on Friday | Alice owns launch");

  // The saved message lands: one bubble, not two, still with its sources.
  const saved = {
    id: "bob-final", group_id: group.id, seq: ++state.groupSeq, client_id: JOB,
    sender_user_id: bob.user_id, sender_kind: "agent", agent_for_user_id: bob.user_id,
    reply_to_message_id: "trigger-1", content: finalText, created_at: new Date().toISOString(),
  };
  state.groupMessages.push(saved as never);
  await broadcast(page, topic, "message", { kind: "group", group_id: group.id, message: saved });
  await broadcast(page, topic, "agent_typing", { job_id: JOB, group_id: group.id, user_id: bob.user_id, status: "done" });
  const messages = page.getByLabel("Group messages", { exact: true });
  await expect(messages.locator(".nv2-bubble.is-agent")).toHaveCount(1);
  await expect(messages.locator(".nv2-bubble.is-streaming")).toHaveCount(0);
  await expect(messages.locator(".nv2-msg-row.is-agent")).not.toContainText("Saving…");
  await expect(messages.locator(".nv2-sources summary")).toHaveText("Sources (dev)");

  // A snapshot that straggles in after the saved message never brings the bubble back.
  await broadcast(page, topic, "agent_stream", snapshot(6, { text: finalText }));
  await expect(messages.locator(".nv2-bubble.is-streaming")).toHaveCount(0);
  await expect(messages.locator(".nv2-bubble.is-agent")).toHaveCount(1);

  // Sources are session memory: they survive leaving the conversation and coming back.
  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Elsewhere");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  await expect(page.locator(".nv2-conv-title")).toContainText("Elsewhere");
  await page.getByRole("button").filter({ hasText: "Streaming" }).first().click();
  await expect(page.locator(".nv2-conv-title")).toContainText("Streaming");
  await expect(messages.locator(".nv2-sources summary")).toHaveText("Sources (dev)");
  await messages.locator(".nv2-sources summary").click();
  await expect(messages.locator(".nv2-sources")).toContainText("query: launch date");

  // ...but not a reload: sources are never persisted.
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Streaming" }).first().click();
  await expect(page.getByLabel("Group messages", { exact: true }).locator(".nv2-bubble.is-agent")).toHaveCount(1);
  await expect(page.locator(".nv2-sources")).toHaveCount(0);
});

test("v2 shows a streamed reply on your own side, restarts a retried job, and clears a failed one", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  const { group, topic } = await openGroupWithBob(page, "Retries", state);
  const snapshot = (attempt: number, seq: number, extra: Record<string, unknown>) => ({
    job_id: JOB, group_id: group.id, user_id: NETWORK_USER, message_id: "trigger-1",
    attempt, seq, text: "", done: false, status: "writing", ...extra,
  });
  const messages = page.getByLabel("Group messages", { exact: true });

  await page.getByLabel("Group message", { exact: true }).fill("@alice summarise this");
  await page.getByRole("button", { name: "Send group message" }).click();
  await expect(page.locator(".nv2-typing-row.is-mine")).toContainText("Your AI assistant");

  await broadcast(page, topic, "agent_stream", snapshot(1, 1, { text: "First attempt, half" }));
  const own = messages.locator(".nv2-msg-row.is-agent.is-mine");
  await expect(own.locator(".nv2-msg-sender")).toHaveText("Your AI assistant");
  await expect(own.locator(".nv2-bubble")).toHaveClass(/is-own/);
  await expect(own.locator(".nv2-bubble")).toContainText("First attempt, half");
  await expect(page.locator(".nv2-typing-row.is-mine")).toHaveCount(0);
  const area = (await messages.boundingBox())!;
  const box = (await own.locator(".nv2-bubble").boundingBox())!;
  expect(box.x + box.width).toBeGreaterThan(area.x + area.width - 60);

  // The job failed and is being retried: what was written is void.
  await broadcast(page, topic, "agent_typing", { job_id: JOB, group_id: group.id, user_id: NETWORK_USER, status: "pending" });
  await expect(own).toHaveCount(0);
  // Attempt 2 restarts from nothing, with a lower seq than attempt 1 reached.
  await broadcast(page, topic, "agent_stream", snapshot(2, 1, { status: "thinking" }));
  await broadcast(page, topic, "agent_stream", snapshot(2, 2, { text: "Second attempt" }));
  await expect(own.locator(".nv2-bubble")).toContainText("Second attempt");
  await expect(own.locator(".nv2-bubble")).not.toContainText("First attempt");

  // The last attempt fails: the bubble goes and the existing error shows.
  await broadcast(page, topic, "agent_typing", { job_id: JOB, group_id: group.id, user_id: NETWORK_USER, status: "failed" });
  await expect(own).toHaveCount(0);
  await expect(page.locator(".nv2-agent-error.is-mine")).toContainText("The assistant couldn't reply");
});

test("v2 follows a streaming reply at the bottom and offers the New messages pill when scrolled up", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");
  await page.getByRole("button", { name: "Create a group" }).click();
  await page.getByLabel("Group name", { exact: true }).fill("Long chat");
  await page.getByRole("button", { name: "Create group", exact: true }).click();
  const group = state.groups[0];
  const bob = state.people[0];
  state.members.push({ id: "bob-member", user_id: bob.user_id, role: "member", card: bob });
  for (let n = 0; n < 40; n += 1) {
    state.groupMessages.push({
      id: `history-${n}`, group_id: group.id, seq: ++state.groupSeq, sender_user_id: bob.user_id, sender_kind: "user",
      content: `Earlier message number ${n}`, created_at: new Date(Date.now() - (60 - n) * 1000).toISOString(),
    });
  }
  await page.reload();
  await page.getByRole("button").filter({ hasText: "Long chat" }).click();
  const topic = `cards:group:${group.id}`;
  const messages = page.getByLabel("Group messages", { exact: true });
  await expect(messages).toContainText("Earlier message number 39");
  const gap = () => messages.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
  const snapshot = (seq: number, text: string) => ({
    job_id: JOB, group_id: group.id, user_id: bob.user_id, message_id: "trigger-1",
    attempt: 1, seq, text, done: false, status: "writing",
  });
  const lines = (count: number) => Array.from({ length: count }, (_, n) => `- point ${n + 1}`).join("\n");

  // At the bottom: the view stays on the newest words as the reply grows tall.
  await expect.poll(gap).toBeLessThan(4);
  await broadcast(page, topic, "agent_stream", snapshot(1, "Plan:\n\n" + lines(6)));
  await broadcast(page, topic, "agent_stream", snapshot(2, "Plan:\n\n" + lines(30)));
  await expect(messages.locator(".nv2-bubble.is-streaming li")).toHaveCount(30);
  await expect.poll(gap).toBeLessThan(4);
  await expect(page.getByRole("button", { name: /New messages/ })).toHaveCount(0);

  // Scrolled up: the view stays put and the pill says there is more.
  // Wait for the scroll event itself: that is what tells the pane the reader left the bottom.
  await messages.evaluate((el) => new Promise<void>((resolve) => {
    el.addEventListener("scroll", () => resolve(), { once: true });
    el.scrollTop = 0;
  }));
  expect(await messages.evaluate((el) => el.scrollTop)).toBe(0);
  await broadcast(page, topic, "agent_stream", snapshot(3, "Plan:\n\n" + lines(34)));
  await expect(messages.locator(".nv2-bubble.is-streaming li")).toHaveCount(34);
  const pill = page.getByRole("button", { name: /New messages/ });
  await expect(pill).toBeVisible();
  expect(await messages.evaluate((el) => el.scrollTop)).toBe(0);
  await pill.click();
  await expect.poll(gap).toBeLessThan(4);
  await expect(pill).toHaveCount(0);
});

test("v2 has no horizontal overflow on a narrow phone", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/network?v2=1");
  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

// ── Start a connection: name-or-handle search ────────────────────────────────

const ACCEPTED_ID = "77777777-7777-4777-8777-777777777777";
const PENDING_OUT_ID = "88888888-8888-4888-8888-888888888888";
const PENDING_IN_ID = "33333333-3333-4333-8333-333333333333";

function connectionWith(handle: string, name: string, overrides: Partial<CardConnection> = {}): CardConnection {
  return {
    id: ACCEPTED_ID, status: "accepted", incoming: false, created_at: new Date().toISOString(),
    partner: { card_id: `${handle}-card`, handle, name },
    thread_id: "99999999-9999-4999-8999-999999999999", last_message_at: null, last_message_preview: null,
    last_message_sender_user_id: null, unread_count: 0, ...overrides,
  };
}

async function openConnectionDialog(page: Page) {
  await page.getByRole("button", { name: "Start a connection" }).click();
  return page.getByRole("combobox", { name: "Card handle" });
}

test("suggestions appear after a debounce, pick a person and send to their handle", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  // typing quickly makes one request, not one per key
  await combo.pressSequentially("dan", { delay: 40 });
  const list = page.getByRole("listbox", { name: "Matching Cards" });
  await expect(list.getByRole("option")).toHaveCount(2);
  expect(state.suggestCalls).toEqual(["dan"]);
  await expect(list.getByRole("option", { name: /Dan Smith/ })).toContainText("@dan · Founder");

  // "dana" ranks level with "dan" (both start with it); step to Dan Smith and choose it
  const names = await list.getByRole("option").allInnerTexts();
  const target = names.findIndex((text) => text.includes("Dan Smith"));
  for (let step = 0; step <= target; step++) await combo.press("ArrowDown");
  await combo.press("Enter");
  // the person is pinned as a chip; the search box is gone
  await expect(page.locator(".nv2-combo-chip")).toContainText("Dan Smith");
  await expect(page.locator(".nv2-combo-chip")).toContainText("@dan");
  await expect(combo).toHaveCount(0);
  await expect(page.getByLabel("Connection note", { exact: true })).toBeFocused();

  await page.getByLabel("Connection note", { exact: true }).fill("Hi Dan");
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection request sent" })).toBeVisible();
  expect(state.connections.at(-1)?.partner.handle).toBe("dan");
  expect(state.connections.at(-1)?.request_message).toBe("Hi Dan");
});

test("the suggestion list is a keyboard-operable combobox", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  await expect(combo).toHaveAttribute("aria-expanded", "false");
  await combo.fill("da");
  const options = page.getByRole("option");
  await expect(options).toHaveCount(2);
  await expect(combo).toHaveAttribute("aria-expanded", "true");
  await expect(combo).toHaveAttribute("aria-autocomplete", "list");
  // nothing is highlighted until you move, so Enter never swaps what you typed for someone else
  await expect(combo).not.toHaveAttribute("aria-activedescendant", /.+/);

  await combo.press("ArrowDown");
  const first = await options.nth(0).getAttribute("id");
  await expect(combo).toHaveAttribute("aria-activedescendant", first!);
  await expect(options.nth(0)).toHaveAttribute("aria-selected", "true");
  await combo.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await expect(options.nth(0)).toHaveAttribute("aria-selected", "false");
  await combo.press("ArrowDown");              // wraps
  await expect(options.nth(0)).toHaveAttribute("aria-selected", "true");
  await combo.press("ArrowUp");                // wraps back
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");

  await combo.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(combo).toHaveAttribute("aria-expanded", "false");
  // Escape closed the list only: the dialog is still there
  await expect(page.getByRole("dialog", { name: "New connection" })).toBeVisible();
});

test("an older, slower answer never replaces the one for what you typed last", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.suggestDelay = { co: 900 };
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  await combo.fill("co");
  await expect.poll(() => state.suggestCalls).toContain("co");
  await combo.fill("cor");
  const options = page.getByRole("option");
  await expect(options).toHaveCount(1);
  await expect(options.first()).toContainText("Cora Connected");
  await page.waitForTimeout(1200);              // the "co" answer (Cora + Colin) has now arrived
  await expect(options).toHaveCount(1);
});

test("people you are already connected with open their DM instead of sending", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionWith("cora", "Cora Connected"));
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  await combo.fill("cora");
  const option = page.getByRole("option", { name: /Cora Connected/ });
  await expect(option).toContainText("Connected");
  await expect(option).toContainText("Message");
  const before = state.connections.length;
  await option.click();

  await expect(page.getByRole("dialog", { name: "New connection" })).toHaveCount(0);
  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();
  expect(state.connections).toHaveLength(before);
});

test("a request you sent, a closed connection and an incoming request are handled, not resent", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(
    connectionWith("colin", "Colin Park", { id: PENDING_OUT_ID, status: "pending", incoming: false, thread_id: null }),
    connectionWith("dana", "Dana Whitfield", { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", status: "declined", incoming: false, thread_id: null }),
  );
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);
  const before = state.connections.length;

  await combo.fill("colin");
  const requested = page.getByRole("option", { name: /Colin Park/ });
  await expect(requested).toContainText("Requested");
  await expect(requested).toHaveAttribute("aria-disabled", "true");
  await requested.click({ force: true });          // aria-disabled: a user can click it, nothing happens
  await expect(page.locator(".nv2-combo-chip")).toHaveCount(0);   // nothing was chosen

  await combo.fill("dana");
  const closed = page.getByRole("option", { name: /Dana Whitfield/ });
  await expect(closed).toContainText("Unavailable");
  await expect(closed).toHaveAttribute("aria-disabled", "true");
  await closed.click({ force: true });
  await expect(page.locator(".nv2-combo-chip")).toHaveCount(0);

  // Bob's request to you is the one that can be answered: it takes you to the Requests tab
  await combo.fill("bob");
  const incoming = page.getByRole("option", { name: /Bob/ });
  await expect(incoming).toContainText("Wants to connect");
  await incoming.click();
  await expect(page.getByRole("dialog", { name: "New connection" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: /Requests/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "Accept connection from Bob" })).toBeVisible();
  expect(state.connections).toHaveLength(before);
});

test("no match and a failed search both explain themselves, and an exact handle still sends", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  await combo.fill("zzz");
  await expect(page.getByText('No Card matches "zzz"')).toBeVisible();

  state.failNextSuggest = true;
  await combo.fill("qqq");
  await expect(page.getByText("Couldn't search right now")).toBeVisible();

  // a single character is below the minimum: no request, no menu
  const calls = state.suggestCalls.length;
  await combo.fill("d");
  await page.waitForTimeout(400);
  expect(state.suggestCalls).toHaveLength(calls);
  await expect(page.locator(".nv2-combo-menu")).toHaveCount(0);

  // whatever the search said, a typed handle goes out as typed
  await combo.fill("erin");
  await page.getByRole("button", { name: "Send request", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connection request sent" })).toBeVisible();
  expect(state.connections.at(-1)?.partner.handle).toBe("erin");
});

test("the person chip can be cleared to search again", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);

  await combo.fill("dana");
  await page.getByRole("option", { name: /Dana Whitfield/ }).click();
  await expect(page.locator(".nv2-combo-chip")).toContainText("Dana Whitfield");
  await page.getByRole("button", { name: "Choose someone else instead of Dana Whitfield" }).click();
  await expect(page.locator(".nv2-combo-chip")).toHaveCount(0);
  const again = page.getByRole("combobox", { name: "Card handle" });
  await expect(again).toBeFocused();
  await expect(again).toHaveValue("");
});

test("the connection dialog fits a narrow phone", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/network?v2=1");
  const combo = await openConnectionDialog(page);
  await combo.fill("dan");
  await expect(page.getByRole("option")).toHaveCount(2);
  const box = await page.locator(".nv2-combo-menu").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

// ── ?c= deep link ────────────────────────────────────────────────────────────

test("?c= opens that accepted conversation once, and drops the param", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionWith("cora", "Cora Connected"));
  await page.goto(`/network?v2=1&c=${ACCEPTED_ID}`);

  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();
  await expect(page.locator(".nv2-main")).toContainText("Cora Connected");
  await expect.poll(() => new URL(page.url()).searchParams.has("c")).toBe(false);
  expect(new URL(page.url()).searchParams.get("v2")).toBe("1");

  // a reload is not pulled back into the conversation
  await page.reload();
  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveCount(0);
});

test("?c= for a pending request opens the Requests tab", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto(`/network?v2=1&c=${PENDING_IN_ID}`);
  await expect(page.getByRole("tab", { name: /Requests/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("button", { name: "Accept connection from Bob" })).toBeVisible();
});

test("?c= that is not yours says so instead of failing silently", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/network?v2=1&c=cccccccc-cccc-4ccc-8ccc-cccccccccccc");
  await expect(page.getByRole("status").filter({ hasText: "That conversation is not available." })).toBeVisible();
  await expect(page.getByLabel("Direct message", { exact: true })).toHaveCount(0);
});

test("?c= that is not a UUID is ignored", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto("/network?v2=1&c=../../etc/passwd");
  await expect(page.getByRole("heading", { name: "Messages" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "not available" })).toHaveCount(0);
});

test("?c= opens the conversation pane on a phone", async ({ page, context }) => {
  await signIn(context);
  const state = await mockNetwork(page);
  state.connections.push(connectionWith("cora", "Cora Connected"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/network?v2=1&c=${ACCEPTED_ID}`);
  await expect(page.locator(".nv2-shell")).toHaveClass(/is-open/);
  await expect(page.getByLabel("Direct message", { exact: true })).toBeVisible();
});

test("signed-out ?c= comes back after sign-in, and a junk one is dropped from the return path", async ({ page }) => {
  await page.goto(`/network?c=${ACCEPTED_ID}`);
  await expect(page).toHaveURL(new RegExp(`/auth\\?next=%2Fnetwork%3Fc%3D${ACCEPTED_ID}$`));
  // the sign-in page reads that same value back untouched
  expect(new URL(page.url()).searchParams.get("next")).toBe(`/network?c=${ACCEPTED_ID}`);

  await page.goto("/network?c=javascript:alert(1)");
  await expect(page).toHaveURL(/\/auth\?next=%2Fnetwork$/);
});

test("the sign-in page keeps a next path with a query, as a same-site cookie value", async ({ page, context }) => {
  const next = `/network?c=${ACCEPTED_ID}`;
  await page.goto(`/auth?next=${encodeURIComponent(next)}`);
  // Starting the LinkedIn flow stores the path before leaving; the callback reads it back
  // (lib/auth/next-cookie.ts, covered by the unit test) and refuses anything off-site.
  await page.getByRole("button", { name: "Sign in with LinkedIn" }).click();
  await expect.poll(async () => (await context.cookies()).find((cookie) => cookie.name === "zynd_next")?.value)
    .toBe(encodeURIComponent(next));
});

test("the legacy inbox ignores ?c= and still loads", async ({ page, context }) => {
  await signIn(context);
  await mockNetwork(page);
  await page.goto(`/network?c=${PENDING_IN_ID}`);
  await expect(page.getByText("Can we discuss Python APIs?")).toBeVisible();
});
