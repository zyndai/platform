export type ConnectionStatus = "pending" | "accepted" | "declined" | "blocked" | "revoked";

export interface CardSummary {
  card_id: string;
  handle?: string | null;
  name: string;
  headline?: string;
  avatar_url?: string | null;
}

export interface CardConnection {
  id: string;
  status: ConnectionStatus;
  incoming: boolean;
  created_at: string;
  decided_at?: string | null;
  updated_at?: string;
  request_message?: string | null;
  partner: CardSummary;
  thread_id?: string | null;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  last_message_sender_user_id?: string | null;
  unread_count?: number;
}

export interface CardMessage {
  id: string;
  thread_id?: string;
  group_id?: string;
  seq?: number;
  client_id?: string | null;
  sender_user_id: string;
  content: string;
  created_at: string;
  pending?: boolean;
  failed?: boolean;
}

export interface CardGroup {
  id: string;
  name: string;
  description?: string | null;
  owner_user_id: string;
  visibility: "private" | "open";
  my_role?: "owner" | "member";
  created_at: string;
  updated_at: string;
  thread_id?: string | null;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  last_message_sender_user_id?: string | null;
  unread_count?: number;
}

export interface CardGroupMember {
  id: string;
  user_id: string;
  role: "owner" | "member";
  joined_at?: string;
  card?: CardSummary | null;
}

export interface CardGroupInvitation {
  id: string;
  group_id: string;
  invitee_user_id: string;
  inviter_user_id: string;
  status: string;
  message?: string | null;
  created_at: string;
  expires_at: string;
  group?: { id: string; name: string; description?: string | null };
}

export interface CardInbox {
  connections: CardConnection[];
  groups: CardGroup[];
  invitations: CardGroupInvitation[];
  server_time?: string;
}

export interface CardMessagePage {
  thread_id?: string;
  group_id?: string;
  messages: CardMessage[];
  has_more: boolean;
  latest_seq: number;
  peer_last_read_seq?: number;
}

export interface CardMessageResult {
  message: CardMessage;
  duplicate?: boolean;
}

export type NetworkConversation =
  | { kind: "dm"; id: string; connection: CardConnection }
  | { kind: "group"; id: string; group: CardGroup };

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

export async function cardsNetworkRequest<T>(
  path: string,
  token: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API}/cards/network${path}`, {
    method,
    cache: "no-store",
    signal,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let detail = "Cards network request failed";
    try { detail = (await response.json()).detail || detail; } catch { /* fallback */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function messageQuery(limit: number, beforeSeq?: number | null, afterSeq?: number | null): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (beforeSeq != null) params.set("before_seq", String(beforeSeq));
  if (afterSeq != null) params.set("after_seq", String(afterSeq));
  return params.toString();
}

export function fetchInbox(token: string, signal?: AbortSignal): Promise<CardInbox> {
  return cardsNetworkRequest<CardInbox>("/inbox", token, "GET", undefined, signal);
}

export function fetchDmMessages(
  token: string,
  connectionId: string,
  options: { limit?: number; beforeSeq?: number | null; afterSeq?: number | null; signal?: AbortSignal } = {},
): Promise<CardMessagePage> {
  const query = messageQuery(options.limit ?? 40, options.beforeSeq, options.afterSeq);
  return cardsNetworkRequest<CardMessagePage>(`/connections/${connectionId}/messages?${query}`, token, "GET", undefined, options.signal);
}

export function fetchGroupMessages(
  token: string,
  groupId: string,
  options: { limit?: number; beforeSeq?: number | null; afterSeq?: number | null; signal?: AbortSignal } = {},
): Promise<CardMessagePage> {
  const query = messageQuery(options.limit ?? 40, options.beforeSeq, options.afterSeq);
  return cardsNetworkRequest<CardMessagePage>(`/groups/${groupId}/messages?${query}`, token, "GET", undefined, options.signal);
}

export function sendDm(
  token: string,
  connectionId: string,
  content: string,
  clientId: string,
): Promise<CardMessageResult> {
  return cardsNetworkRequest<CardMessageResult>(`/connections/${connectionId}/messages`, token, "POST", {
    content,
    client_id: clientId,
  });
}

export function sendGroupMessage(
  token: string,
  groupId: string,
  content: string,
  clientId: string,
): Promise<CardMessageResult> {
  return cardsNetworkRequest<CardMessageResult>(`/groups/${groupId}/messages`, token, "POST", {
    content,
    client_id: clientId,
  });
}

export function markNetworkRead(
  token: string,
  kind: "dm" | "group",
  id: string,
  seq: number,
): Promise<{ status: string; last_read_seq: number }> {
  return cardsNetworkRequest<{ status: string; last_read_seq: number }>("/read", token, "POST", {
    kind,
    id,
    seq,
  });
}

export function connectionRequestNotice(result: { connection: CardConnection; existing: boolean }): string {
  if (!result.existing) return "Connection request sent";
  const connection = result.connection;
  if (connection.status === "accepted") return "You are already connected";
  if (connection.status === "pending") return connection.incoming
    ? "This Card has already sent you a request. Accept it in your network."
    : "Your connection request is already pending";
  return `This connection is ${connection.status}. No new request was sent.`;
}

/** What each side of an accepted connection is doing now, what they share, and what to bring up
 *  (Cards API GET /network/connections/{id}/brief). */
export interface ConnectionBrief {
  partner: { handle: string; name: string; headline: string };
  now: { you: { text: string }[]; them: { text: string }[] };
  shared: { skills: string[]; industries: string[]; interests: string[]; location: string };
  suggested_topics: string[];
}

/** True when there is nothing worth showing, so the page can skip the panel instead of
 *  rendering empty headings. */
export function briefIsEmpty(brief: ConnectionBrief | null | undefined): boolean {
  if (!brief) return true;
  const { now, shared, suggested_topics } = brief;
  return !(
    now.you.length || now.them.length || suggested_topics.length ||
    shared.skills.length || shared.industries.length || shared.interests.length || shared.location
  );
}

/** One line for the "in common" row: "Python, AI · Pune, India". */
export function sharedSummary(shared: ConnectionBrief["shared"]): string {
  const things = [...shared.skills, ...shared.industries, ...shared.interests];
  return [things.join(", "), shared.location].filter(Boolean).join(" · ");
}
