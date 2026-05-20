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
