export type ConnectionStatus = "pending" | "accepted" | "declined" | "blocked" | "revoked";

export interface CardSummary {
  card_id: string;
  handle?: string | null;
  name: string;
  headline?: string;
  avatar_url?: string | null;
}

/** The caller's connection with one other person, as the status and suggestion endpoints report it. */
export interface ConnectionSummary {
  id: string;
  status: ConnectionStatus;
  /** True when the other person asked and the caller is the one who can answer. */
  incoming: boolean;
}

/** A claimed Card matching the typed text (GET /network/people/suggest). Public Card data only. */
export interface PersonSuggestion extends CardSummary {
  connection: ConnectionSummary | null;
}

export type ConnectionStatusResult =
  | { self: true }
  | { self?: false; connection: ConnectionSummary | null; can_connect: boolean; reason: string | null };

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
  sender_kind?: "user" | "agent";
  agent_for_user_id?: string | null;
  reply_to_message_id?: string | null;
  mentions?: string[];
  remembered?: boolean;
  memory_id?: string | null;
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
  /** Only on the owner's pending list (GET /network/groups/{id}/invitations). */
  invitee?: CardSummary | null;
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
  agent_replies?: number;
  agent_reply_users?: string[];
}

export interface CardGroupMemory {
  id: string;
  kind: "summary" | "fact";
  content: string;
  metadata?: Record<string, unknown>;
  source_message_id?: string | null;
  created_at?: string;
  updated_at?: string;
  similarity?: number;
}

export interface CardGroupMemoryList {
  summary: CardGroupMemory | null;
  facts: CardGroupMemory[];
}

export interface CardGroupMemorySearch {
  group_id: string;
  query: string;
  results: CardGroupMemory[];
  error?: string;
}

export interface CardAgentPreference {
  enabled: boolean;
  updated_at?: string | null;
}

export type NetworkConversation =
  | { kind: "dm"; id: string; connection: CardConnection }
  | { kind: "group"; id: string; group: CardGroup };

const API = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

/** Renews the signed-in session and resolves to the new access token, or to null when it cannot. */
type SessionRenewer = () => Promise<string | null>;
let renewSession: SessionRenewer | null = null;

/**
 * The page registers how to renew its session. A 401 means the token in hand has expired (access
 * tokens last about an hour), so the request renews it once and retries with the new token.
 */
export function setSessionRenewer(renewer: SessionRenewer | null) {
  renewSession = renewer;
}

export function cardsNetworkRequest<T>(
  path: string,
  token: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return sendNetworkRequest<T>(path, token, method, body, signal, true);
}

async function sendNetworkRequest<T>(
  path: string,
  token: string,
  method: string,
  body: unknown,
  signal: AbortSignal | undefined,
  canRenew: boolean,
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
  if (response.status === 401 && canRenew && renewSession) {
    const fresh = await renewSession();
    if (fresh) return sendNetworkRequest<T>(path, fresh, method, body, signal, false);
  }
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

export function suggestPeople(token: string, q: string, signal?: AbortSignal): Promise<{ people: PersonSuggestion[] }> {
  const params = new URLSearchParams({ q });
  return cardsNetworkRequest<{ people: PersonSuggestion[] }>(`/people/suggest?${params.toString()}`, token, "GET", undefined, signal);
}

export function fetchConnectionStatus(token: string, handle: string, signal?: AbortSignal): Promise<ConnectionStatusResult> {
  const params = new URLSearchParams({ handle });
  return cardsNetworkRequest<ConnectionStatusResult>(`/connections/status?${params.toString()}`, token, "GET", undefined, signal);
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

export function fetchGroupMemory(
  token: string,
  groupId: string,
  signal?: AbortSignal,
): Promise<CardGroupMemoryList> {
  return cardsNetworkRequest<CardGroupMemoryList>(`/groups/${groupId}/memory`, token, "GET", undefined, signal);
}

export function searchGroupMemory(
  token: string,
  groupId: string,
  query: string,
  signal?: AbortSignal,
): Promise<CardGroupMemorySearch> {
  const params = new URLSearchParams({ q: query });
  return cardsNetworkRequest<CardGroupMemorySearch>(`/groups/${groupId}/memory?${params.toString()}`, token, "GET", undefined, signal);
}

export function rememberGroupMessage(
  token: string,
  groupId: string,
  messageId: string,
): Promise<{ memory: CardGroupMemory; message_id: string }> {
  return cardsNetworkRequest<{ memory: CardGroupMemory; message_id: string }>(
    `/groups/${groupId}/memory`, token, "POST", { message_id: messageId },
  );
}

export function addGroupFact(
  token: string,
  groupId: string,
  content: string,
): Promise<{ memory: CardGroupMemory }> {
  return cardsNetworkRequest<{ memory: CardGroupMemory }>(
    `/groups/${groupId}/memory`, token, "POST", { content },
  );
}

export function fetchAgentPreference(token: string): Promise<CardAgentPreference> {
  return cardsNetworkRequest<CardAgentPreference>("/agent-preferences", token);
}

export function setAgentPreference(token: string, enabled: boolean): Promise<CardAgentPreference> {
  return cardsNetworkRequest<CardAgentPreference>("/agent-preferences", token, "PUT", { enabled });
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

/** How a connection reads to the person looking at it. `closed` is declined, revoked or blocked:
 *  the server keeps one final row per pair, so a new request can never succeed and the UI must not
 *  offer one. (Blocked is kept vague on purpose: it does not say who blocked whom.) */
export type ConnectionState = "none" | "connected" | "requested" | "wants-to-connect" | "closed";

export function connectionState(connection: ConnectionSummary | null | undefined): ConnectionState {
  if (!connection) return "none";
  if (connection.status === "accepted") return "connected";
  if (connection.status === "pending") return connection.incoming ? "wants-to-connect" : "requested";
  return "closed";
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The `?c=` deep link into a conversation: a connection id, or null for anything that is not a UUID
 *  (a repeated param takes the first). Lower-cased so it matches the ids the API returns. */
export function parseConnectionParam(raw: string | string[] | null | undefined): string | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value && UUID.test(value) ? value.toLowerCase() : null;
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
