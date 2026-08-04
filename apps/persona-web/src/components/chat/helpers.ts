import type {
  ActionRecord,
  PersonaHit,
  PublishedPage,
  ThreadHandoff,
  ToolCallState,
} from "./types";
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
        match_reason: typeof item.match_reason === "string" ? item.match_reason : undefined,
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

function isPublishedPageValue(v: unknown): v is PublishedPage {
  if (!isPlainObject(v)) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.slug === "string" &&
    typeof r.url === "string" &&
    typeof r.title === "string" &&
    (r.format === "html" || r.format === "markdown")
  );
}

/**
 * Pull `publish_page` results out of the final actions array so the chat can
 * render a shareable-page card with copy/open buttons.
 */
export function extractPublishedPages(
  actions: ActionRecord[] | undefined,
): PublishedPage[] {
  if (!actions) return [];
  const out: PublishedPage[] = [];
  const seen = new Set<string>();
  for (const a of actions) {
    if (a.tool !== "publish_page") continue;
    const r = a.result;
    if (!isPlainObject(r) || !r.success || !isPublishedPageValue(r)) continue;
    if (seen.has(r.slug)) continue;
    seen.add(r.slug);
    out.push(r);
  }
  return out;
}

/**
 * Pull `list_my_pages` results so the chat can render a compact page list card.
 */
export function extractPageLists(
  actions: ActionRecord[] | undefined,
): PublishedPage[] | null {
  if (!actions) return null;
  for (const a of actions) {
    if (a.tool !== "list_my_pages") continue;
    const r = a.result;
    if (!isPlainObject(r) || !r.success || !Array.isArray(r.pages)) continue;
    const pages = r.pages.filter(isPublishedPageValue) as PublishedPage[];
    return pages.length ? pages : [];
  }
  return null;
}
