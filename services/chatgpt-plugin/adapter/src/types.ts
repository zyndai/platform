export type AuthenticatedUser = {
  scopes: string[];
  accessToken: string;
};

export const PLUGIN_SCOPES = ["memory:recall", "memory:propose", "cards:review"] as const;

export const PLUGIN_TOOL_SCOPES = {
  recall_memories: "memory:recall",
  propose_memory: "memory:propose",
  get_proposal_status: "memory:propose",
  list_pending_facts: "cards:review",
  propose_card_fact: "cards:review",
  get_public_card: "cards:review",
} as const;

export type PluginToolName = keyof typeof PLUGIN_TOOL_SCOPES;
