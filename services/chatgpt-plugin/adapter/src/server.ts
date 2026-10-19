import "dotenv/config";
import express, { type Request, type Response, type NextFunction } from "express";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";
import { zyndApi } from "./zynd-api.js";
import { pluginScopes, requireScope } from "./consent.js";
import { PLUGIN_TOOL_SCOPES, type AuthenticatedUser } from "./types.js";

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "128kb" }));

type AuthRequest = Request & { zyndUser?: AuthenticatedUser };

const MCP_RESOURCE = (process.env.ZYND_MCP_URL ?? "https://api.zynd.ai/chatgpt/mcp").replace(/\/$/, "");
const AUTH_ISSUER = (process.env.ZYND_AUTH_ISSUER ?? "https://api.zynd.ai").replace(/\/$/, "");

function challenge(res: Response, status: number, error: string) {
  const metadata = `${new URL(MCP_RESOURCE).origin}/.well-known/oauth-protected-resource`;
  res.setHeader("WWW-Authenticate", `Bearer resource_metadata="${metadata}", error="${error}"`);
  return res.status(status).json({ error });
}

function scopesOf(payload: Record<string, unknown>): string[] {
  const scp = payload.scp;
  if (Array.isArray(scp) && scp.every((item) => typeof item === "string")) return scp;
  if (typeof payload.scope === "string") return payload.scope.split(" ").filter(Boolean);
  return [];
}

function authenticate(req: AuthRequest, res: Response, next: NextFunction) {
  const match = /^Bearer\s+(.+)$/i.exec(req.header("authorization") ?? "");
  if (!match?.[1]) return challenge(res, 401, "unauthorized");
  const token = match[1];
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return challenge(res, 401, "invalid_token");
  try {
    const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8")) as Record<string, unknown>;
    const audience = payload.aud;
    const audiences = Array.isArray(audience) ? audience : [audience];
    const clientId = typeof payload.cid === "string" ? payload.cid : "";
    if (payload.iss !== AUTH_ISSUER || !audiences.includes(MCP_RESOURCE) || clientId !== "zynd-chatgpt-plugin") {
      return challenge(res, 401, "invalid_token");
    }
    if (typeof payload.exp === "number" && payload.exp * 1000 <= Date.now()) {
      return challenge(res, 401, "invalid_token");
    }
    req.zyndUser = { scopes: pluginScopes(scopesOf(payload)), accessToken: token };
    next();
  } catch {
    return challenge(res, 401, "invalid_token");
  }
}

function text(value: unknown) {
  return [{ type: "text" as const, text: JSON.stringify(value) }];
}

function makeServer(user: AuthenticatedUser) {
  const server = new McpServer({ name: "zynd", version: "0.2.0" });

  server.registerTool("recall_memories", {
    description: "Recall relevant private ZYND facts only when the owner asks about them. Read-only; never saves.",
    inputSchema: {
      query: z.string().trim().min(1).max(500),
      limit: z.number().int().min(1).max(10).default(5),
    },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  }, async ({ query, limit }) => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.recall_memories);
    const result = await zyndApi.recallMemories(user, query, limit);
    return { content: text(result), structuredContent: result };
  });

  server.registerTool("propose_memory", {
    description: "Draft one exact private fact for signed-in Zynd web review. This does not save it. Never pass a confirmation nonce.",
    inputSchema: { text: z.string().trim().min(1).max(2000) },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, async ({ text: fact }) => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.propose_memory);
    const proposal = await zyndApi.proposeMemory(user, fact);
    return {
      content: text(`Pending review ${proposal.id}. Not saved. Open ${proposal.review_url} while signed in.`),
      structuredContent: proposal,
    };
  });

  server.registerTool("get_proposal_status", {
    description: "Read one proposal's status. Pending review is not saved or published.",
    inputSchema: { proposal_id: z.string().uuid() },
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  }, async ({ proposal_id }) => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.get_proposal_status);
    const result = await zyndApi.getProposalStatus(user, proposal_id);
    return { content: text(result), structuredContent: result };
  });

  server.registerTool("list_pending_facts", {
    description: "List private card facts and pending proposals. Do not publish them.",
    inputSchema: {},
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  }, async () => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.list_pending_facts);
    const result = await zyndApi.listPendingFacts(user);
    return { content: text(result), structuredContent: result };
  });

  server.registerTool("propose_card_fact", {
    description: "Queue one existing private card fact, by id and version, for exact-wording web review. This does not publish it.",
    inputSchema: { fact_id: z.string().uuid(), version: z.number().int().positive() },
    annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: false },
  }, async ({ fact_id, version }) => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.propose_card_fact);
    const result = await zyndApi.proposeCardFact(user, fact_id, version);
    return {
      content: text(`Pending review ${result.id}. Nothing published. Open ${result.review_url} while signed in.`),
      structuredContent: result,
    };
  });

  server.registerTool("get_public_card", {
    description: "Return only facts already approved for the public card.",
    inputSchema: {},
    annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
  }, async () => {
    requireScope(user.scopes, PLUGIN_TOOL_SCOPES.get_public_card);
    const result = await zyndApi.getPublicCard(user);
    return { content: text(result), structuredContent: result };
  });

  return server;
}

app.get("/healthz", (_req, res) => res.json({ ok: true, service: "zynd-mcp", upstream: MCP_RESOURCE }));

app.post("/mcp", authenticate, async (req: AuthRequest, res: Response) => {
  const user = req.zyndUser!;
  const server = makeServer(user);
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  res.on("close", () => { void transport.close(); void server.close(); });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch {
    if (!res.headersSent) res.status(500).json({ error: "mcp_request_failed", requestId: randomUUID() });
  }
});

const port = Number(process.env.PORT ?? 8787);
app.listen(port, "0.0.0.0", () => {
  console.log(`ZYND MCP adapter listening on port ${port}`);
});
