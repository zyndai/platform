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

/** One contact-database person, shaped by the backend's _shape_person /
 *  _shape_cached (backend/mcp/tools/quickenrich.py) — NOT a PersonaHit: no
 *  agent_id, so no "Say hi" / connection flow, only a LinkedIn link. */
export interface SuggestedPerson {
  name?: string;
  first_name?: string;
  last_name?: string;
  title?: string;
  linkedin_url?: string;
  company_name?: string;
  company_url?: string;
  city?: string;
  locality?: string;
  country?: string;
  has_email?: boolean;
  has_phone?: boolean;
  industry?: string;
  company_size?: string;
}

export interface SuggestedPeopleSection {
  key: string;
  title: string;
  reason?: string;
  items: SuggestedPerson[];
}

export interface PeopleSuggestionsResponse {
  status?: "success" | "empty" | "skipped" | string;
  generated_at?: string | null;
  sections?: SuggestedPeopleSection[];
  can_refresh?: boolean;
  cooldown_seconds?: number;
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

/** The proactive "Similar people" shortlist — contact-database matches
 *  picked from the persona's own profile, grouped by why they matched.
 *  Generated in the background (persona creation, LinkedIn scrape, weekly
 *  refresh); this just reads whatever was last generated. */
export function getPeopleSuggestions(): Promise<PeopleSuggestionsResponse> {
  return apiGet<PeopleSuggestionsResponse>("/api/people/suggestions", { noCache: true });
}

/** Manually regenerate the shortlist now. Rate-limited server-side to once
 *  an hour — a 429 means the cooldown hasn't cleared; its body is JSON
 *  ({detail: "..."}), not plain text, despite apiPost surfacing it via
 *  Error.message. */
export function refreshPeopleSuggestions(): Promise<PeopleSuggestionsResponse> {
  return apiPost<PeopleSuggestionsResponse>("/api/people/suggestions/refresh", {});
}
