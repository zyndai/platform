import type { ActionRecord, PersonaHit, ThreadHandoff } from "./types";

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
