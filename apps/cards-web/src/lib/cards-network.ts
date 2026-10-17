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
  request_message?: string | null;
  partner: CardSummary;
}

export interface CardMessage {
  id: string;
  thread_id?: string;
  group_id?: string;
  sender_user_id: string;
  content: string;
  created_at: string;
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
}

export interface CardGroupMember {
  id: string;
  user_id: string;
  role: "owner" | "member";
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

export function connectionRequestNotice(result: { connection: CardConnection; existing: boolean }): string {
  if (!result.existing) return "Connection request sent";
  const connection = result.connection;
  if (connection.status === "accepted") return "You are already connected";
  if (connection.status === "pending") return connection.incoming
    ? "This Card has already sent you a request. Accept it in your network."
    : "Your connection request is already pending";
  return `This connection is ${connection.status}. No new request was sent.`;
}
