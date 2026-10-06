import { CARDS_API } from "@/lib/cards";

export interface McpConnectResult {
  token: string;
  mcp_url: string;
  config_json: string;
  config_http: { mcpServers: Record<string, { url: string; headers: Record<string, string> }> };
  instructions: string[];
}

export interface SuggestedFact {
  predicate: string;
  object: string;
  confidence: number;
}

async function errDetail(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail || `Request failed (${res.status})`;
}

/** Generate (or regenerate) the signed-in user's cards MCP connection. */
export async function connectMcp(supabaseToken: string): Promise<McpConnectResult> {
  const res = await fetch(`${CARDS_API}/cards/mcp/connect`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
  return (await res.json()) as McpConnectResult;
}

/** Revoke every ZYND token for the signed-in user (kills the MCP connection). */
export async function disconnectMcp(supabaseToken: string): Promise<void> {
  const res = await fetch(`${CARDS_API}/cards/mcp/disconnect`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
}

/** Facts reported by the user's coding agents, still private, awaiting review. */
export async function fetchSuggestedFacts(supabaseToken: string): Promise<SuggestedFact[]> {
  const res = await fetch(`${CARDS_API}/cards/mcp/suggestions`, {
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as { suggestions?: SuggestedFact[] };
  return data.suggestions ?? [];
}

/** Publish one suggested fact onto the user's public card. */
export async function approveSuggestedFact(
  supabaseToken: string,
  predicate: string,
  value: string,
): Promise<void> {
  const res = await fetch(`${CARDS_API}/cards/mcp/approve`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ predicate, value }),
  });
  if (!res.ok) throw new Error(await errDetail(res));
}

/** Take one fact off the public card (kept in private memory). */
export async function revokeSuggestedFact(
  supabaseToken: string,
  predicate: string,
  value: string,
): Promise<void> {
  const res = await fetch(`${CARDS_API}/cards/mcp/revoke`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ predicate, value }),
  });
  if (!res.ok) throw new Error(await errDetail(res));
}
