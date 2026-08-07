/**
 * Slash-command parser + API client for Zynd network-discovery commands.
 *
 * Supported commands:
 *   /agents <query>           → search the WHOLE network (personas + services + agents)
 *   /services <query>         → narrow search to services only
 *   /card <entity_id>         → fetch any entity's agent-card
 *   /help                     → show available commands
 *
 * Commands are intercepted client-side and call /api/{agents,services}/* directly,
 * bypassing the LLM. The orchestrator can still reach for the same tools
 * in natural-language chat — slash commands are a power-user shortcut.
 */

import { apiPost, apiGet } from "@/lib/api";

export type SlashCommand =
  | { kind: "agents"; query: string }
  | { kind: "services"; query: string }
  | { kind: "card"; entityId: string }
  | { kind: "help" }
  | { kind: "invalid"; raw: string; hint: string };

const VALID_NAMES = ["agents", "services", "card", "help"] as const;

export function parseSlashCommand(input: string): SlashCommand | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return null;
  const space = trimmed.indexOf(" ");
  const name = (space === -1 ? trimmed.slice(1) : trimmed.slice(1, space)).toLowerCase();
  const arg = space === -1 ? "" : trimmed.slice(space + 1).trim();

  if (name === "agents") {
    if (!arg) {
      return {
        kind: "invalid",
        raw: trimmed,
        hint: "Usage: /agents <query>  — e.g. `/agents competitor monitoring`",
      };
    }
    return { kind: "agents", query: arg };
  }
  if (name === "services" || name === "search") {
    if (!arg) {
      return {
        kind: "invalid",
        raw: trimmed,
        hint: "Usage: /services <query>  — e.g. `/services translate text`",
      };
    }
    return { kind: "services", query: arg };
  }
  if (name === "card") {
    if (!arg) {
      return {
        kind: "invalid",
        raw: trimmed,
        hint: "Usage: /card <entity_id>  — e.g. `/card zns:svc:abc…`",
      };
    }
    return { kind: "card", entityId: arg };
  }
  if (name === "help") {
    return { kind: "help" };
  }
  if (!VALID_NAMES.includes(name as typeof VALID_NAMES[number])) {
    return {
      kind: "invalid",
      raw: trimmed,
      hint: `Unknown command \`/${name}\`. Try /agents, /services, /card, or /help.`,
    };
  }
  return null;
}

export interface ServiceSearchResult {
  entity_id: string;
  name: string;
  summary: string;
  category: string;
  tags?: string[];
  status?: string;
  score?: number;
}

export interface AgentSearchResult {
  entity_id: string;
  name: string;
  kind: string; // "persona" | "agent" | "service" — the registry entity_type
  /** Registry's authoritative entity_type ("agent" | "service" | "persona"). */
  entity_type?: string;
  summary: string;
  category: string; // topic label e.g. "marketing", "general" — NOT the type
  tags?: string[];
  url?: string;
  status?: string;
  avatar_url?: string | null;
}

export interface AgentSearchPayload {
  status: "success" | "error";
  /** Rows in this page (results.length). */
  count: number;
  /** Full number of matches on the network, before the page limit. */
  total_available?: number;
  /** Breakdown of total_available by kind, e.g. { persona: 18, agent: 2 }. */
  by_kind?: Record<string, number>;
  results: AgentSearchResult[];
  source?: string;
  error?: string;
}

export interface ServiceSearchPayload {
  status: "success" | "error";
  count: number;
  results: ServiceSearchResult[];
  total_found?: number;
  hint?: string;
  error?: string;
  from_cache?: boolean;
}

export interface ServiceCardPayload {
  status: "success" | "not_found" | "unreachable" | "error";
  entity_id: string;
  name?: string;
  description?: string;
  url?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  category?: string;
  tags?: string[];
  service_status?: string;
  pricing?: Record<string, unknown>;
  hint?: string;
  error?: string;
}

export async function runServiceSearch(query: string): Promise<ServiceSearchPayload> {
  return apiPost<ServiceSearchPayload>("/api/services/search", {
    query,
    top_k: 5,
  });
}

