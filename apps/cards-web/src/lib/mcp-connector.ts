import { CARDS_API } from "@/lib/cards";
import { MEMORY_API } from "@/lib/memory";

export interface McpConnectResult {
  token: string;
  mcp_url: string;
  config_json: string;
  config_http: { mcpServers: Record<string, { url: string; headers: Record<string, string> }> };
  instructions: string[];
  client_id?: string;
  label?: string;
  scopes?: string[];
  cursor?: string;
  claude_code?: string;
  server_url?: string;
}

export interface McpClientRow {
  id: string;
  label: string;
  scopes: string[];
  created_at: string | null;
  last_used_at: string | null;
}

export const MCP_SCOPES = [
  { id: "memory:write", label: "Report facts", defaultOn: true, locked: true },
  { id: "cards:read", label: "Read card status", defaultOn: false, locked: false },
  { id: "cards:approve", label: "Publish without asking", defaultOn: false, locked: false },
  { id: "people:message", label: "Message people", defaultOn: false, locked: false },
] as const;

export type SuggestionGroup = "right" | "look" | "noise";

export interface SuggestedFact {
  predicate: string;
  object: string;
  confidence: number;
  group?: SuggestionGroup;
  suggested_predicate?: string;
  public_label?: string;
}

/** Public memory snapshot returned by /cards/mcp/approve. An array (possibly
 *  empty) is a live snapshot; null means none was returned. */
export type MemorySnapshot = Array<Record<string, unknown>> | null;

async function errDetail(res: Response): Promise<string> {
  const data = (await res.json().catch(() => ({}))) as { detail?: string };
  return data.detail || `Request failed (${res.status})`;
}

/** Build the paste-ready config. The MCP server URL comes from .env
 *  (NEXT_PUBLIC_MCP_URL, the centralized/shared MCP server); it falls back to
 *  the URL the memory layer advertises. */
function buildConfig(token: string, mcpUrl: string): McpConnectResult {
  const url = (process.env.NEXT_PUBLIC_MCP_URL || mcpUrl || "").replace(/\/+$/, "");
  const serverBlock = { url, headers: { Authorization: `Bearer ${token}` } };
  return {
    token,
    mcp_url: url,
    config_json: JSON.stringify({ mcpServers: { zynd: serverBlock } }, null, 2),
    config_http: { mcpServers: { zynd: serverBlock } },
    instructions: [
      "Claude Code: claude mcp add --transport http zynd " + url +
        " --header 'Authorization: Bearer <token>'",
      "Cursor: Settings → MCP → Add HTTP server, paste the URL and header",
      "VS Code / Windsurf / Cline: add the JSON block to your mcp.json",
    ],
  };
}

/** Exchange the signed-in session for one assistant token. Other assistants stay connected. */
export async function connectMcp(
  supabaseToken: string,
  options?: { label?: string; scopes?: string[] },
): Promise<McpConnectResult> {
  const res = await fetch(`${MEMORY_API}/token/exchange`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${supabaseToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      label: options?.label || "Assistant",
      scopes: options?.scopes?.length ? options.scopes : ["memory:write"],
    }),
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as {
    token: string;
    mcp_url: string;
    config_json?: string;
    client_id?: string;
    label?: string;
    scopes?: string[];
    cursor?: string;
    claude_code?: string;
    server_url?: string;
  };
  const built = buildConfig(data.token, data.mcp_url);
  return {
    ...built,
    config_json: data.config_json || built.config_json,
    client_id: data.client_id,
    label: data.label,
    scopes: data.scopes,
    cursor: data.cursor,
    claude_code: data.claude_code,
    server_url: data.server_url || built.mcp_url,
  };
}

export async function listMcpClients(supabaseToken: string): Promise<McpClientRow[]> {
  const res = await fetch(`${MEMORY_API}/me/mcp/clients`, {
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as { clients?: McpClientRow[] };
  return data.clients ?? [];
}

export async function revokeMcpClient(supabaseToken: string, clientId: string): Promise<void> {
  const res = await fetch(`${MEMORY_API}/me/mcp/clients/${encodeURIComponent(clientId)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
}

export async function revokeAllMcpClients(supabaseToken: string): Promise<void> {
  const res = await fetch(`${MEMORY_API}/me/mcp/revoke-all`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
}

/** Revoke every ZYND token for the user (signs the MCP connection out everywhere). */
export async function disconnectMcp(personalToken: string): Promise<void> {
  const res = await fetch(`${MEMORY_API}/me/logout`, {
    method: "POST",
    headers: { Authorization: `Bearer ${personalToken}` },
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

/** One of the owner's public card facts with where it came from and the sentence
 *  behind it. Owner-only: `evidence` is the person's own words. */
export interface OwnerCardFact {
  predicate: string;
  object: string;
  provenance?: string;
  evidence?: string | null;
}

export async function fetchOwnerCardFacts(supabaseToken: string): Promise<OwnerCardFact[]> {
  const res = await fetch(`${CARDS_API}/cards/mcp/card-facts`, {
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as { facts?: OwnerCardFact[] };
  return data.facts ?? [];
}

/** Publish one suggested fact onto the user's public card. Returns the fresh
 *  public memory snapshot (null when the API returned none). */
export async function approveSuggestedFact(
  supabaseToken: string,
  predicate: string,
  value: string,
  asPredicate?: string,
): Promise<MemorySnapshot> {
  const body: { predicate: string; value: string; as_predicate?: string } = {
    predicate,
    value,
  };
  if (asPredicate) body.as_predicate = asPredicate;
  const res = await fetch(`${CARDS_API}/cards/mcp/approve`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as { zynd_memory?: unknown };
  return Array.isArray(data.zynd_memory)
    ? (data.zynd_memory as Array<Record<string, unknown>>)
    : null;
}

/** Permanently hide one suggestion from the inbox (keeps private memory). */
export async function dismissSuggestedFact(
  supabaseToken: string,
  predicate: string,
  value: string,
): Promise<void> {
  const res = await fetch(`${CARDS_API}/cards/mcp/dismiss`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ predicate, value }),
  });
  if (!res.ok) throw new Error(await errDetail(res));
}

/** Delete one suggested fact from memory entirely (hard reject). */
export async function deleteSuggestedFact(
  supabaseToken: string,
  predicate: string,
  value: string,
): Promise<void> {
  const res = await fetch(`${CARDS_API}/cards/mcp/forget`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}`, "Content-Type": "application/json" },
    body: JSON.stringify({ predicate, value }),
  });
  if (!res.ok) throw new Error(await errDetail(res));
}
