import type { AuthenticatedUser, PluginToolName } from "./types.js";

const base = (process.env.ZYND_MCP_URL ?? "https://api.zynd.ai/chatgpt/mcp").replace(/\/$/, "");

type RpcResult = { result?: unknown; error?: { message?: string; code?: number } };

async function callTool(user: AuthenticatedUser, name: PluginToolName, args: Record<string, unknown>): Promise<unknown> {
  const response = await fetch(base, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${user.accessToken}`,
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status === 401) throw new Error("ZYND MCP rejected the access token");
  if (!response.ok) throw new Error(`ZYND MCP request failed (${response.status})`);

  const body = await response.json() as RpcResult;
  if (body.error) throw new Error(body.error.message ?? "ZYND MCP tool call failed");
  const result = body.result as { isError?: boolean; structuredContent?: unknown; content?: Array<{ text?: string }> } | undefined;
  if (!result || result.isError) throw new Error(result?.content?.[0]?.text ?? "ZYND MCP tool call failed");
  if (result.structuredContent !== undefined) return result.structuredContent;
  const text = result.content?.find((part) => typeof part.text === "string")?.text;
  if (text) {
    try { return JSON.parse(text) as unknown; } catch { return { text }; }
  }
  return {};
}

export const zyndApi = {
  recallMemories(user: AuthenticatedUser, query: string, limit: number) {
    return callTool(user, "recall_memories", { query, limit }) as Promise<{ facts: Array<{ text: string }>; private: true }>;
  },
  proposeMemory(user: AuthenticatedUser, text: string) {
    return callTool(user, "propose_memory", { text }) as Promise<{ id: string; status: string; expires_at: string; review_url: string }>;
  },
  getProposalStatus(user: AuthenticatedUser, proposalId: string) {
    return callTool(user, "get_proposal_status", { proposal_id: proposalId }) as Promise<{ id: string; status: string; expires_at?: string }>;
  },
  listPendingFacts(user: AuthenticatedUser) {
    return callTool(user, "list_pending_facts", {}) as Promise<{ ok: boolean; data: unknown[] }>;
  },
  proposeCardFact(user: AuthenticatedUser, factId: string, version: number) {
    return callTool(user, "propose_card_fact", { fact_id: factId, version }) as Promise<{ id: string; status: string; expires_at: string; review_url: string }>;
  },
  getPublicCard(user: AuthenticatedUser) {
    return callTool(user, "get_public_card", {}) as Promise<{ facts: unknown[] }>;
  },
};
