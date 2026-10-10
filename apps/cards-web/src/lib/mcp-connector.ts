import { CARDS_API } from "@/lib/cards";
import { MEMORY_API } from "@/lib/memory";

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

/** Exchange the signed-in user's Supabase session for a personal token on the
 *  centralized MCP server, then build the paste-ready config. */
export async function connectMcp(supabaseToken: string): Promise<McpConnectResult> {
  const res = await fetch(`${MEMORY_API}/token/exchange`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) throw new Error(await errDetail(res));
  const data = (await res.json()) as { token: string; mcp_url: string };
  return buildConfig(data.token, data.mcp_url);
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
