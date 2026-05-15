import { apiDelete, apiGet, apiPost, invalidate } from "./api";

export interface InvitableUser {
  user_id: string;
  agent_id?: string | null;
  name: string;
  description?: string;
  avatar_url?: string | null;
}

export interface GroupInvitationBrief {
  id: string;
  slug: string;
  name: string;
  description?: string | null;
  avatar_url?: string | null;
  visibility?: string;
  member_count?: number;
}

export interface GroupInvitation {
  id: string;
  group_id: string;
  group: GroupInvitationBrief;
  invitee_user_id: string;
  invitee_name?: string | null;
  invitee_avatar_url?: string | null;
  inviter_user_id?: string | null;
  inviter_name?: string | null;
  inviter_avatar_url?: string | null;
  invitee_role: "admin" | "member";
  status: "pending" | "accepted" | "declined" | "revoked" | "expired";
  message?: string | null;
  created_at: string;
  decided_at?: string | null;
  expires_at: string;
}

export interface InvitableSearchResponse {
  results: InvitableUser[];
  count: number;
}

export interface InvitationListResponse {
  invitations: GroupInvitation[];
}

export interface InvitationCreateResponse {
  invitation: GroupInvitation | null;
}

export interface InvitationDecideResponse {
  status: "accepted" | "declined" | "already_member";
  group_id: string;
}

const INCOMING_PATH = "/api/groups/invitations/incoming";

export function searchInvitableUsers(
  groupId: string,
  query: string,
  options?: { limit?: number; signal?: AbortSignal },
): Promise<InvitableSearchResponse> {
  const params = new URLSearchParams({ query });
  if (options?.limit) params.set("limit", String(options.limit));
  return apiGet<InvitableSearchResponse>(
    `/api/groups/${groupId}/invitable?${params.toString()}`,
    { noCache: true, signal: options?.signal },
  );
}

export async function createGroupInvitation(
  groupId: string,
  invite: { user_id: string; role?: "member" | "admin"; message?: string | null },
): Promise<InvitationCreateResponse> {
  const res = await apiPost<InvitationCreateResponse>(
    `/api/groups/${groupId}/invitations`,
    invite,
  );
  invalidate(`/api/groups/${groupId}/invitations`);
  invalidate(INCOMING_PATH);
  return res;
}

export function listGroupInvitations(groupId: string): Promise<InvitationListResponse> {
  return apiGet<InvitationListResponse>(`/api/groups/${groupId}/invitations`, {
    noCache: true,
  });
}

export async function revokeGroupInvitation(
  groupId: string,
  invitationId: string,
): Promise<{ status: string }> {
  const res = await apiDelete<{ status: string }>(
    `/api/groups/${groupId}/invitations/${invitationId}`,
  );
  invalidate(`/api/groups/${groupId}/invitations`);
  return res;
}

export function listIncomingInvitations(): Promise<InvitationListResponse> {
  return apiGet<InvitationListResponse>(INCOMING_PATH, { noCache: true });
}

export async function respondToGroupInvitation(
  invitationId: string,
  decision: "accept" | "decline",
): Promise<InvitationDecideResponse> {
  const res = await apiPost<InvitationDecideResponse>(
    `/api/groups/invitations/${invitationId}/respond`,
    { decision },
  );
  invalidate(INCOMING_PATH);
  invalidate("/api/groups");
  return res;
}
