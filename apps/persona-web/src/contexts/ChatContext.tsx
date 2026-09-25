"use client";

/**
 * Cross-page chat state. Lives at the dashboard-layout level so the
 * home thread survives navigation between /dashboard/chat and any
 * other dashboard page — the user comes back and sees their messages
 * still there, no flash of "Hi. Still reading the network…", no
 * second `/api/chat/history` round-trip.
 *
 * Also owns the global `callback_results` realtime subscription so
 * an A2A reply that arrives while the user is on a different page
 * still gets injected into the chat thread by the time they open it.
 * (TaskToasts also subscribes for the cross-page toast — those are
 * complementary, not redundant.)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";
import type { ChatMessage } from "@/components/chat/types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** localStorage key for the active conversation id, per user. Persists
 * "New chat" across a refresh — without this, a refresh before the first
 * message in a new thread would re-fetch /api/chat/history with no id,
 * which falls back to "most recent row in chat_messages" and silently
 * resurrects the old (possibly poisoned) conversation instead. */
const activeConversationKey = (userId: string) => `zynd:active-conversation:${userId}`;

type HistoryRow = {
  role: "user" | "assistant";
  content: string;
  actions?: ChatMessage["actions"];
};

const rowsToMessages = (rows: HistoryRow[]): ChatMessage[] =>
  rows.map((r) => ({
    role: r.role,
    content: r.content,
    actions: r.actions || undefined,
  }));

export interface ChatSession {
  conversation_id: string;
  preview: string;
  updated_at: string;
  message_count: number;
}

interface ChatContextValue {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  conversationId: string | null;
  setConversationId: React.Dispatch<React.SetStateAction<string | null>>;
  /** True until the initial /api/chat/history fetch completes (or fails). */
  hydrated: boolean;
  /**
   * Starts a fresh conversation thread with a new client-generated id
   * (persisted to localStorage so a refresh doesn't lose it — see
   * activeConversationKey below). The old thread's messages stay in the DB
   * untouched, just no longer loaded into context — and become reachable
   * again from the history sidebar via loadConversation. Exists so a model
   * that's gotten stuck repeating a stale claim from earlier in the
   * conversation can be given a clean slate instead of dragging that
   * history into every future turn.
   */
  newChat: () => void;
  /** Switches the active thread to a past conversation_id — used by the
   * history sidebar. Fetches its messages fresh rather than trusting
   * anything already in local state. */
  loadConversation: (id: string) => Promise<void>;
  historyOpen: boolean;
  toggleHistory: () => void;
}

const ChatContext = createContext<ChatContextValue>({
  messages: [],
  setMessages: () => {},
  conversationId: null,
  setConversationId: () => {},
  hydrated: false,
  newChat: () => {},
  loadConversation: async () => {},
  historyOpen: false,
  toggleHistory: () => {},
});

