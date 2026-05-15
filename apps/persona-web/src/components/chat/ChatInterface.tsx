"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
  ChatMessage,
  PersonaHit,
  ThreadHandoff,
} from "./types";
import {
  extractHandoffs,
  extractPersonaHits,
} from "./helpers";
import ChatInput from "./ChatInput";
import MatchCard from "./MatchCard";
import IntroPreviewModal from "./IntroPreviewModal";
import ApprovalCard, { type PendingApproval } from "./ApprovalCard";
import IncomingRequestCard from "./IncomingRequestCard";

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

function MessageRow({
  message,
  busyId,
  onSayHi,
  onActOnHandoff,
  userId,
  userName,
  userAvatarUrl,
  onIncomingReplied,
}: {
  message: ChatMessage;
  busyId: string | null;
  onSayHi: (h: PersonaHit) => void;
  onActOnHandoff: (h: ThreadHandoff) => void;
  userId: string;
  userName: string;
  userAvatarUrl: string | null;
  onIncomingReplied: () => void;
}) {
  if (message.incoming) {
    return (
      <IncomingRequestCard
        request={message.incoming}
        userId={userId}
        onReplied={onIncomingReplied}
      />
    );
  }

  const isAria = message.role === "assistant";
  const personaHits = isAria ? extractPersonaHits(message.actions) : [];
  const handoffs = isAria ? extractHandoffs(message.actions) : [];
  const showTyping = isAria && !!message.streaming && !message.content;

  return (
    <>
      <div className={`msg ${isAria ? "aria" : "user"}`}>
        {isAria && <Monogram size="sm" />}
        <div className="bubble">
          {showTyping && <TypingIndicator />}
          {message.content && (
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
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
    </>
  );
}

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
  } = useChat();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

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
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMessages]);

  const updateStreaming = useCallback(
    (patch: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const out = prev.slice();
        const lastIdx = out.length - 1;
        if (out[lastIdx].role !== "assistant") return prev;
        out[lastIdx] = patch(out[lastIdx]);
        return out;
      });
    },
    [],
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
          }));
          break;
        case "done":
          if (typeof event.conversation_id === "string") {
            setConversationId(event.conversation_id);
          }
          updateStreaming((m) => ({
            ...m,
            content: (event.reply as string) || m.content,
            actions: event.actions_taken as ChatMessage["actions"],
            streaming: false,
          }));
          break;
      }
    },
    [updateStreaming],
  );

  const sendMessage = async (text: string) => {
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const placeholder: ChatMessage = {
      role: "assistant",
      content: "",
      thinking: "",
      toolCalls: [],
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, placeholder]);
    setInput("");
    setLoading(true);

    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      const res = await fetch(`${API}/api/chat/stream`, {
        method: "POST",
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
      updateStreaming((m) => ({
        ...m,
        error: err instanceof Error ? err.message : String(err),
        streaming: false,
      }));
    } finally {
      setLoading(false);
    }
  };

  // S9 → S10: clicking "Say hi" on a match card opens the intro preview
  // modal. The actual send happens through `sendIntro` below; this just
  // stages the target.
  const openIntroForPersona = (hit: PersonaHit) => {
    setIntroTarget(hit);
  };

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
  const actOnHandoff = async (h: ThreadHandoff) => {
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
  };

  const isEmpty = messages.length === 0;

  return (
    <>
      <div className="chat-area">
        {isEmpty ? (
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
          <div className="chat-thread">
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
                busyId={busyId}
                onSayHi={openIntroForPersona}
                onActOnHandoff={actOnHandoff}
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
                onIncomingReplied={() => {
                  setMessages((prev) =>
                    prev.map((msg, idx) =>
                      idx === i && msg.incoming
                        ? { ...msg, incoming: { ...msg.incoming, replied: true } }
                        : msg,
                    ),
                  );
                }}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={sendMessage}
          disabled={loading}
        />
      </div>

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
