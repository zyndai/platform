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

interface ChatContextValue {
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  conversationId: string | null;
  setConversationId: React.Dispatch<React.SetStateAction<string | null>>;
  /** True until the initial /api/chat/history fetch completes (or fails). */
  hydrated: boolean;
}

const ChatContext = createContext<ChatContextValue>({
  messages: [],
  setMessages: () => {},
  conversationId: null,
  setConversationId: () => {},
  hydrated: false,
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
        const res = await fetch(`${API}/api/chat/history`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!res.ok) {
          if (!cancelled) setHydrated(true);
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        if (data.conversation_id) setConversationId(data.conversation_id);
        type Row = {
          role: "user" | "assistant";
          content: string;
          actions?: ChatMessage["actions"];
        };
        const rows: Row[] = data.messages || [];
        if (rows.length > 0) {
          setMessages(
            rows.map((r) => ({
              role: r.role,
              content: r.content,
              actions: r.actions || undefined,
            })),
          );
        }
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

  const value: ChatContextValue = {
    messages,
    setMessages,
    conversationId,
    setConversationId,
    hydrated,
  };

  return (
    <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
  );
}