export function useChat() {
  return useContext(ChatContext);
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const { user } = useDashboard();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  // Once we've fetched history for a given user id we don't refetch on
  // every focus event — DashboardContext stabilises the user reference
  // across token refreshes, and this guard catches anything that slips.
  const hydratedFor = useRef<string | null>(null);

  // Initial chat-history hydration. Runs once per signed-in user.
  useEffect(() => {
    if (!user) {
      setMessages([]);
      setConversationId(null);
      setHydrated(false);
      hydratedFor.current = null;
      return;
    }
    if (hydratedFor.current === user.id) return;
    hydratedFor.current = user.id;
    let cancelled = false;
    (async () => {
      try {
        const sb = getSupabase();
        const {
          data: { session },
        } = await sb.auth.getSession();
        if (!session?.access_token) {
          if (!cancelled) setHydrated(true);
          return;
        }
        // If we already know which conversation was active (e.g. "New chat"
        // then a refresh, before any message was sent in it), ask for that
        // exact thread — otherwise the server falls back to "most recent
        // row", which would be the thread the user just left.
        let storedConversationId: string | null = null;
        try {
          storedConversationId = window.localStorage.getItem(activeConversationKey(user.id));
        } catch {
          /* localStorage unavailable */
        }
        const url = storedConversationId
          ? `${API}/api/chat/history?conversation_id=${encodeURIComponent(storedConversationId)}`
          : `${API}/api/chat/history`;
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!res.ok) {
          if (!cancelled) setHydrated(true);
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        if (data.conversation_id) setConversationId(data.conversation_id);
        const rows: HistoryRow[] = data.messages || [];
        if (rows.length > 0) setMessages(rowsToMessages(rows));
      } catch {
        /* ignore — chat just starts fresh */
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  // Global callback_results subscription. Fires for any inbound A2A
  // reply that lands while the user is anywhere in the dashboard.
  // We append the synthesized "Reply from peer" message into the
  // shared messages array so when the user opens the home chat,
  // it's already there. Idempotent on the server side via the
  // unique callback_id.
  useEffect(() => {
    if (!user) return;
    const sb = getSupabase();
    const channel = sb
      .channel(`chat-callback-results-${user.id}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "callback_results",
          filter: `user_id=eq.${user.id}`,
        },
        (payload) => {
          const row = payload.new as {
            id: string;
            reply_text: string | null;
            task_state: string;
            peer_agent_id: string;
          };
          const replyText = row.reply_text?.trim() || "";
          if (!replyText && row.task_state !== "completed") return;
          const peerLabel = row.peer_agent_id.includes(":")
            ? row.peer_agent_id.split(":").pop()!.slice(0, 8)
            : row.peer_agent_id.slice(0, 8);
          const banner =
            row.task_state === "completed"
              ? `Reply from ${peerLabel}`
              : `Update from ${peerLabel} (${row.task_state})`;
          setMessages((prev) => {
            // Idempotency guard — synthesized inline + async push for
            // the same callback_id can't both land here, but realtime
            // can re-deliver an INSERT during a channel reconnect.
            if (prev.some((m) => m.callbackId === row.id)) return prev;
            return [
              ...prev,
              {
                role: "assistant",
                content:
                  replyText.length > 0
                    ? `**${banner}** \n\n${replyText}`
                    : `**${banner}** — they’re processing it.`,
                synthetic: true,
                callbackId: row.id,
              },
            ];
          });
        },
      )
      .subscribe();
    return () => {
      sb.removeChannel(channel);
    };
  }, [user]);

  // Inbound agent-channel messages — when a peer's persona reaches out
  // to ours (over A2A), the server side writes the message into
  // dm_messages with channel='agent'. We subscribe globally so the
  // user notices the request live in the home chat without having to
  // navigate to the Threads page first. Banner links straight to the
  // thread for a manual reply (the thread page handles the actual
  // composer + side-mode toggling).
  useEffect(() => {
    if (!user) return;

    // Resolve our agent_id once so we can filter out our own outbound
    // copies of the same dm_messages rows. Cached for the lifetime of
    // the provider — agent ids don't change once minted.
    let myAgentId: string | null = null;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `${API}/api/persona/${user.id}/status`,
        );
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && typeof data?.agent_id === "string") {
          myAgentId = data.agent_id;
        }
      } catch {
        /* best-effort */
      }
    })();

    const sb = getSupabase();
    const channel = sb
      .channel(`chat-dm-incoming-${user.id}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "dm_messages",
          // Narrows delivery to agent-channel rows only — the handler
          // below only ever acts on `channel === "agent"` anyway, so this
          // was previously firing (and paying an RLS-scoped fetch's worth
          // of client work) for every human-channel row too, table-wide.
          filter: "channel=eq.agent",
        },
        async (payload) => {
          const row = payload.new as {
            id: string;
            thread_id: string;
            sender_id: string;
            sender_type: string;
            channel: string;
            content: string;
          };
          // Only agent-channel inbound (our orchestrator's own replies
          // are also written into dm_messages with our agent_id as
          // sender — those we skip).
          if (row.channel !== "agent") return;
          if (!myAgentId || row.sender_id === myAgentId) return;

          // Only surface the card when OUR side of the thread is in
          // human mode. In agent mode (the default), the orchestrator
          // is already handling the inbound autonomously — popping a
          // composer would force the user to type a reply that's
          // about to be answered by their AI anyway.
          let shouldShow = false;
          try {
            const t = await sb
              .from("dm_threads")
              .select("initiator_id,receiver_id,initiator_mode,receiver_mode")
              .eq("id", row.thread_id)
              .limit(1)
              .maybeSingle();
            const thread = t.data as
              | {
                  initiator_id: string;
                  receiver_id: string;
                  initiator_mode: string;
                  receiver_mode: string;
                }
              | null;
            if (thread) {
              const ourSide =
                thread.initiator_id === myAgentId
                  ? "initiator"
                  : thread.receiver_id === myAgentId
                    ? "receiver"
                    : null;
              if (ourSide) {
                const mode =
                  ourSide === "initiator"
                    ? thread.initiator_mode
                    : thread.receiver_mode;
                shouldShow = mode === "human";
              }
            }
          } catch {
            /* swallow — better to show nothing than spam */
          }
          if (!shouldShow) return;

          const peerLabel = row.sender_id.includes(":")
            ? row.sender_id.split(":").pop()!.slice(0, 8)
            : row.sender_id.slice(0, 8);

          setMessages((prev) => {
            if (prev.some((m) => m.callbackId === `dm:${row.id}`)) return prev;
            return [
              ...prev,
              {
                role: "assistant",
                content: "",  // rendered by IncomingRequestCard, not markdown
                synthetic: true,
                callbackId: `dm:${row.id}`,
                incoming: {
                  threadId: row.thread_id,
                  messageId: row.id,
                  peerLabel,
                  body: row.content,
                },
              },
            ];
          });
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      sb.removeChannel(channel);
    };
  }, [user]);

  const [historyOpen, setHistoryOpen] = useState(false);
  const toggleHistory = useCallback(() => setHistoryOpen((v) => !v), []);

  const newChat = useCallback(() => {
    // Mint the id client-side (rather than null) so it can be persisted
    // immediately — a refresh before the first message is sent still needs
    // something concrete to ask /api/chat/history for. The backend accepts
    // this id as-is on the next /api/chat/stream call (see
    // handle_user_message_stream in orchestrator.py), same as if it had
    // generated one itself.
    const id = crypto.randomUUID();
    setMessages([]);
    setConversationId(id);
    setHistoryOpen(false);
    if (user) {
      try {
        window.localStorage.setItem(activeConversationKey(user.id), id);
      } catch {
        /* localStorage unavailable */
      }
    }
  }, [user]);

  // Keep localStorage in sync whenever the active conversation changes for
  // any other reason too — e.g. the very first message of a brand-new
  // session, where the id comes from the server's "done" event rather than
  // from newChat() above.
  useEffect(() => {
    if (!user || !conversationId) return;
    try {
      window.localStorage.setItem(activeConversationKey(user.id), conversationId);
    } catch {
      /* localStorage unavailable */
    }
  }, [user, conversationId]);

  // Switch to a past session — used by the history sidebar. Always fetches
  // fresh rather than trusting any cached list-view preview text.
  const loadConversation = useCallback(async (id: string) => {
    if (!user) return;
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) return;
      const res = await fetch(
        `${API}/api/chat/history?conversation_id=${encodeURIComponent(id)}`,
        { headers: { Authorization: `Bearer ${session.access_token}` } },
      );
      if (!res.ok) return;
      const data = await res.json();
      const rows: HistoryRow[] = data.messages || [];
      setMessages(rowsToMessages(rows));
      setConversationId(id);
      setHistoryOpen(false);
      try {
        window.localStorage.setItem(activeConversationKey(user.id), id);
      } catch {
        /* localStorage unavailable */
      }
    } catch {
      /* best-effort — leave the current thread showing on failure */
    }
  }, [user]);

  const value: ChatContextValue = {
    messages,
    setMessages,
    conversationId,
    setConversationId,
    hydrated,
    newChat,
    loadConversation,
    historyOpen,
    toggleHistory,
  };

  return (
    <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
  );
}
