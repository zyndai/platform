import type { PersonaHit } from "@/components/chat/types";
import { apiGet, apiPost } from "./api";

export interface PeopleDiscoverResponse {
  status?: string;
  count?: number;
  results?: PersonaHit[];
  source?: "registry" | "local_db" | "none" | string;
  from_cache?: boolean;
  warning?: string;
  error?: string;
}

export interface PeopleMeResponse {
  user_id: string;
  deployed: boolean;
  agent_id?: string | null;
  name?: string | null;
  public_path?: string | null;
}

export interface PeopleIntroductionResponse {
  status: string;
  thread_id: string;
  thread?: { id?: string };
  delivery?: {
    delivered?: boolean;
    transport?: string;
    task_id?: string;
    task_state?: string;
    callback_id?: string;
    error?: string;
    error_code?: string;
    error_reason?: string;
  };
  warning?: string;
}

export function getPeopleMe(): Promise<PeopleMeResponse> {
  return apiGet<PeopleMeResponse>("/api/people/me", { noCache: true });
}

export function discoverPeople(
  query: string,
  limit = 24,
  signal?: AbortSignal,
): Promise<PeopleDiscoverResponse> {
  const params = new URLSearchParams({
    query: query || "persona",
    limit: String(limit),
  });
  return apiGet<PeopleDiscoverResponse>(`/api/people/discover?${params.toString()}`, {
    noCache: true,
    signal,
  });
}

export function sendPeopleIntroduction(input: {
  targetAgentId: string;
  targetName?: string;
  message: string;
}): Promise<PeopleIntroductionResponse> {
  return apiPost<PeopleIntroductionResponse>("/api/people/introductions", {
    target_agent_id: input.targetAgentId,
    target_name: input.targetName || "Network Agent",
    message: input.message,
  });
}
