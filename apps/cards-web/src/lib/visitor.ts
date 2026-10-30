/** Who is reading a server-rendered page or route, for the agent_fetch events in lib/track.ts. */

export interface Visitor {
  userAgent: string | null;
  /** The address host Caddy saw; null when there is no proxy header (local dev). */
  ip: string | null;
}

/** Keep in step with _AI_AGENT in cards-api services/ua_class.py (the MCP labels there are
 *  memory's, never a browser's). Matched case-insensitively anywhere in the header, as there. */
const AI_AGENT_TOKENS = [
  "GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "anthropic-ai",
  "PerplexityBot", "Perplexity-User", "Google-Extended", "Bytespider", "CCBot", "Amazonbot",
  "Applebot-Extended", "Meta-ExternalAgent", "cohere-ai", "Codex",
].map((token) => token.toLowerCase());

export function isAiAgent(userAgent: string | null | undefined): boolean {
  const ua = (userAgent ?? "").toLowerCase();
  return ua.length > 0 && AI_AGENT_TOKENS.some((token) => ua.includes(token));
}

/** Host Caddy drops a client's own X-Forwarded-For and writes the peer it saw, so the last entry
 *  is Caddy's (infra/single-box/Caddyfile); anything before it would be the caller's claim. */
export function forwardedClientIp(forwardedFor: string | null | undefined): string | null {
  const entries = (forwardedFor ?? "").split(",").map((entry) => entry.trim()).filter(Boolean);
  return entries.at(-1) ?? null;
}

export function visitorFrom(headers: Pick<Headers, "get">): Visitor {
  return { userAgent: headers.get("user-agent"), ip: forwardedClientIp(headers.get("x-forwarded-for")) };
}
