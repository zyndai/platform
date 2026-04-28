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

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  /** Reasoning stream (only when the provider exposes it). */
  thinking?: string;
  /** Live tool-call progress while the SSE is open. */
  toolCalls?: ToolCallState[];
  /** Final actions array from the orchestrator's `done` event. */
  actions?: ActionRecord[];
  /** Synthetic = client-only message (welcome line). Don't persist or count. */
  synthetic?: boolean;
  /** True while the SSE is open. */
  streaming?: boolean;
  error?: string;
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
}

export interface ThreadHandoff {
  thread_id: string;
  partner_name?: string;
  partner_agent_id?: string;
  source_tool: string;
}
