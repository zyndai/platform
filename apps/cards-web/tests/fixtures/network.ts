import type { Page } from "@playwright/test";
import type { CardConnection, CardGroup, CardGroupInvitation, CardGroupMember, CardMessage, CardSummary } from "../../src/lib/cards-network";

export const NETWORK_USER = "11111111-1111-4111-8111-111111111111";
const BOB = "22222222-2222-4222-8222-222222222222";
const DM_THREAD = "66666666-6666-4666-8666-666666666666";
const GROUP_ID = "55555555-5555-4555-8555-555555555555";

export async function mockNetwork(page: Page) {
  const state = {
    connections: [{
      id: "33333333-3333-4333-8333-333333333333", status: "pending", incoming: true,
      created_at: new Date().toISOString(), request_message: "Can we discuss Python APIs?",
      partner: { card_id: "bob-card", handle: "bob", name: "Bob" },
      thread_id: null, last_message_at: null, last_message_preview: null,
      last_message_sender_user_id: null, unread_count: 0,
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
    dmSeq: 0,
    groupSeq: 0,
  };

  const lastDm = (connection: CardConnection) => {
    const rows = state.messages.filter((message) => message.thread_id === connection.thread_id);
    return rows[rows.length - 1];
  };
  const lastGroup = (group: CardGroup) => {
    const rows = state.groupMessages.filter((message) => message.group_id === group.id);
    return rows[rows.length - 1];
  };
  const decorateConnection = (connection: CardConnection): CardConnection => {
    const last = lastDm(connection);
    return {
      ...connection,
      last_message_at: last?.created_at ?? null,
      last_message_preview: last?.content ?? null,
      last_message_sender_user_id: last?.sender_user_id ?? null,
    };
  };
  const decorateGroup = (group: CardGroup): CardGroup => {
    const last = lastGroup(group);
    return {
      ...group,
      last_message_at: last?.created_at ?? null,
      last_message_preview: last?.content ?? null,
      last_message_sender_user_id: last?.sender_user_id ?? null,
    };
  };

  await page.route("**/cards/network/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/cards/network", "");
    const post = request.method() === "POST";
    const body = post ? request.postDataJSON() : {};
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });

    if (path === "/inbox") {
      return json({
        connections: state.connections.map(decorateConnection),
        groups: state.groups.map(decorateGroup),
        invitations: state.invitations,
        server_time: new Date().toISOString(),
      });
    }

    if (path === "/connections") {
      if (!post) return json({ connections: state.connections.map(decorateConnection) });
      if (state.failNextRequest) { state.failNextRequest = false; return json({ detail: "Temporarily unavailable" }, 503); }
      const existing = state.connections.find(row => row.partner.handle === body.target_handle);
      if (existing) return json({ connection: existing, existing: true });
      const connection: CardConnection = {
        id: "44444444-4444-4444-8444-444444444444", status: "pending", incoming: false,
        partner: { card_id: "claimed-card", handle: body.target_handle, name: "Dan" },
        request_message: body.message, created_at: new Date().toISOString(),
        thread_id: null, unread_count: 0,
      };
      state.connections.push(connection);
      return json({ connection, existing: false });
    }

    if (path.match(/^\/connections\/[^/]+\/respond$/)) {
      const connection = state.connections.find(row => row.id === path.split("/")[2])!;
      connection.status = body.action === "accept" ? "accepted" : "declined";
      if (body.action === "accept") {
        connection.thread_id = DM_THREAD;
        connection.unread_count = 0;
      }
      return json({ connection });
    }

    if (path.match(/^\/connections\/[^/]+\/messages$/)) {
      const connection = state.connections.find(row => row.id === path.split("/")[2])!;
      connection.thread_id ??= DM_THREAD;
      if (post) {
        if (state.failNextMessage) { state.failNextMessage = false; return json({ detail: "Message failed" }, 503); }
        const existing = body.client_id
          ? state.messages.find(message => message.client_id === body.client_id)
          : undefined;
        if (existing) return json({ message: existing, duplicate: true });
        const message: CardMessage = {
          id: body.client_id || `dm-${state.dmSeq + 1}`,
          client_id: body.client_id ?? null,
          thread_id: connection.thread_id,
          seq: ++state.dmSeq,
          sender_user_id: NETWORK_USER,
          content: body.content,
          created_at: new Date().toISOString(),
        };
        state.messages.push(message);
        return json({ message, duplicate: false });
      }
      const before = urlNumber(request.url(), "before_seq");
      const after = urlNumber(request.url(), "after_seq");
      const limit = urlNumber(request.url(), "limit") ?? 40;
      // Legacy fixtures push replies without a thread_id; keep them visible so
      // the old /network tests still exercise the polling UI.
      let rows = state.messages.filter(message => !message.thread_id || message.thread_id === connection.thread_id);
      if (before != null) rows = rows.filter(message => (message.seq ?? 0) < before);
      if (after != null) rows = rows.filter(message => (message.seq ?? 0) > after);
      rows = rows.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
      const hasMore = rows.length > limit;
      rows = hasMore ? rows.slice(-limit) : rows;
      return json({ thread_id: connection.thread_id, messages: rows, has_more: hasMore, latest_seq: state.dmSeq });
    }

    if (path === "/groups") {
      if (!post) return json({ groups: state.groups.map(decorateGroup) });
      const group: CardGroup = {
        id: GROUP_ID, name: body.name, description: body.description, owner_user_id: NETWORK_USER,
        my_role: "owner", visibility: "private", created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        unread_count: 0,
      };
      state.groups.push(group);
      state.members.push({ id: "owner-member", user_id: NETWORK_USER, role: "owner", card: { card_id: "owner-card", name: "Alice" } });
      return json({ group });
    }

    if (path === "/group-invitations") return json({ invitations: state.invitations });

    if (path.match(/^\/group-invitations\/[^/]+\/respond$/)) {
      const invitation = state.invitations.find(row => row.id === path.split("/")[2])!;
      state.invitations = state.invitations.filter(row => row.id !== invitation.id);
      if (body.decision === "accept") {
        state.groups.push({
          id: invitation.group_id, name: invitation.group!.name, owner_user_id: BOB,
          my_role: "member", visibility: "private", created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(), unread_count: 0,
        });
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
      const groupId = path.split("/")[2];
      if (post) {
        if (state.failNextMessage) { state.failNextMessage = false; return json({ detail: "Message failed" }, 503); }
        const existing = body.client_id
          ? state.groupMessages.find(message => message.client_id === body.client_id)
          : undefined;
        if (existing) return json({ message: existing, duplicate: true });
        const message: CardMessage = {
          id: body.client_id || `group-${state.groupSeq + 1}`,
          client_id: body.client_id ?? null,
          group_id: groupId,
          seq: ++state.groupSeq,
          sender_user_id: NETWORK_USER,
          content: body.content,
          created_at: new Date().toISOString(),
        };
        state.groupMessages.push(message);
        return json({ message, duplicate: false });
      }
      const before = urlNumber(request.url(), "before_seq");
      const after = urlNumber(request.url(), "after_seq");
      const limit = urlNumber(request.url(), "limit") ?? 40;
      let rows = state.groupMessages.filter(message => !message.group_id || message.group_id === groupId);
      if (before != null) rows = rows.filter(message => (message.seq ?? 0) < before);
      if (after != null) rows = rows.filter(message => (message.seq ?? 0) > after);
      rows = rows.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
      const hasMore = rows.length > limit;
      rows = hasMore ? rows.slice(-limit) : rows;
      return json({ group_id: groupId, messages: rows, has_more: hasMore, latest_seq: state.groupSeq });
    }

    if (path === "/read") {
      if (body.kind === "dm") {
        const connection = state.connections.find(row => row.id === body.id);
        if (connection) connection.unread_count = 0;
      } else {
        const group = state.groups.find(row => row.id === body.id);
        if (group) group.unread_count = 0;
      }
      return json({ status: "ok", last_read_seq: body.seq });
    }

    return json({ detail: "Unhandled fixture route" }, 404);
  });
  return state;
}

function urlNumber(url: string, key: string): number | null {
  const raw = new URL(url).searchParams.get(key);
  return raw == null ? null : Number(raw);
}