export async function runAgentSearch(query: string): Promise<AgentSearchPayload> {
  return apiPost<AgentSearchPayload>("/api/agents/search", {
    query,
    top_k: 8,
    kind: "any",
  });
}

export async function runServiceCard(entityId: string): Promise<ServiceCardPayload> {
  return apiGet<ServiceCardPayload>(
    `/api/services/card/${encodeURIComponent(entityId)}`,
  );
}

export interface ServiceCallResult {
  // The backend (classify_task_result + dispatch paths) emits more states than
  // the original three — keep them in the union so the gen-UI renderer can
  // switch on them without casts.
  status:
    | "success"
    | "partial"
    | "error"
    | "auth_required"
    | "needs_input"
    | "working"
    | "dispatched"
    | "empty_result"
    | "bad_request"
    | "remote_failed"
    | "rejected"
    | "not_found"
    | "unreachable";
  entity_id: string;
  task_id?: string;
  task_state?: string;
  reply_text?: string | null;
  structured_output?: unknown; // JSON-parsed reply; prefer over reply_text
  error?: string;
  /** Non-technical explanation of why the error happened. */
  error_message?: string;
  /** What the user can do next. */
  hint?: string;
  error_code?: string | number;
  error_data?: unknown;
}

export async function runServiceCall(
  entityId: string,
  args: { text?: string; data?: Record<string, unknown> },
): Promise<ServiceCallResult> {
  return apiPost<ServiceCallResult>(
    `/api/services/call/${encodeURIComponent(entityId)}`,
    { text: args.text, data: args.data },
  );
}

export const HELP_TEXT = `**Slash commands**

- \`/agents <query>\` — search the entire Zynd Network: personas, services, and standalone agents (e.g. \`/agents influencer discovery\`). Each result has a **Call** button (fill in the agent's inputs and run it) and a **Let my persona handle it** button.
- \`/services <query>\` — narrow search to capability-style services only (e.g. \`/services translate text\`).
- \`/card <service name or id>\` — fetch a service's live card (description, inputs, status).
- \`/help\` — show this help.

For natural-language requests like *"find a competitor research agent and run it"* your persona will search, read the card, and call it automatically — slash commands are a faster, deterministic path.`;

/**
 * Definitions used to power the slash-command autocomplete popover in chat
 * composers. Keep this list in sync with the parser above — every entry here
 * must be a name `parseSlashCommand` understands.
 */
export interface SlashCommandDef {
  /** Canonical name as the user types it (no leading slash). */
  name: string;
  /** Short usage hint shown next to the name, e.g. "<query>". */
  args: string;
  /** One-line description for the popover row. */
  description: string;
  /** A concrete usage example shown in muted text. */
  example: string;
  /** What the input should look like AFTER picking this command. The caret
   *  lands at the end of insertText, ready for the user to type the argument. */
  insertText: string;
}

export const SLASH_COMMANDS: SlashCommandDef[] = [
  {
    name: "agents",
    args: "<query>",
    description: "Find any agent, service, or persona on the network — then call it.",
    example: "/agents competitor monitoring",
    insertText: "/agents ",
  },
  {
    name: "services",
    args: "<query>",
    description: "Search the Zynd registry for a service that can do this.",
    example: "/services translate text",
    insertText: "/services ",
  },
  {
    name: "card",
    args: "<service name or id>",
    description: "Show a service's description, inputs, and live status.",
    example: "/card currency converter",
    insertText: "/card ",
  },
  {
    name: "help",
    args: "",
    description: "List every slash command and what it does.",
    example: "/help",
    insertText: "/help",
  },
];

/**
 * Match a partial command at the start of `text`. Returns the slice of
 * commands whose name starts with the typed prefix, or `null` if the input
 * is not in a "still typing the command name" state (e.g. the user has
 * already typed an argument after a space).
 */
export function suggestSlashCommands(text: string): SlashCommandDef[] | null {
  if (!text.startsWith("/")) return null;
  const space = text.indexOf(" ");
  if (space !== -1) return null; // already typing args — no more suggestions
  const prefix = text.slice(1).toLowerCase();
  if (!prefix) return SLASH_COMMANDS;
  return SLASH_COMMANDS.filter((c) => c.name.startsWith(prefix));
}
