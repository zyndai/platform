/** S11 — public Cards MCP discovery. Off by default; advertise only when enabled. */
export function featureS11PublicMcp(): boolean {
  return process.env.NEXT_PUBLIC_FEATURE_S11_PUBLIC_MCP === "true";
}

export const PUBLIC_CARDS_MCP_URL = "https://api.zynd.ai/cards-public-mcp";
