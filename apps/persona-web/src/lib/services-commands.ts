/**
 * Slash-command parser + API client for Zynd service-discovery commands.
 *
 * Supported commands:
 *   /services <query>         → search the registry
 *   /card <entity_id>         → fetch a service's agent-card
 *   /help                     → show available commands
 *
 * Commands are intercepted client-side and call /api/services/* directly,
 * bypassing the LLM. The orchestrator can still reach for the same tools
 * in natural-language chat — slash commands are a power-user shortcut.
 */

import { apiPost, apiGet } from "@/lib/api";

export type SlashCommand =
  | { kind: "services"; query: string }
  | { kind: "card"; entityId: string }
  | { kind: "help" }
  | { kind: "invalid"; raw: string; hint: string };

const VALID_NAMES = ["services", "card", "help"] as const;

export function parseSlashCommand(input: string): SlashCommand | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/")) return null;
  const space = trimmed.indexOf(" ");
  const name = (space === -1 ? trimmed.slice(1) : trimmed.slice(1, space)).toLowerCase();
  const arg = space === -1 ? "" : trimmed.slice(space + 1).trim();

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
      hint: `Unknown command \`/${name}\`. Try /services, /card, or /help.`,
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

export async function runServiceCard(entityId: string): Promise<ServiceCardPayload> {
  return apiGet<ServiceCardPayload>(
    `/api/services/card/${encodeURIComponent(entityId)}`,
  );
}

export const HELP_TEXT = `**Slash commands**

- \`/services <query>\` — search the Zynd registry for services that fulfill the capability (e.g. \`/services translate text\`).
- \`/card <entity_id>\` — fetch a service's full agent-card (input schema, endpoint URL, status).
- \`/help\` — show this help.

For natural-language requests like *"translate this to French"* your agent will pick a service automatically — slash commands are a faster, deterministic path.`;

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
    name: "services",
    args: "<query>",
    description: "Search the Zynd registry for a service that can do this.",
    example: "/services translate text",
    insertText: "/services ",
  },
  {
    name: "card",
    args: "<entity_id>",
    description: "Show a service's input schema, endpoint, and live status.",
    example: "/card zns:svc:c565a80…",
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
