"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ExternalLink,
  Plus,
} from "lucide-react";
import { QUICK_PROMPTS } from "./quickPrompts";
import {
  Avatar,
  Monogram,
  Button,
} from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";
import { useChat } from "@/contexts/ChatContext";
import type {
  ActionSummaryItem,
  ChatMessage,
  PersonaHit,
  ThreadHandoff,
  ServicesPanelPayload,
  ToolCallState,
} from "./types";
import {
  extractCallResults,
  extractHandoffs,
  extractPageLists,
  extractPersonaHits,
  extractPublishedPages,
} from "./helpers";
import GenUiResult, { LongResponseCard, isLongResponse } from "./GenUiResult";
import ChatInput, { type ChatInputHandle } from "./ChatInput";
import ChatThreadSkeleton from "./ChatThreadSkeleton";
import ChatHistorySidebar from "./ChatHistorySidebar";
import MatchCard from "./MatchCard";
import IntroPreviewModal from "./IntroPreviewModal";
import ApprovalCard, { type PendingApproval } from "./ApprovalCard";
import IncomingRequestCard from "./IncomingRequestCard";
import PublishedPageCard, { PageListCard } from "./PublishedPageCard";
import ServicesPanel from "./ServicesPanel";
import type { CallTarget } from "./ServicesPanel";
import {
  parseSlashCommand,
  runAgentSearch,
  runServiceSearch,
  runServiceCard,
  runServiceCall,
  HELP_TEXT,
} from "@/lib/services-commands";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ─────────────────────────────────────────────────────────────────────
// Subcomponents
// ─────────────────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="typing-indicator" role="status" aria-label="Persona is typing">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  );
}

