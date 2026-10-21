// State for a Card assistant reply while it is still being written.
//
// cards-api broadcasts `agent_stream` snapshots on the group's Realtime topic:
// the FULL text so far, not a delta, so a dropped or repeated snapshot costs
// nothing. This file is the pure part (parse, order, merge, prune) so it can be
// tested without a browser; network-v2.tsx owns the React state.

export type AgentStreamStatus = "thinking" | "tool" | "writing" | "done";

/** What the assistant was given and which tools it used. Dev only, never stored. */
export interface AgentSources {
  context?: {
    recent_messages?: number;
    summary?: { present?: boolean; preview?: string };
    group_facts?: { count?: number; items?: string[] };
    member_facts?: { member?: string | null; connected?: boolean; count?: number; items?: string[] };
  };
  tools?: {
    name?: string;
    args?: Record<string, string>;
    summary?: string;
    ok?: boolean;
    running?: boolean;
  }[];
  more_tools?: number;
  truncated?: boolean;
}

export interface AgentStreamSnapshot {
  jobId: string;
  userId: string;
  messageId: string | null;
  /** Retries of the same job count up; `seq` restarts within each attempt. */
  attempt: number;
  seq: number;
  text: string;
  done: boolean;
  status: AgentStreamStatus;
  sources?: AgentSources;
}

export interface AgentStream extends AgentStreamSnapshot {
  updatedAt: number;
}

/** Streams in flight, by job id (the id the final message carries as `client_id`). */
export type AgentStreams = Record<string, AgentStream>;

/** Longest a stream may go without a snapshot before it is forgotten. */
export const STREAM_STALE_MS = 90_000;

const STATUSES: readonly string[] = ["thinking", "tool", "writing", "done"];

export function parseAgentStream(payload: Record<string, unknown>): AgentStreamSnapshot | null {
  const jobId = typeof payload.job_id === "string" ? payload.job_id : "";
  const userId = typeof payload.user_id === "string" ? payload.user_id : "";
  if (!jobId || !userId) return null;
  const done = payload.done === true;
  const status = typeof payload.status === "string" && STATUSES.includes(payload.status)
    ? (payload.status as AgentStreamStatus)
    : done ? "done" : "writing";
  const sources = payload.sources && typeof payload.sources === "object" && !Array.isArray(payload.sources)
    ? (payload.sources as AgentSources)
    : undefined;
  return {
    jobId,
    userId,
    messageId: typeof payload.message_id === "string" ? payload.message_id : null,
    attempt: Number(payload.attempt) || 0,
    seq: Number(payload.seq) || 0,
    text: typeof payload.text === "string" ? payload.text : "",
    done,
    status,
    sources,
  };
}

/**
 * Fold one snapshot into the streams. A snapshot older than what is held (a
 * lower attempt, or the same attempt at a lower or equal `seq`) is ignored, so
 * a reordered or duplicated delivery cannot rewind the text. A new attempt
 * replaces the old text outright; that is how a retried job starts over.
 * Sources only ever accumulate within an attempt: a snapshot that carries none
 * keeps the ones already known.
 */
export function applyAgentStream(streams: AgentStreams, snapshot: AgentStreamSnapshot, now: number): AgentStreams {
  const previous = streams[snapshot.jobId];
  if (previous && snapshot.seq > 0) {
    if (snapshot.attempt < previous.attempt) return streams;
    if (snapshot.attempt === previous.attempt && snapshot.seq <= previous.seq) return streams;
  }
  const sameAttempt = previous?.attempt === snapshot.attempt;
  return {
    ...streams,
    [snapshot.jobId]: {
      ...snapshot,
      sources: snapshot.sources ?? (sameAttempt ? previous?.sources : undefined),
      updatedAt: now,
    },
  };
}

/** A user's assistant is retrying or has given up: whatever it had written is void. */
export function clearUserStreams(streams: AgentStreams, userId: string): AgentStreams {
  const keep = Object.entries(streams).filter(([, stream]) => stream.userId !== userId);
  return keep.length === Object.keys(streams).length ? streams : Object.fromEntries(keep);
}

/** The durable message arrived (by event or by page): its stream is no longer needed. */
export function dropFinishedStreams(
  streams: AgentStreams,
  messages: readonly { client_id?: string | null }[],
): AgentStreams {
  const finished = new Set(messages.map((message) => message.client_id).filter(Boolean));
  const keep = Object.entries(streams).filter(([jobId]) => !finished.has(jobId));
  return keep.length === Object.keys(streams).length ? streams : Object.fromEntries(keep);
}

/** Forget streams that stopped updating, e.g. the worker died mid-reply. */
export function pruneStaleStreams(streams: AgentStreams, now: number, maxAge = STREAM_STALE_MS): AgentStreams {
  const keep = Object.entries(streams).filter(([, stream]) => now - stream.updatedAt <= maxAge);
  return keep.length === Object.keys(streams).length ? streams : Object.fromEntries(keep);
}

/**
 * The streams to draw as bubbles: they have text, and the final message is not
 * in the conversation yet. Checking the messages here, not only when a message
 * event arrives, covers both arrival orders (final message first, then a late
 * snapshot) and a message that came in through a fetched page.
 */
export function visibleStreams(
  streams: AgentStreams,
  messages: readonly { client_id?: string | null }[],
): AgentStream[] {
  const have = new Set(messages.map((message) => message.client_id).filter(Boolean));
  return Object.values(streams)
    .filter((stream) => stream.text.trim() !== "" && !have.has(stream.jobId))
    .sort((a, b) => a.updatedAt - b.updatedAt || a.jobId.localeCompare(b.jobId));
}

const TOOL_LABELS: Record<string, string> = {
  search_group_memory: "Searching group memory…",
  get_recent_group_messages: "Reading recent messages…",
  get_person_public_memory: "Reading a member's public memory…",
  get_group_memory: "Reading group memory…",
  get_group_members: "Checking who is in the group…",
};

/**
 * What a not-yet-writing assistant is doing, or null. The tool name is only
 * known when the server runs with FEATURE_AGENT_DEBUG_SOURCES; otherwise a
 * tool step is just "Looking things up…".
 */
export function activityLabel(stream: AgentStream | undefined): string | null {
  if (!stream || stream.status !== "tool") return null;
  const running = [...(stream.sources?.tools ?? [])].reverse().find((tool) => tool.running);
  return (running?.name && TOOL_LABELS[running.name]) || "Looking things up…";
}
