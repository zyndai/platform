/**
 * Shared types for the home chat. Extracted so MessageBubble, ChatInterface,
 * and helpers can all import from one place without circular deps.
 */

export interface ToolCallState {
  id: string;
  name: string;
  /** Accumulated JSON fragment streamed in tool_call_args events. */
  argsText: string;
  /** Parsed args once tool_call_end arrives. */
  arguments?: Record<string, unknown>;
  /** Result returned by tool_result. */
  result?: unknown;
  status: "running" | "done" | "error";
}

export interface ActionSummaryItem {
  status: "done" | "pending" | "waiting" | "error" | "none";
  label: string;
  icon?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Reasoning stream (only when the provider exposes it). */
  thinking?: string;
  /** Live tool-call progress while the SSE is open. */
  toolCalls?: ToolCallState[];
  /** Final actions array from the orchestrator's `done` event. */
  actions?: ActionRecord[];
  /** User-facing status summary derived from actions. */
  actionSummary?: ActionSummaryItem[];
  /** Synthetic = client-only message (welcome line, callback banner). Don't persist or count. */
  synthetic?: boolean;
  /** Set on synthetic A2A-callback banners — used for dedup if realtime re-delivers. */
  callbackId?: string;
  /** Inbound A2A request from a peer's agent — renders an inline reply composer
   *  in the home chat instead of a plain markdown banner. */
  incoming?: IncomingRequest;
  /** True while the SSE is open. */
  streaming?: boolean;
  error?: string;
  /** Slash-command result payload (e.g. `/services <query>`). Rendered
   *  inline as a card list instead of markdown. Local-only, never persisted. */
  services?: ServicesPanelPayload;
}

export interface ServicesPanelPayload {
  kind: "search" | "card" | "help" | "error" | "agents" | "call";
  query?: string;
  entityId?: string;
  search?: import("@/lib/services-commands").ServiceSearchPayload;
  agents?: import("@/lib/services-commands").AgentSearchPayload;
  /** For kind "card" AND "call" — the call form reads its input_schema. */
  card?: import("@/lib/services-commands").ServiceCardPayload;
  helpText?: string;
  error?: string;
  loading?: boolean;
  // ── kind === "call" ──────────────────────────────────────────────
  /** Display name of the entity being called (from the search row). */
  callName?: string;
  /** Persona hint threaded from the originating search row, if any. */
  callKind?: string;
  /** True while the card (form schema) is being fetched. */
  callLoading?: boolean;
  /** True while a submitted call is in flight. */
  callSubmitting?: boolean;
  /** Result of the most recent submit. */
  callResult?: import("@/lib/services-commands").ServiceCallResult;
  /** Top-level error (card fetch failed, or the call threw). */
  callError?: string;
}

export interface IncomingRequest {
  /** dm_threads.id — used for the agent-send POST when the user replies. */
  threadId: string;
  /** dm_messages.id — used for client-side dedup. */
  messageId: string;
  /** Short label for the peer (last 8 chars of agent_id by default). */
  peerLabel: string;
  /** Full message body the peer sent. */
  body: string;
  /** Flips to true once the user has sent a reply through the composer. */
  replied?: boolean;
}

export interface ActionRecord {
  tool: string;
  args?: unknown;
  result: unknown;
}

export interface PersonaHit {
  agent_id: string;
  name?: string;
  description?: string;
  avatar_url?: string | null;
  /** Grounded one-line "why this matched" from the backend's keyword-overlap
   *  scoring (e.g. "matched on: founder, ai") — shown as MatchCard's reason
   *  instead of an arbitrary slice of the description. */
  match_reason?: string;
}

export interface ThreadHandoff {
  thread_id: string;
  partner_name?: string;
  partner_agent_id?: string;
  source_tool: string;
}

export interface PublishedPage {
  slug: string;
  url: string;
  title: string;
  format: "html" | "markdown";
  visibility?: string;
  created_at?: string | null;
}