function ActionSummaryBlock({ items }: { items: ActionSummaryItem[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="action-summary" aria-label="Action summary">
      {items.map((item, i) => (
        <div key={i} className={`action-summary-item action-summary-item--${item.status}`}>
          <span className="action-summary-icon" aria-hidden="true">
            {item.icon || {
              done: "✅",
              pending: "⏳",
              waiting: "⏳",
              error: "⚠️",
              none: "📅",
            }[item.status]}
          </span>
          <span className="action-summary-label">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

// Friendly progress labels so a multi-step turn shows what's actually
// happening ("Searching…", "Ranking matches…", "Sending a connection
// request…") instead of a silent spinner or a raw tool name like "Running
// find best intro for me". Each entry lights up live as its tool call
// starts and clears when the next one does — this is what actually
// produces a "Searching... Ranking matches... Preparing outreach..."-style
// sequence for a compound request, driven by the real tool calls as they
// execute rather than a fabricated fixed script.
const TOOL_PROGRESS_LABELS: Record<string, string> = {
  // Zynd network — discovery & connections
  search_zynd_network: "Looking for a matching agent or service",
  search_zynd_personas: "Looking for a matching person",
  search_zynd_services: "Looking for a matching service",
  get_zynd_service_card: "Reading the agent's details",
  get_persona_profile: "Reading their profile",
  call_zynd_service: "Calling the agent",
  call_zynd_agent: "Calling the agent",
  message_zynd_agent: "Messaging the agent",
  request_connection: "Sending a connection request",
  list_my_connections: "Checking your connections",
  check_connection_status: "Checking connection status",
  read_agent_channel: "Reading the conversation",
  // Meetings
  propose_meeting: "Proposing meeting times",
  propose_group_meeting: "Proposing meeting times",
  respond_to_meeting: "Responding to the meeting",
  list_pending_meetings: "Checking pending meetings",
  smart_group_schedule: "Checking everyone's calendars",
  // Network intros / matching
  find_best_intro_for_me: "Searching and ranking matches",
  check_network_overlap: "Checking what you have in common",
  // Memory & digital twin
  what_do_you_know_about_me: "Checking what I remember",
  remember_this: "Saving that",
  forget_this: "Forgetting that",
  answer_like_me: "Thinking it through",
  delegate_to_my_persona: "Working on it",
  what_do_i_really_know_about: "Digging through memory",
  refresh_my_style: "Updating your communication style",
  // Calendar
  create_calendar_event: "Creating the calendar event",
  list_calendar_events: "Checking your calendar",
  delete_calendar_event: "Removing the event",
  // Todos & brief
  add_todo: "Adding to your todos",
  append_to_my_brief: "Updating your brief",
  read_my_brief: "Reading your brief",
  replace_my_brief: "Updating your brief",
  clear_my_brief: "Clearing your brief",
  // Pages
  publish_page: "Publishing your page",
  update_page: "Updating your page",
  list_my_pages: "Checking your pages",
  // Google Docs / Sheets / Drive
  create_google_doc: "Creating the document",
  read_google_doc: "Reading the document",
  append_to_google_doc: "Updating the document",
  search_google_docs: "Searching your documents",
  list_google_docs: "Checking your documents",
  create_google_sheet: "Creating the spreadsheet",
  read_google_sheet_values: "Reading the spreadsheet",
  append_to_google_sheet: "Updating the spreadsheet",
  search_google_spreadsheets: "Searching your spreadsheets",
  create_google_drive_folder: "Creating the folder",
  list_google_drive_files: "Checking your files",
  list_google_drive_folder_contents: "Checking the folder",
  move_google_drive_file: "Moving the file",
  // Gmail
  send_gmail_email: "Sending the email",
  search_gmail_emails: "Searching your inbox",
  get_gmail_email_details: "Reading the email",
  list_recent_gmail_threads: "Checking recent emails",
  // Notion
  create_notion_page: "Creating the Notion page",
  update_notion_page: "Updating the Notion page",
  get_notion_page_content: "Reading the Notion page",
  append_notion_blocks: "Updating the Notion page",
  create_notion_database: "Creating the Notion database",
  get_notion_database: "Reading the Notion database",
  query_notion_database: "Searching Notion",
  search_notion: "Searching Notion",
  // LinkedIn
  post_to_linkedin: "Posting to LinkedIn",
  read_linkedin_profile: "Reading your LinkedIn profile",
  read_linkedin_dms: "Checking LinkedIn messages",
  send_linkedin_dm: "Sending a LinkedIn message",
  // Twitter / X
  post_tweet: "Posting to X",
  read_timeline: "Checking your timeline",
  read_twitter_dms: "Checking your messages",
  send_twitter_dm: "Sending a message",
  // General utility
  internet_search: "Searching the web",
  webpage_scrape: "Reading the page",
  get_current_time: "Checking the time",
  calculate: "Calculating",
};

function ToolProgress({ toolCalls }: { toolCalls: ToolCallState[] }) {
  // Show the most recent still-running tool (the one we're waiting on).
  const active = [...toolCalls].reverse().find((t) => t.status === "running");
  const label = active
    ? TOOL_PROGRESS_LABELS[active.name] ||
      `Running ${active.name.replace(/_/g, " ")}`
    : null;
  // Show a friendly label even after the last tool finishes (composing reply).
  const text = label || "Working on it";
  // Append the called agent's entity id tail when it's an agent call.
  return (
    <div className="tool-progress" role="status">
      <span className="tool-progress-spin" />
      <span className="tool-progress-label">{text}…</span>
    </div>
  );
}

function MatchCardRow({
  hits,
  busyId,
  onSayHi,
}: {
  hits: PersonaHit[];
  busyId: string | null;
  onSayHi: (hit: PersonaHit) => void;
}) {
  if (hits.length === 0) return null;
  return (
    <div className="match-card-row">
      <div className="match-row-label caption">a few worth a look</div>
      {hits.map((hit) => (
        <MatchCard
          key={hit.agent_id}
          hit={hit}
          busy={busyId === hit.agent_id}
          onSayHi={() => onSayHi(hit)}
          reason={
            hit.match_reason
              ? hit.match_reason.charAt(0).toUpperCase() + hit.match_reason.slice(1)
              : undefined
          }
        />
      ))}
    </div>
  );
}

function HandoffCards({
  handoffs,
  busyId,
  onAct,
}: {
  handoffs: ThreadHandoff[];
  busyId: string | null;
  onAct: (h: ThreadHandoff) => void;
}) {
  if (handoffs.length === 0) return null;
  return (
    <div className="inline-cards">
      {handoffs.map((h) => {
        const isMeeting = h.source_tool === "propose_meeting";
        const headline =
          h.source_tool === "request_connection"
            ? `I reached out${h.partner_name ? ` to ${h.partner_name}` : ""}.`
            : isMeeting
              ? `I proposed times${h.partner_name ? ` to ${h.partner_name}` : ""}.`
              : `I sent a message${h.partner_name ? ` to ${h.partner_name}` : ""}.`;
        const sub = isMeeting
          ? "They can accept, counter, or decline from the thread."
          : "It's still in my hands — take it over to reply yourself.";
        return (
          <div key={`${h.source_tool}-${h.thread_id}`} className="inline-card handoff-card">
            <div className="info">
              <div className="name italic-pull accent-text">{headline}</div>
              <div className="body-s secondary">{sub}</div>
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={busyId === h.thread_id}
              onClick={() => onAct(h)}
              rightIcon={<ExternalLink size={14} strokeWidth={1.5} />}
            >
              {busyId === h.thread_id
                ? "Opening…"
                : isMeeting
                  ? "View"
                  : "Take over"}
            </Button>
          </div>
        );
      })}
    </div>
  );
}

/** Patch the last "call"-kind message matching `entityId`. Matching on
 *  entityId (not just "the last call message") keeps two open call forms
 *  for different agents from clobbering each other. */
function updateLastCall(
  prev: ChatMessage[],
  entityId: string,
  patch: (s: ServicesPanelPayload) => ServicesPanelPayload,
): ChatMessage[] {
  const out = prev.slice();
  const idx = out.findLastIndex(
    (m) => m.services?.kind === "call" && m.services.entityId === entityId,
  );
  if (idx >= 0 && out[idx].services) {
    out[idx] = { ...out[idx], services: patch(out[idx].services as ServicesPanelPayload) };
  }
  return out;
}

function MessageRowInner({
  message,
  messageIndex,
  busyId,
  onSayHi,
  onActOnHandoff,
  onCardLookup,
  onCallAgent,
  onCall,
  onAskPersona,
  userId,
  userName,
  userAvatarUrl,
  onIncomingReplied,
}: {
  message: ChatMessage;
  /** Row index in the message list — passed so the stable onIncomingReplied
   *  callback can target the correct slot without an inline closure. */
  messageIndex: number;
  busyId: string | null;
  onSayHi: (h: PersonaHit) => void;
  onActOnHandoff: (h: ThreadHandoff) => void;
  onCardLookup: (entityId: string) => void;
  onCallAgent: (target: CallTarget) => void;
  onCall: (entityId: string, args: { text?: string; data?: Record<string, unknown> }) => void;
  onAskPersona: (target: CallTarget & { intent?: string }) => void;
  userId: string;
  userName: string;
  userAvatarUrl: string | null;
  onIncomingReplied: (index: number) => void;
}) {
  if (message.incoming) {
    return (
      <IncomingRequestCard
        request={message.incoming}
        userId={userId}
        onReplied={() => onIncomingReplied(messageIndex)}
      />
    );
  }

  // Slash-command result panels are pure system-side renders — no avatar,
  // no bubble wrapper, just the inline cards.
  if (message.services && message.role === "assistant") {
    return (
      <div className="services-panel-wrap">
        <ServicesPanel
          payload={message.services}
          onCardLookup={onCardLookup}
          onCallAgent={onCallAgent}
          onCall={onCall}
          onAskPersona={onAskPersona}
        />
      </div>
    );
  }

  const isAria = message.role === "assistant";
  const personaHits = isAria ? extractPersonaHits(message.actions) : [];
  const handoffs = isAria ? extractHandoffs(message.actions) : [];
  const callResults = isAria
    ? extractCallResults(message.actions, message.toolCalls)
    : [];
  const publishedPages = isAria ? extractPublishedPages(message.actions) : [];
  const pageList = isAria ? extractPageLists(message.actions) : null;
  const activeTools = (message.toolCalls || []).length > 0;
  const showTyping = isAria && !!message.streaming && !message.content;

  return (
    <>
      <div className={`msg ${isAria ? "aria" : "user"}`}>
        {isAria && <Monogram size="sm" />}
        <div className="bubble">
          {showTyping &&
            (activeTools ? (
              <ToolProgress toolCalls={message.toolCalls || []} />
            ) : (
              <TypingIndicator />
            ))}
          {message.content &&
            (isAria && isLongResponse(message.content) ? (
              <LongResponseCard
                markdown={message.content}
                streaming={message.streaming}
              />
            ) : (
              <div className="markdown-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            ))}
          {message.error && (
            <p className="msg-error body-s">⚠ {message.error}</p>
          )}
        </div>
        {!isAria && (
          <span className="msg-user-avatar" aria-label={userName}>
            <Avatar size="sm" src={userAvatarUrl} name={userName} />
          </span>
        )}
      </div>
      {isAria && message.actionSummary && message.actionSummary.length > 0 && (
        <ActionSummaryBlock items={message.actionSummary} />
      )}
      {callResults.length > 0 && (
        <div className="genui-stack">
          {callResults.map((r, i) => (
            <div className="genui-wrap" key={`${r.entity_id}-${i}`}>
              <GenUiResult
                result={r}
                title={
                  r.entity_id?.startsWith("zns:svc:")
                    ? "Service result"
                    : "Agent result"
                }
              />
            </div>
          ))}
        </div>
      )}
      {personaHits.length > 0 && (
        <MatchCardRow
          hits={personaHits}
          busyId={busyId}
          onSayHi={onSayHi}
        />
      )}
      {handoffs.length > 0 && (
        <HandoffCards
          handoffs={handoffs}
          busyId={busyId}
          onAct={onActOnHandoff}
        />
      )}
      {publishedPages.length > 0 && (
        <div className="inline-cards">
          {publishedPages.map((page) => (
            <PublishedPageCard key={page.slug} result={page} />
          ))}
        </div>
      )}
      {pageList !== null && (
        <div className="inline-cards">
          <PageListCard pages={pageList} />
        </div>
      )}
    </>
  );
}

// Memoized so only the message that actually changed (the streaming tail)
// re-renders on each token — avoids re-running extractCallResults /
// extractPersonaHits / isLongResponse on every other message in the thread.
const MessageRow = memo(MessageRowInner);

// ─────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────

export default function ChatInterface() {
  const router = useRouter();
  const { user } = useDashboard();
  // Chat history + conversation id live in ChatProvider so they persist
  // across dashboard navigation. Local-only state (input, busy flags,
  // expanded thinking panels) stays here — they're per-mount.
  const {
    messages,
    setMessages,
    conversationId,
    setConversationId,
    hydrated,
  } = useChat();
  // The chat draft lives inside ChatInput (so keystrokes don't re-render the
  // thread). We only need an imperative handle to clear/focus it.
  const chatInputRef = useRef<ChatInputHandle>(null);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  // Holds the in-flight SSE fetch's abort handle so the Stop button (and
  // Escape key in ChatInput) can cancel a streaming reply. Cleared on
  // completion / error.
  const abortRef = useRef<AbortController | null>(null);

  // Guards against a stale stream corrupting a different conversation's
  // messages. Scenario: send a message, don't wait for it, then hit "New
  // chat" or open a past session from the history sidebar — the abandoned
  // fetch keeps running and its events still arrive. Without this check,
  // updateStreaming's "no message is flagged streaming, so patch the last
  // one" fallback (needed for legitimate mid-turn card insertions) would
  // instead silently overwrite the newly-loaded, already-complete
  // conversation's last assistant message with leftover deltas.
  const liveConversationIdRef = useRef(conversationId);
  useEffect(() => {
    if (liveConversationIdRef.current === conversationId) return;
    liveConversationIdRef.current = conversationId;
    // The conversation on screen just changed from under an in-flight (or
    // just-finished) send. Release the input immediately rather than
    // leaving it disabled until that abandoned background fetch happens
    // to finish — the guard above already keeps its trailing updates from
    // touching whatever's now displayed, so there's nothing left to wait
    // on from this screen's point of view.
    setLoading(false);
  }, [conversationId]);
  const sendConversationIdRef = useRef<string | null>(null);

  // S10 intro modal state. Holds the persona we're drafting an intro to.
  const [introTarget, setIntroTarget] = useState<PersonaHit | null>(null);
  const [myPersonaName, setMyPersonaName] = useState<string>("");
  const [toast, setToast] = useState<string | null>(null);

  // Pending approvals — orchestrator stages commitment-class tool calls
  // here, surfaced as sticky cards above the chat thread.
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);

  const fetchApprovals = useCallback(async () => {
    if (!user) return;
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) return;
      const res = await fetch(`${API}/api/approvals/`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      setApprovals(data.approvals || []);
    } catch {
      /* ignore — best effort */
    }
  }, [user]);

  // Initial fetch + realtime subscription on pending_approvals so a
  // freshly-staged approval (e.g. while the user is typing) appears
  // without needing a poll cycle.
  useEffect(() => {
    if (!user) return;
    void fetchApprovals();
    const sb = getSupabase();
    const channel = sb
      .channel(`approvals-${user.id}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "pending_approvals",
          filter: `user_id=eq.${user.id}`,
        },
        () => { void fetchApprovals(); },
      )
      .subscribe();
    return () => {
      sb.removeChannel(channel);
    };
  }, [user, fetchApprovals]);

  // Note: the global callback_results subscription lives in
  // ChatProvider so a reply that arrives while the user is on a
  // different page still gets injected into the shared thread state
  // by the time they navigate back here.

  const decideApproval = useCallback(
    async (approvalId: string, decision: "approve" | "decline") => {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) throw new Error("Not signed in");
      const res = await fetch(`${API}/api/approvals/${approvalId}/decide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({ decision }),
      });
      if (!res.ok) throw new Error((await res.text()) || "Couldn't decide");
      // Optimistic local update — realtime will reconcile.
      setApprovals((prev) => prev.filter((a) => a.id !== approvalId));
      setToast(
        decision === "approve"
          ? "Done — I'll let them know."
          : "Declined — I told them you can't commit right now.",
      );
      setTimeout(() => setToast(null), 3500);
    },
    [],
  );

  const bottomRef = useRef<HTMLDivElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  // Whether the user is parked at the bottom. We only auto-scroll when pinned,
  // so reading a big card mid-stream isn't yanked back down on every token.
  const pinnedRef = useRef(true);
  const handleThreadScroll = useCallback(() => {
    const el = threadRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  // Fetch the user's persona name once so the intro draft can sign as them.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/persona/${user.id}/status`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data.deployed && typeof data.name === "string") {
          setMyPersonaName(data.name);
        }
      } catch {
        /* ignore — modal falls back to "my person" */
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  // Note: chat history hydration lives in ChatProvider — runs once
  // per signed-in user at dashboard mount, so navigating back to
  // /dashboard/chat doesn't trigger a refetch or flash a loader.

  const displayMessages = messages;

  useEffect(() => {
    if (!pinnedRef.current) return;
    const streaming = displayMessages[displayMessages.length - 1]?.streaming;
    // Instant during streaming (no smooth-scroll thrash on every token); smooth
    // once a turn settles.
    bottomRef.current?.scrollIntoView({ behavior: streaming ? "auto" : "smooth" });
  }, [displayMessages]);

  const updateStreaming = useCallback(
    (patch: (m: ChatMessage) => ChatMessage) => {
      // The conversation this stream was sent into is no longer the one
      // on screen — ignore. See the sendConversationIdRef comment above.
      if (sendConversationIdRef.current !== liveConversationIdRef.current) return;
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const out = prev.slice();
        // Find the most recent streaming assistant message (the "tail").
        // This is more robust than only looking at the very last item when
        // search-card messages are inserted just before the streaming reply.
        const tailIdx = out.findLastIndex(
          (m) => m.role === "assistant" && m.streaming,
        );
        const lastIdx = tailIdx >= 0 ? tailIdx : out.length - 1;
        if (out[lastIdx].role !== "assistant") return prev;
        out[lastIdx] = patch(out[lastIdx]);
        return out;
      });
    },
    [],
  );

  // Render network-search tool results from plain chat as clickable cards,
  // inserted just before the streaming assistant bubble. Mirrors the shape
  // the /agents slash command produces so the same ServicesPanel + Call
  // buttons light up. Services-only searches map too.
  //
  // search_zynd_personas is deliberately NOT handled here — it already gets
  // its own dedicated "a few worth a look" MatchCard row (see
  // extractPersonaHits/MatchCardRow below), which is the friendlier,
  // avatar+reason card built specifically for people results. Rendering it
  // a second time here as a generic technical row (raw zns: id, "View
  // card"/"Let my persona handle it" buttons meant for callable
  // agents/services) just duplicated the same search 2-3x in one turn —
  // once as this block, once as prose, once as MatchCard.
  const maybeInsertSearchCards = useCallback(
    (event: Record<string, unknown>) => {
      // Same staleness guard as updateStreaming — this bypasses it with
      // its own setMessages call, so needs the check independently.
      if (sendConversationIdRef.current !== liveConversationIdRef.current) return;
      const tool = event.name as string | undefined;
      const result = event.result as Record<string, unknown> | undefined;
      if (!tool || !result || typeof result !== "object") return;
      const rows = result.results;
      if (!Array.isArray(rows) || rows.length === 0) return;

      let panel: ServicesPanelPayload | null = null;
      const query =
        (result.query_used as string) || (result.query as string) || "";

      if (tool === "search_zynd_network") {
        panel = {
          kind: "agents",
          query,
          agents: {
            status: "success",
            count: rows.length,
            total_available: result.total_available as number | undefined,
            by_kind: result.by_kind as Record<string, number> | undefined,
            results: rows as never[],
          },
        };
      } else if (tool === "search_zynd_services") {
        panel = {
          kind: "search",
          query,
          search: {
            status: "success",
            count: rows.length,
            results: rows as never[],
          },
        };
      }
      if (!panel) return;

      const cardMsg: ChatMessage = { role: "assistant", content: "", services: panel };
      // Insert before the trailing streaming assistant message so the prose
      // reply stays at the bottom.
      setMessages((prev) => {
        if (prev.length === 0) return [cardMsg];
        const lastIdx = prev.length - 1;
        if (prev[lastIdx].role === "assistant" && prev[lastIdx].streaming) {
          const out = prev.slice();
          out.splice(lastIdx, 0, cardMsg);
          return out;
        }
        return [...prev, cardMsg];
      });
    },
    [setMessages],
  );

  const handleStreamEvent = useCallback(
    (event: Record<string, unknown>) => {
      const type = event.type as string;
      switch (type) {
        case "text":
          updateStreaming((m) => ({
            ...m,
            content: (m.content || "") + ((event.delta as string) || ""),
          }));
          break;
        case "thinking":
          updateStreaming((m) => ({
            ...m,
            thinking: (m.thinking || "") + ((event.delta as string) || ""),
          }));
          break;
        case "tool_call_start":
          updateStreaming((m) => ({
            ...m,
            toolCalls: [
              ...(m.toolCalls || []),
              {
                id: event.id as string,
                name: event.name as string,
                argsText: "",
                status: "running",
              },
            ],
          }));
          break;
        case "tool_call_args":
          updateStreaming((m) => ({
            ...m,
            toolCalls: (m.toolCalls || []).map((tc) =>
              tc.id === event.id
                ? { ...tc, argsText: tc.argsText + ((event.args_delta as string) || "") }
                : tc,
            ),
          }));
          break;
        case "tool_call_end":
          updateStreaming((m) => ({
            ...m,
            toolCalls: (m.toolCalls || []).map((tc) =>
              tc.id === event.id
                ? {
                    ...tc,
                    arguments: event.arguments as Record<string, unknown>,
                  }
                : tc,
            ),
          }));
          break;
        case "tool_result": {
          const isErr =
            typeof event.result === "object" &&
            event.result !== null &&
            "error" in (event.result as Record<string, unknown>);
          updateStreaming((m) => ({
            ...m,
            toolCalls: (m.toolCalls || []).map((tc) =>
              tc.id === event.id
                ? {
                    ...tc,
                    result: event.result,
                    status: isErr ? "error" : "done",
                  }
                : tc,
            ),
          }));
          // When the persona searched the network in plain chat, render the
          // same clickable result cards (with Call buttons) the /agents
          // command shows — inserted just above the streaming reply bubble.
          maybeInsertSearchCards(event);
          break;
        }
        case "text_to_thinking":
          // The current iteration ended with tool calls. Move whatever text
          // streamed into `content` over to the `thinking` block so the
          // visible bubble doesn't briefly show pre-tool-call reasoning.
          updateStreaming((m) => {
            const moved = m.content || "";
            if (!moved) return m;
            const sep = m.thinking ? "\n\n" : "";
            return {
              ...m,
              thinking: (m.thinking || "") + sep + moved,
              content: "",
            };
          });
          break;
        case "error":
          updateStreaming((m) => ({
            ...m,
            error: (event.message as string) || "stream error",
            toolCalls: [],
            streaming: false,
          }));
          break;
        case "done":
          // Only adopt the server's id if the user hasn't since switched
          // away (New chat / history load) — otherwise this would snap
          // their view back to the abandoned conversation.
          if (
            typeof event.conversation_id === "string" &&
            sendConversationIdRef.current === liveConversationIdRef.current
          ) {
            setConversationId(event.conversation_id);
          }
          updateStreaming((m) => ({
            ...m,
            content: (event.reply as string) || m.content,
            actions: event.actions_taken as ChatMessage["actions"],
            actionSummary: event.action_summary as ChatMessage["actionSummary"],
            toolCalls: [],
            streaming: false,
          }));
          break;
      }
    },
    [updateStreaming, maybeInsertSearchCards],
  );

  // Slash commands (e.g. `/services translate text`) are intercepted and
  // run against /api/services/* directly — they bypass the LLM and render
  // structured cards inline. Returns true when the message was a command
  // and was handled; false to let the normal LLM flow proceed.
  const tryHandleSlashCommand = useCallback(
    async (text: string): Promise<boolean> => {
      const cmd = parseSlashCommand(text);
      if (!cmd) return false;

      const userMsg: ChatMessage = { role: "user", content: text };

      if (cmd.kind === "help") {
        setMessages((prev) => [
          ...prev,
          userMsg,
          {
            role: "assistant",
            content: "",
            services: { kind: "help", helpText: HELP_TEXT },
          },
        ]);
        return true;
      }

      if (cmd.kind === "invalid") {
        setMessages((prev) => [
          ...prev,
          userMsg,
          {
            role: "assistant",
            content: "",
            services: { kind: "error", error: cmd.hint },
          },
        ]);
        return true;
      }

      // /agents <query>
      if (cmd.kind === "agents") {
        const placeholder: ChatMessage = {
          role: "assistant",
          content: "",
          services: { kind: "agents", query: cmd.query, loading: true },
        };
        setMessages((prev) => [...prev, userMsg, placeholder]);
        try {
          const agents = await runAgentSearch(cmd.query);
          setMessages((prev) => {
            const out = prev.slice();
            // Find the loading placeholder from the end — robust to a
            // message landing after it while the search was in flight.
            const idx = out.findLastIndex(
              (m) => m.services?.kind === "agents" && m.services.loading,
            );
            if (idx >= 0) {
              out[idx] = {
                ...out[idx],
                services: { kind: "agents", query: cmd.query, agents },
              };
            }
            return out;
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Search failed.";
          setMessages((prev) => {
            const out = prev.slice();
            const idx = out.findLastIndex(
              (m) => m.services?.kind === "agents" && m.services.loading,
            );
            if (idx >= 0) {
              out[idx] = { ...out[idx], services: { kind: "error", error: msg } };
            }
            return out;
          });
        }
        return true;
      }

      // /services <query>
      if (cmd.kind === "services") {
        const placeholder: ChatMessage = {
          role: "assistant",
          content: "",
          services: { kind: "search", query: cmd.query, loading: true },
        };
        setMessages((prev) => [...prev, userMsg, placeholder]);
        try {
          const search = await runServiceSearch(cmd.query);
          setMessages((prev) => {
            const out = prev.slice();
            const idx = out.length - 1;
            if (out[idx]?.services?.kind === "search") {
              out[idx] = {
                ...out[idx],
                services: { kind: "search", query: cmd.query, search },
              };
            }
            return out;
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Search failed.";
          setMessages((prev) => {
            const out = prev.slice();
            const idx = out.length - 1;
            if (out[idx]?.services) {
              out[idx] = { ...out[idx], services: { kind: "error", error: msg } };
            }
            return out;
          });
        }
        return true;
      }

      // /card <entity_id>
      if (cmd.kind === "card") {
        const placeholder: ChatMessage = {
          role: "assistant",
          content: "",
          services: { kind: "card", entityId: cmd.entityId, loading: true },
        };
        setMessages((prev) => [...prev, userMsg, placeholder]);
        try {
          const card = await runServiceCard(cmd.entityId);
          setMessages((prev) => {
            const out = prev.slice();
            const idx = out.length - 1;
            if (out[idx]?.services?.kind === "card") {
              out[idx] = {
                ...out[idx],
                services: { kind: "card", entityId: cmd.entityId, card },
              };
            }
            return out;
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Couldn't load card.";
          setMessages((prev) => {
            const out = prev.slice();
            const idx = out.length - 1;
            if (out[idx]?.services) {
              out[idx] = { ...out[idx], services: { kind: "error", error: msg } };
            }
            return out;
          });
        }
        return true;
      }

      return false;
    },
    [setMessages],
  );

  // Triggered by "View card" buttons inside service search results.
  // Appends a new card-payload message rather than mutating the search.
  const handleCardLookup = useCallback(
    async (entityId: string) => {
      const placeholder: ChatMessage = {
        role: "assistant",
        content: "",
        services: { kind: "card", entityId, loading: true },
      };
      setMessages((prev) => [...prev, placeholder]);
      try {
        const card = await runServiceCard(entityId);
        setMessages((prev) => {
          const out = prev.slice();
          const idx = out.length - 1;
          if (out[idx]?.services?.kind === "card") {
            out[idx] = {
              ...out[idx],
              services: { kind: "card", entityId, card },
            };
          }
          return out;
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Couldn't load card.";
        setMessages((prev) => {
          const out = prev.slice();
          const idx = out.length - 1;
          if (out[idx]?.services) {
            out[idx] = { ...out[idx], services: { kind: "error", error: msg } };
          }
          return out;
        });
      }
    },
    [setMessages],
  );

  // Open the schema-driven Call form: append a "call"-kind message and
  // fetch the card to drive the form. Mirrors handleCardLookup.
  const handleCallAgent = useCallback(
    async ({ entityId, name, kind }: CallTarget) => {
      const placeholder: ChatMessage = {
        role: "assistant",
        content: "",
        services: {
          kind: "call",
          entityId,
          callName: name,
          callKind: kind,
          callLoading: true,
        },
      };
      setMessages((prev) => [...prev, placeholder]);
      try {
        const card = await runServiceCard(entityId);
        setMessages((prev) =>
          updateLastCall(prev, entityId, (s) => ({
            ...s,
            callLoading: false,
            card,
            callName: name || card.name,
          })),
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Couldn't load the form.";
        setMessages((prev) =>
          updateLastCall(prev, entityId, (s) => ({
            ...s,
            callLoading: false,
            callError: msg,
          })),
        );
      }
    },
    [setMessages],
  );

  // Submit a Call form. Result persists on the message payload.
  const handleCall = useCallback(
    async (entityId: string, args: { text?: string; data?: Record<string, unknown> }) => {
      setMessages((prev) =>
        updateLastCall(prev, entityId, (s) => ({
          ...s,
          callSubmitting: true,
          callError: undefined,
          callResult: undefined,
        })),
      );
      try {
        const result = await runServiceCall(entityId, args);
        setMessages((prev) =>
          updateLastCall(prev, entityId, (s) => ({
            ...s,
            callSubmitting: false,
            callResult: result,
          })),
        );
      } catch (e) {
        const msg = e instanceof Error ? e.message : "The call failed.";
        setMessages((prev) =>
          updateLastCall(prev, entityId, (s) => ({
            ...s,
            callSubmitting: false,
            callError: msg,
          })),
        );
      }
    },
    [setMessages],
  );

  const sendMessage = async (text: string) => {
    if (!text || loading) return;

    if (await tryHandleSlashCommand(text)) return;

    // Snapshot which conversation this send targets — updateStreaming
    // compares this against the live value on every event and no-ops once
    // they diverge (New chat / history switch mid-stream).
    sendConversationIdRef.current = conversationId;

    const userMsg: ChatMessage = { role: "user", content: text };
    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      thinking: "",
      toolCalls: [],
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, placeholder]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      const res = await fetch(`${API}/api/chat/stream`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token
            ? { Authorization: `Bearer ${session.access_token}` }
            : {}),
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
          time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      });
      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => "request failed");
        throw new Error(errText);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sepIdx: number;
        while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sepIdx);
          buffer = buffer.slice(sepIdx + 2);
          const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("data: ")) dataLines.push(line.slice(6));
          }
          if (dataLines.length === 0) continue;
          try {
            handleStreamEvent(JSON.parse(dataLines.join("\n")));
          } catch (e) {
            console.error("SSE parse error:", e);
          }
        }
      }
      updateStreaming((m) => ({ ...m, streaming: false }));
    } catch (err) {
      // AbortError == user clicked Stop / hit Esc. Not an error — just
      // close the stream cleanly and leave whatever content arrived.
      const isAbort =
        err instanceof DOMException && err.name === "AbortError";
      if (isAbort) {
        updateStreaming((m) => ({ ...m, streaming: false }));
      } else {
        updateStreaming((m) => ({
          ...m,
          error: err instanceof Error ? err.message : String(err),
          streaming: false,
        }));
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // `sendMessage` is re-created each render (big closure). Hand ChatInput a
  // STABLE wrapper that always calls the latest one, so the memoized ChatInput
  // doesn't re-render on every streamed token.
  const sendMessageRef = useRef(sendMessage);
  sendMessageRef.current = sendMessage;
  const handleSend = useCallback((text: string) => sendMessageRef.current(text), []);

  // Stable callback used by MessageRow (via memo) to mark an incoming request
  // as replied. Takes the message index so the closure doesn't re-create on
  // every render — avoids busting React.memo on unchanged rows.
  const markIncomingReplied = useCallback((idx: number) => {
    setMessages((prev) =>
      prev.map((msg, i) =>
        i === idx && msg.incoming
          ? { ...msg, incoming: { ...msg.incoming, replied: true } }
          : msg,
      ),
    );
  }, [setMessages]);

  // "Let my persona handle it" — hand the request to the LLM chat, which
  // has the search/card/call tools. Plain function (not memoized) so it
  // always closes over the current sendMessage.
  const handleAskPersona = useCallback(({ entityId, name, intent }: CallTarget & { intent?: string }) => {
    const label = name ? `${name} (${entityId})` : entityId;
    const text = intent?.trim()
      ? `Use the Zynd network agent ${label} to ${intent.trim()}`
      : `Use the Zynd network agent ${label} for me — figure out what it does from its card and call it.`;
    void sendMessage(text);
  }, [sendMessage]);

  // S9 → S10: clicking "Say hi" on a match card opens the intro preview
  // modal. The actual send happens through `sendIntro` below; this just
  // stages the target.
  const openIntroForPersona = useCallback((hit: PersonaHit) => {
    setIntroTarget(hit);
  }, []);

  // Two-step send: create the agent-mode thread, post the first message
  // through it. Returns the new thread id so the modal can confirm + the
  // toast can show + we can navigate the user there.
  const sendIntro = async (message: string): Promise<string> => {
    if (!user || !introTarget) throw new Error("Missing context");
    const threadRes = await fetch(`${API}/api/persona/${user.id}/threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_agent_id: introTarget.agent_id,
        target_name: introTarget.name || "Network Agent",
        mode: "agent",
      }),
    });
    if (!threadRes.ok) throw new Error(await threadRes.text());
    const threadData = await threadRes.json();
    const threadId: string | undefined = threadData?.thread?.id;
    if (!threadId) throw new Error("Couldn't open the thread.");

    const sendRes = await fetch(`${API}/api/persona/${user.id}/agent-send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, content: message }),
    });
    if (!sendRes.ok) throw new Error(await sendRes.text());
    // The backend returns 200 even when the receiver rejects (so the
    // sender's local DB row isn't lost). We need to look at the
    // delivery_result body to spot peer-side rejections like
    // "awaiting_acceptance".
    const sendData = await sendRes.json().catch(() => null);
    const delivery = sendData?.delivery;
    if (delivery && delivery.delivered === false) {
      const reason = delivery.error_reason || delivery.error || "delivery_failed";
      if (reason === "awaiting_acceptance") {
        throw new Error(
          "I sent the connection request — they need to accept before I can deliver the message. " +
            "I'll try again automatically once they do.",
        );
      }
      throw new Error(`The other agent rejected the message (${reason}).`);
    }
    return threadId;
  };

  const onIntroSent = (threadId: string) => {
    const targetName = introTarget?.name || "their assistant";
    setIntroTarget(null);
    setToast(`Sent to ${targetName}'s assistant · just now.`);
    // Stay on Home — the eventual reply arrives over the
    // callback_results realtime channel and renders inline.
    // Thread id is logged for debug; the user can still open the DM
    // surface from the Threads tab if they want to.
    void threadId;
    setTimeout(() => setToast(null), 3500);
  };

  // For meeting hand-offs: just navigate (keep AI mode). For DM hand-offs:
  // flip to human mode then navigate.
  const actOnHandoff = useCallback(async (h: ThreadHandoff) => {
    setBusyId(h.thread_id);
    try {
      if (h.source_tool !== "propose_meeting") {
        await fetch(`${API}/api/persona/threads/${h.thread_id}/mode`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "human" }),
        });
      }
    } catch (e) {
      console.error("actOnHandoff failed:", e);
    } finally {
      setBusyId(null);
      router.push(`/dashboard/messages?thread=${h.thread_id}`);
    }
  }, [router]);

  // No messages + history not yet hydrated → still loading (show skeleton).
  // No messages + hydrated → genuinely empty (show the welcome hero).
  const isEmpty = messages.length === 0;
  const isLoadingHistory = isEmpty && !hydrated;

  return (
    <>
      <div className="chat-area">
        {isLoadingHistory ? (
          <ChatThreadSkeleton />
        ) : isEmpty ? (
          <div className="welcome-hero">
            <h1>Welcome to <em>ZyndAI</em></h1>
            <p className="welcome-sub">
              Tell your Persona what&apos;s on your mind. It&apos;ll find people worth meeting,
              reach out on your behalf, and book the times.
            </p>
            <div className="action-grid">
              {QUICK_PROMPTS.map((card) => {
                const Icon = card.icon;
                return (
                  <button
                    key={card.label}
                    type="button"
                    className="action-card"
                    onClick={() => sendMessage(card.send)}
                    disabled={loading}
                  >
                    <span className={`action-icon ${card.tone}`}>
                      <Icon />
                    </span>
                    <span className="action-label">{card.label}</span>
                    <span className="action-plus"><Plus /></span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="chat-thread" ref={threadRef} onScroll={handleThreadScroll}>
            {approvals.length > 0 && (
              <div className="approvals-stack">
                {approvals.map((a) => (
                  <ApprovalCard
                    key={a.id}
                    approval={a}
                    onDecide={decideApproval}
                  />
                ))}
              </div>
            )}
            {displayMessages.map((m, i) => (
              <MessageRow
                key={i}
                message={m}
                messageIndex={i}
                busyId={busyId}
                onSayHi={openIntroForPersona}
                onActOnHandoff={actOnHandoff}
                onCardLookup={handleCardLookup}
                onCallAgent={handleCallAgent}
                onCall={handleCall}
                onAskPersona={handleAskPersona}
                userId={user?.id || ""}
                userName={
                  user?.user_metadata?.full_name ||
                  user?.user_metadata?.name ||
                  user?.email?.split("@")[0] ||
                  "You"
                }
                userAvatarUrl={
                  user?.user_metadata?.avatar_url ||
                  user?.user_metadata?.picture ||
                  null
                }
                onIncomingReplied={markIncomingReplied}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
        <ChatInput
          ref={chatInputRef}
          onSend={handleSend}
          onStop={stopStreaming}
          streaming={loading}
          disabled={loading}
        />
      </div>

      <ChatHistorySidebar />

      {introTarget && (
        <IntroPreviewModal
          target={introTarget}
          myName={myPersonaName}
          onClose={() => setIntroTarget(null)}
          onSent={onIntroSent}
          send={sendIntro}
        />
      )}

      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}
