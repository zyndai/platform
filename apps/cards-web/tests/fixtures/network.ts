import type { Page } from "@playwright/test";
import type { CardConnection, CardGroup, CardGroupInvitation, CardGroupMember, CardMessage, CardSummary } from "../../src/lib/cards-network";

export const NETWORK_USER = "11111111-1111-4111-8111-111111111111";
const BOB = "22222222-2222-4222-8222-222222222222";

export async function mockNetwork(page: Page) {
  const state = {
    connections: [{
      id: "33333333-3333-4333-8333-333333333333", status: "pending", incoming: true,
      created_at: new Date().toISOString(), request_message: "Can we discuss Python APIs?",
      partner: { card_id: "bob-card", handle: "bob", name: "Bob" },
    }] as CardConnection[],
    groups: [] as CardGroup[],
    invitations: [] as CardGroupInvitation[],
    messages: [] as CardMessage[],
    groupMessages: [] as CardMessage[],
    members: [] as CardGroupMember[],
    people: [{ card_id: "bob-card", handle: "bob", name: "Bob", user_id: BOB }] as (CardSummary & { user_id: string })[],
    sentInvitations: [] as string[],
    failNextRequest: false,
    failNextMessage: false,
  };
  await page.route("**/cards/network/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/cards/network", "");
    const post = request.method() === "POST";
    const body = post ? request.postDataJSON() : {};
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/connections") {
      if (!post) return json({ connections: state.connections });
      if (state.failNextRequest) { state.failNextRequest = false; return json({ detail: "Temporarily unavailable" }, 503); }
      const existing = state.connections.find(row => row.partner.handle === body.target_handle);
      if (existing) return json({ connection: existing, existing: true });
      const connection: CardConnection = {
        id: "44444444-4444-4444-8444-444444444444", status: "pending", incoming: false,
        partner: { card_id: "claimed-card", handle: body.target_handle, name: "Dan" },
        request_message: body.message, created_at: new Date().toISOString(),
      };
      state.connections.push(connection);
      return json({ connection, existing: false });
    }
    if (path.match(/^\/connections\/[^/]+\/respond$/)) {
      const connection = state.connections.find(row => row.id === path.split("/")[2])!;
      connection.status = body.action === "accept" ? "accepted" : "declined";
      return json({ connection });
    }
    if (path.match(/^\/connections\/[^/]+\/messages$/)) {
      if (post) {
        if (state.failNextMessage) { state.failNextMessage = false; return json({ detail: "Message failed" }, 503); }
        const message = { id: `dm-${state.messages.length}`, sender_user_id: NETWORK_USER, content: body.content, created_at: new Date().toISOString() };
        state.messages.push(message);
        return json({ message });
      }
      return json({ messages: state.messages });
    }
    if (path === "/groups") {
      if (!post) return json({ groups: state.groups });
      const group: CardGroup = { id: "55555555-5555-4555-8555-555555555555", name: body.name, description: body.description, owner_user_id: NETWORK_USER, my_role: "owner", visibility: "private", created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
      state.groups.push(group);
      state.members.push({ id: "owner-member", user_id: NETWORK_USER, role: "owner", card: { card_id: "owner-card", name: "Alice" } });
      return json({ group });
    }
    if (path === "/group-invitations") return json({ invitations: state.invitations });
    if (path.match(/^\/group-invitations\/[^/]+\/respond$/)) {
      const invitation = state.invitations.find(row => row.id === path.split("/")[2])!;
      state.invitations = state.invitations.filter(row => row.id !== invitation.id);
      if (body.decision === "accept") {
        state.groups.push({ id: invitation.group_id, name: invitation.group!.name, owner_user_id: BOB, my_role: "member", visibility: "private", created_at: new Date().toISOString(), updated_at: new Date().toISOString() });
      }
      return json({ status: body.decision === "accept" ? "accepted" : "declined", group_id: invitation.group_id });
    }
    if (path.endsWith("/members")) return json({ members: state.members });
    if (path.endsWith("/people")) return json({ people: state.people });
    if (path.endsWith("/invitations") && post) {
      state.sentInvitations.push(body.target_handle);
      return json({ invitation: { id: "outgoing-invite" } });
    }
    if (path.match(/^\/groups\/[^/]+\/messages$/)) {
      if (post) {
        const message = { id: `group-${state.groupMessages.length}`, sender_user_id: NETWORK_USER, content: body.content, created_at: new Date().toISOString() };
        state.groupMessages.push(message);
        return json({ message });
      }
      return json({ messages: state.groupMessages });
    }
    return json({ detail: "Unhandled fixture route" }, 404);
  });
  return state;
}
