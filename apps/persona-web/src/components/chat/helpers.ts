import type { ActionRecord, PersonaHit, ThreadHandoff, ToolCallState } from "./types";
import type { ServiceCallResult } from "@/lib/services-commands";

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function extractPersonaHits(actions: ActionRecord[] | undefined): PersonaHit[] {
  if (!actions) return [];
  const hits: PersonaHit[] = [];
  const seen = new Set<string>();
  for (const a of actions) {
    if (a.tool !== "search_zynd_personas") continue;
    const r = a.result;
    if (!isPlainObject(r)) continue;
    const list = r.results;
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      if (!isPlainObject(item)) continue;
      const id = typeof item.agent_id === "string" ? item.agent_id : "";
      if (!id || seen.has(id)) continue;
      seen.add(id);
      hits.push({
        agent_id: id,
        name: typeof item.name === "string" ? item.name : undefined,
        description: typeof item.description === "string" ? item.description : undefined,
        avatar_url: typeof item.avatar_url === "string" ? item.avatar_url : null,
      });
    }
  }
  return hits;
}

const HANDOFF_TOOLS = new Set([
  "request_connection",
  "message_zynd_agent",
  "propose_meeting",
]);

export function extractHandoffs(actions: ActionRecord[] | undefined): ThreadHandoff[] {
  if (!actions) return [];
  const out: ThreadHandoff[] = [];
  const seen = new Set<string>();
  for (const a of actions) {
    if (!HANDOFF_TOOLS.has(a.tool)) continue;
    const r = a.result;
    if (!isPlainObject(r)) continue;
    const tid = typeof r.thread_id === "string" ? r.thread_id : "";
    if (!tid || seen.has(tid)) continue;
    seen.add(tid);
    out.push({
      thread_id: tid,
      partner_name: typeof r.partner_name === "string" ? r.partner_name : undefined,
      partner_agent_id: typeof r.partner_agent_id === "string" ? r.partner_agent_id : undefined,
      source_tool: a.tool,
    });
  }
  return out;
}

const CALL_TOOLS = new Set(["call_zynd_service", "call_zynd_agent"]);

/** Does a call result carry something worth rendering as a card? */
function hasRenderableContent(r: Record<string, unknown>): boolean {
  const so = r.structured_output;
  const soOk = so != null && !(typeof so === "string" && so.trim() === "");
  const textOk = typeof r.reply_text === "string" && r.reply_text.trim().length > 0;
  return soOk || textOk;
}

/**
 * Pull service/agent call results out of a finished message (`actions`, which
 * persists + rehydrates) or, while still streaming, the live `toolCalls`. The
 * GenUiResult card renders these below the assistant bubble — so cards survive
 * reload exactly like MatchCard/HandoffCards do.
 */
export function extractCallResults(
  actions: ActionRecord[] | undefined,
  toolCalls: ToolCallState[] | undefined,
): ServiceCallResult[] {
  const out: ServiceCallResult[] = [];
  const seen = new Set<string>();

  const push = (tool: string, result: unknown) => {
    if (!CALL_TOOLS.has(tool) || !isPlainObject(result)) return;
    const status = typeof result.status === "string" ? result.status : "";
    // Async dispatch has no reply yet — the model's "I sent it" prose is right.
    if (status === "dispatched") return;
    const isError =
      status === "error" || status === "auth_required" || status === "remote_failed" ||
      status === "bad_request" || status === "rejected";
    if (!hasRenderableContent(result) && !isError && status !== "needs_input") return;
    const key =
      (typeof result.task_id === "string" && result.task_id) ||
      `${result.entity_id ?? ""}:${JSON.stringify(result.structured_output ?? result.reply_text ?? "").slice(0, 240)}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(result as unknown as ServiceCallResult);
  };

  // Prefer the persisted/finished actions; fall back to live tool calls so the
  // card appears as soon as the result streams in (before the lead-in finishes).
  if (actions && actions.length) {
    for (const a of actions) push(a.tool, a.result);
  }
  if (out.length === 0 && toolCalls && toolCalls.length) {
    for (const tc of toolCalls) {
      if (tc.status === "done" || tc.status === "error") push(tc.name, tc.result);
    }
  }
  return out;
}

/** Last non-empty line — used as a one-line preview for collapsed thinking. */
export function lastLine(text: string | undefined): string {
  if (!text) return "";
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  return lines.length > 0 ? lines[lines.length - 1] : "";
}

/** Map orchestrator tool names to first-person verb labels. */
const TOOL_VERBS: Record<string, { active: string; done: string }> = {
  search_zynd_personas:  { active: "Searching the network",     done: "Looked through the network" },
  get_persona_profile:   { active: "Reading a profile",          done: "Read a profile" },
  request_connection:    { active: "Reaching out",               done: "Reached out" },
  message_zynd_agent:    { active: "Sending a message",          done: "Sent a message" },
  propose_meeting:       { active: "Proposing a time",           done: "Proposed a time" },
  schedule_meeting:      { active: "Booking it",                 done: "Booked it" },
};

export function toolVerb(name: string, status: "running" | "done" | "error"): string {
  const v = TOOL_VERBS[name];
  if (!v) return status === "done" ? "Done" : "Working on it";
  if (status === "error") return `${v.active} — that didn't work`;
  return status === "done" ? v.done : v.active;
}
