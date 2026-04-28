"use client";

import { useEffect, useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSupabase } from "@/lib/supabase";

interface Thread {
  id: string;
  initiator_id: string;
  receiver_id: string;
  initiator_name: string;
  receiver_name: string;
  status: "pending" | "accepted" | "blocked";
  // Agent-conversation phase, separate from the connection-request `status`
  // above. Backed by dm_threads.lifecycle. May be missing on older rows
  // — treat undefined as "pending".
  lifecycle?: "pending" | "active" | "needs_human" | "human_handling";
  // Per-side modes — each participant owns their own half independently.
  // The legacy single `mode` field may still come back from older rows;
  // we read it as a fallback but the two new fields are authoritative.
  initiator_mode?: "human" | "agent";
  receiver_mode?: "human" | "agent";
  mode?: "human" | "agent";
  created_at: string;
}

// Friendly per-state copy + tag color for the lifecycle pill at the top
// of an open thread.
const LIFECYCLE_LABEL: Record<NonNullable<Thread["lifecycle"]>, { text: string; tag: string }> = {
  pending:         { text: "Waiting for them",     tag: "tag-amber" },
  active:          { text: "Agents talking",       tag: "tag-teal"  },
  needs_human:     { text: "Needs you",            tag: "tag-amber" },
  human_handling:  { text: "You're handling this", tag: "tag-teal"  },
};

interface ConnectionPermissions {
  can_request_meetings: boolean;
  can_query_availability: boolean;
  can_view_full_profile: boolean;
  can_post_on_my_behalf: boolean;
}

type MeetingStatus = "proposed" | "countered" | "accepted" | "scheduled" | "declined" | "cancelled" | "book_failed";

interface MeetingTask {
  id: string;
  thread_id: string;
  type: "meeting";
  status: MeetingStatus;
  initiator_user_id: string;
  recipient_user_id: string;
  initiator_agent_id: string;
  recipient_agent_id: string;
  payload: {
    title?: string;
    start_time?: string;
    end_time?: string;
    location?: string;
    description?: string;
  };
  history: { at: string; actor_user_id: string; action: string; payload?: any }[];
  created_at: string;
  updated_at: string;
}

// Format an ISO datetime for display: "Tue, Apr 14 · 3:00 PM – 3:30 PM"
function formatMeetingTime(start?: string, end?: string): string {
  if (!start || !end) return "Time TBD";
  try {
    const s = new Date(start);
    const e = new Date(end);
    const dateStr = s.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    const startStr = s.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const endStr = e.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return `${dateStr} · ${startStr} – ${endStr}`;
  } catch {
    return `${start} → ${end}`;
  }
}

const PERMISSION_LABELS: { key: keyof ConnectionPermissions; label: string; help: string }[] = [
  {
    key: "can_request_meetings",
    label: "Request meetings",
    help: "Allow this connection's agent to send you meeting proposals.",
  },
  {
    key: "can_query_availability",
    label: "Query my availability",
    help: "Allow this connection's agent to ask your agent when you're free (reads your calendar's busy/free blocks, not the event details).",
  },
  {
    key: "can_view_full_profile",
    label: "View my full profile",
    help: "Show this connection profile fields beyond name and description (location, organization, interests, links).",
  },
  {
    key: "can_post_on_my_behalf",
    label: "Post on my behalf",
    help: "Allow this connection's agent to ask your agent to publish anything on your connected accounts (tweets, etc.). Off by default.",
  },
];

interface Message {
  id: string;
  thread_id: string;
  sender_id: string;
  sender_type: "human" | "agent" | "system";
  channel: "human" | "agent";
  content: string;
  created_at: string;
}

type ChatChannel = "human" | "agent";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function MessagesPanel({ initialThreadId }: { initialThreadId?: string | null }) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThread, setActiveThread] = useState<Thread | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [activeChannel, setActiveChannel] = useState<ChatChannel>("human");
  const [draft, setDraft] = useState("");
  const [sessionUser, setSessionUser] = useState<any>(null);
  const [sessionAgentId, setSessionAgentId] = useState<string | null>(null);
  const [sessionName, setSessionName] = useState<string>("Zynd Agent");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getSupabase()
      .auth.getSession()
      .then(({ data }) => setSessionUser(data.session?.user));
  }, []);

  useEffect(() => {
    if (!sessionUser) return;

    let isMounted = true;

    const initializeNetwork = async () => {
      let activeAgentId = sessionAgentId;
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/persona/${sessionUser.id}/status`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.deployed && data.agent_id) {
            activeAgentId = data.agent_id;
            if (isMounted) {
              setSessionAgentId(data.agent_id);
              if (data.name) setSessionName(data.name);
            }
          }
        }
      } catch (e) {
        console.error("Failed agent_id sync:", e);
      }

      const sb = getSupabase();
      let queryStr = `initiator_id.eq.${sessionUser.id},receiver_id.eq.${sessionUser.id}`;
      if (activeAgentId) {
        queryStr = `${queryStr},initiator_id.eq.${activeAgentId},receiver_id.eq.${activeAgentId}`;
      }

      const { data } = await sb
        .from("dm_threads")
        .select("*")
        .or(queryStr)
        .order("updated_at", { ascending: false });

      if (data && isMounted) {
        setThreads(data);

        // Keep the currently-open thread fresh — if it's in the list,
        // patch in the latest row so columns updated by the backend
        // (lifecycle, status, mode flips) propagate to the header pill
        // and message styling without needing a full page reload.
        setActiveThread((current) => {
          if (current) {
            const fresh = data.find((t: Thread) => t.id === current.id);
            if (fresh) return fresh;
            return current;
          }
          // First-load: if the page was opened with ?thread=<id>, auto-
          // select that thread once it's in the list.
          if (initialThreadId) {
            const target = data.find((t: Thread) => t.id === initialThreadId);
            return target ?? null;
          }
          return current;
        });
      }
    };

    initializeNetwork();

    const channel = getSupabase()
      .channel("system_pings")
      .on("broadcast", { event: "new_thread" }, (payload) => {
        if (
          payload.payload?.receiver_id === sessionUser.id ||
          payload.payload?.receiver_id === sessionAgentId ||
          payload.payload?.initiator_id === sessionUser.id
        ) {
          initializeNetwork();
        }
      })
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "dm_threads" },
        () => {
          initializeNetwork();
        }
      )
      .subscribe();

    const pollId = setInterval(() => {
      if (isMounted) initializeNetwork();
    }, 10000);

    return () => {
      isMounted = false;
      clearInterval(pollId);
      getSupabase().removeChannel(channel);
    };
  }, [sessionUser]);

  // Depend on the thread *id*, not the thread object reference. Mode flips
  // and other state changes that build a new object via {...prev, mode: x}
  // would otherwise re-run this effect (and reset activeChannel) even
  // though the actual thread didn't change.
  const activeThreadId = activeThread?.id ?? null;
  useEffect(() => {
    if (!activeThreadId) return;
    // Each thread switch lands on the Conversation tab by default; users
    // explicitly switch to Agent Activity if they want to inspect.
    setActiveChannel("human");
    const sb = getSupabase();

    sb.from("dm_messages")
      .select("*")
      .eq("thread_id", activeThreadId)
      .order("created_at", { ascending: true })
      .then(({ data }) => {
        if (data) setMessages(data);
        setTimeout(
          () => scrollRef.current?.scrollIntoView({ behavior: "smooth" }),
          100
        );
      });

    const channel = sb
      .channel(`thread-${activeThreadId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "dm_messages",
          filter: `thread_id=eq.${activeThreadId}`,
        },
        (payload) => {
          setMessages((prev) => [...prev, payload.new as Message]);
          setTimeout(
            () => scrollRef.current?.scrollIntoView({ behavior: "smooth" }),
            100
          );
        }
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
    };
  }, [activeThreadId]);

  const handleSend = async () => {
    if (!draft.trim() || !activeThread || !sessionUser) return;
    const content = draft;
    setDraft("");

    await getSupabase().from("dm_messages").insert({
      thread_id: activeThread.id,
      sender_id: sessionAgentId || sessionUser.id,
      content: content,
      channel: "human", // explicit so this can never accidentally land in the agent log
    });
  };

  const updateThreadStatus = async (status: string) => {
    if (!activeThread) return;
    await getSupabase()
      .from("dm_threads")
      .update({ status })
      .eq("id", activeThread.id);

    setActiveThread((prev) =>
      prev ? { ...prev, status: status as any } : null
    );
  };

  // Which side of a thread belongs to me. Returns 'initiator', 'receiver', or null.
  const mySide = (thread: Thread | null): "initiator" | "receiver" | null => {
    if (!thread || !sessionAgentId) return null;
    if (thread.initiator_id === sessionAgentId) return "initiator";
    if (thread.receiver_id === sessionAgentId) return "receiver";
    return null;
  };

  // My current mode for a thread. Falls back to legacy `mode` field if the
  // per-side columns aren't present yet, then to 'agent'.
  const myModeFor = (thread: Thread | null): "human" | "agent" => {
    if (!thread) return "agent";
    const side = mySide(thread);
    if (side === "initiator") return thread.initiator_mode ?? thread.mode ?? "agent";
    if (side === "receiver")  return thread.receiver_mode  ?? thread.mode ?? "agent";
    return "agent";
  };

  // Derived mode for the currently-open thread. Used everywhere the header,
  // banners, input bar, and take-over buttons need to decide what to show.
  const myMode: "human" | "agent" = myModeFor(activeThread);

  // Flip MY side of the conversation between AI handling and manual.
  // Does NOT affect the other side — their own mode is independent.
  const toggleThreadMode = async () => {
    if (!activeThread || !sessionUser) return;
    const side = mySide(activeThread);
    if (!side) return;
    const next = myMode === "agent" ? "human" : "agent";
    const column = side === "initiator" ? "initiator_mode" : "receiver_mode";
    try {
      const res = await fetch(`${API}/api/persona/threads/${activeThread.id}/mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: next, user_id: sessionUser.id }),
      });
      if (!res.ok) throw new Error(await res.text());
      // Update MY column locally; leave the other side's column untouched.
      setActiveThread((prev) => (prev ? { ...prev, [column]: next } : null));
      setThreads((prev) =>
        prev.map((t) => (t.id === activeThread.id ? { ...t, [column]: next } : t))
      );
    } catch (e) {
      console.error("Failed to toggle thread mode:", e);
    }
  };

  const getPartnerId = (thread: Thread) =>
    thread.initiator_id === sessionUser.id ||
    thread.initiator_id === sessionAgentId
      ? thread.receiver_id
      : thread.initiator_id;
  const getPartnerName = (thread: Thread) =>
    thread.initiator_id === sessionUser.id ||
    thread.initiator_id === sessionAgentId
      ? thread.receiver_name
      : thread.initiator_name;

  const requests = threads.filter(
    (t) =>
      t.status === "pending" &&
      (t.receiver_id === sessionUser.id || t.receiver_id === sessionAgentId)
  );
  const primary = threads.filter(
    (t) =>
      t.status === "accepted" ||
      (t.status === "pending" &&
        (t.initiator_id === sessionUser.id ||
          t.initiator_id === sessionAgentId))
  );

  const [agentDraft, setAgentDraft] = useState("");
  const [agentSending, setAgentSending] = useState(false);

  // Send a human-typed message on the agent channel (when user has taken over)
  const handleAgentSend = async () => {
    if (!agentDraft.trim() || !activeThread || !sessionUser || agentSending) return;
    const content = agentDraft;
    setAgentDraft("");
    setAgentSending(true);
    try {
      await fetch(`${API}/api/persona/${sessionUser.id}/agent-send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: activeThread.id,
          content,
        }),
      });
    } catch (e) {
      console.error("Failed to send agent-channel message:", e);
    } finally {
      setAgentSending(false);
    }
  };

  const [newChatQuery, setNewChatQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // ── Meeting tickets for the active thread ──────────────────────────
  const [meetings, setMeetings] = useState<MeetingTask[]>([]);
  const [counterEditing, setCounterEditing] = useState<string | null>(null);
  const [counterStart, setCounterStart] = useState("");
  const [counterEnd, setCounterEnd] = useState("");
  const [meetingBusy, setMeetingBusy] = useState<string | null>(null);
  const [historyModal, setHistoryModal] = useState<MeetingTask | null>(null);

  useEffect(() => {
    if (!activeThreadId) {
      setMeetings([]);
      return;
    }
    let cancelled = false;

    // Initial fetch via REST so we pick up the row even if realtime is behind.
    fetch(`${API}/api/meetings/thread/${activeThreadId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setMeetings(data.tasks || []);
      })
      .catch((e) => console.error("Failed to load meetings:", e));

    // Realtime: listen to all agent_tasks changes for this thread.
    const sb = getSupabase();
    const channel = sb
      .channel(`meetings-${activeThreadId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "agent_tasks",
          filter: `thread_id=eq.${activeThreadId}`,
        },
        (payload) => {
          setMeetings((prev) => {
            if (payload.eventType === "INSERT") {
              return [payload.new as MeetingTask, ...prev];
            }
            if (payload.eventType === "UPDATE") {
              return prev.map((m) => (m.id === (payload.new as MeetingTask).id ? (payload.new as MeetingTask) : m));
            }
            if (payload.eventType === "DELETE") {
              return prev.filter((m) => m.id !== (payload.old as MeetingTask).id);
            }
            return prev;
          });
        }
      )
      .subscribe();

    return () => {
      cancelled = true;
      sb.removeChannel(channel);
    };
  }, [activeThreadId]);

  // Who is "me" for the purposes of whose-turn-is-it logic.
  // In the tickets table, the user id IS the Supabase UUID (not the agent_id).
  const myUserId = sessionUser?.id as string | undefined;

  const respondToMeeting = async (
    taskId: string,
    action: "accept" | "counter" | "decline" | "cancel",
    edits?: { start_time?: string; end_time?: string }
  ) => {
    if (!myUserId) return;
    setMeetingBusy(taskId);
    try {
      const res = await fetch(`${API}/api/meetings/${taskId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actor_user_id: myUserId,
          action,
          edits: edits || null,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      // Optimistically update — the realtime subscription will reconcile shortly.
      const data = await res.json();
      setMeetings((prev) => prev.map((m) => (m.id === taskId ? data.task : m)));
      setCounterEditing(null);
      setCounterStart("");
      setCounterEnd("");
    } catch (e) {
      console.error("Failed to respond to meeting:", e);
      alert(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMeetingBusy(null);
    }
  };

  // ── Permissions drawer state ──────────────────────────────────────
  const [permissionsOpen, setPermissionsOpen] = useState(false);
  const [permissions, setPermissions] = useState<ConnectionPermissions | null>(null);
  const [permissionsSaving, setPermissionsSaving] = useState<keyof ConnectionPermissions | null>(null);

  // Load permissions whenever the drawer opens for a thread.
  // Depend on the id (not the object reference) so re-renders that
  // create new thread objects don't kick this off again.
  useEffect(() => {
    if (!permissionsOpen || !activeThreadId) return;
    let cancelled = false;
    setPermissions(null);
    fetch(`${API}/api/persona/threads/${activeThreadId}/permissions`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setPermissions(data.permissions);
      })
      .catch((e) => console.error("Failed to load permissions:", e));
    return () => {
      cancelled = true;
    };
  }, [permissionsOpen, activeThreadId]);

  // Optimistic toggle: flip locally immediately, PATCH the backend, roll back on failure.
  const toggleConnectionPermission = async (key: keyof ConnectionPermissions) => {
    if (!activeThread || !permissions) return;
    const previous = permissions[key];
    const next = !previous;
    setPermissions({ ...permissions, [key]: next });
    setPermissionsSaving(key);
    try {
      const res = await fetch(
        `${API}/api/persona/threads/${activeThread.id}/permissions`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [key]: next }),
        }
      );
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      // Trust the server's merged result so we always reflect ground truth
      setPermissions(data.permissions);
    } catch (e) {
      console.error("Failed to update permission:", e);
      setPermissions((prev) => (prev ? { ...prev, [key]: previous } : prev));
    } finally {
      setPermissionsSaving(null);
    }
  };

  useEffect(() => {
    if (newChatQuery.length < 2) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        // Use new v2 search endpoint on dns01.zynd.ai
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/persona/search?query=${encodeURIComponent(newChatQuery)}&limit=10`
        );

        // Fallback: direct registry search if backend proxy not available
        let personas: any[] = [];
        if (res.ok) {
          const json = await res.json();
          personas = json.results || [];
        } else {
          // Direct registry fallback
          const registryRes = await fetch(
            `https://dns01.zynd.ai/v1/search`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                query: newChatQuery,
                tags: ["persona"],
                limit: 10,
              }),
            }
          );
          if (registryRes.ok) {
            const registryJson = await registryRes.json();
            personas = (registryJson.results || []).filter((a: any) => {
              const tags = a.tags || [];
              const caps = a.capabilities || {};
              let parsed = caps;
              if (typeof caps === "string")
                try { parsed = JSON.parse(caps); } catch {}
              return (
                tags.includes("persona") ||
                (typeof parsed === "object" &&
                  Array.isArray(parsed?.services) &&
                  parsed.services.includes("persona"))
              );
            });
          }
        }
        setSearchResults(personas);
      } catch (e) {
        console.error(e);
      }
      setIsSearching(false);
    }, 400);
    return () => clearTimeout(timer);
  }, [newChatQuery]);

  const startNewChat = async (targetAgent: any) => {
    if (!targetAgent || !targetAgent.agent_id || !sessionUser) return;
    const targetAgentId = targetAgent.agent_id;

    const existing = threads.find(
      (t) =>
        ((t.initiator_id === sessionUser.id ||
          t.initiator_id === sessionAgentId) &&
          t.receiver_id === targetAgentId.trim()) ||
        ((t.receiver_id === sessionUser.id ||
          t.receiver_id === sessionAgentId) &&
          t.initiator_id === targetAgentId.trim())
    );
    if (existing) {
      setActiveThread(existing);
      setNewChatQuery("");
      setSearchResults([]);
      return;
    }

    const { data } = await getSupabase()
      .from("dm_threads")
      .insert({
        initiator_id: sessionAgentId || sessionUser.id,
        receiver_id: targetAgentId.trim(),
        initiator_name: sessionName,
        receiver_name: targetAgent.name || "Network Agent",
        status: "pending",
      })
      .select()
      .single();

    if (data) {
      setActiveThread(data);
      setNewChatQuery("");
      setSearchResults([]);

      getSupabase().channel("system_pings").send({
        type: "broadcast",
        event: "new_thread",
        payload: {
          receiver_id: targetAgentId.trim(),
          initiator_id: sessionAgentId || sessionUser.id,
        },
      });
    }
  };

  if (!sessionUser)
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          background: "var(--bg-base)",
        }}
      >
        <div className="status-pill">
          <span className="status-dot" />
          Authenticating...
        </div>
      </div>
    );

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        width: "100%",
        overflow: "hidden",
        background: "var(--bg-base)",
      }}
    >
      {/* -- Left: Thread Inbox -- */}
      <div
        style={{
          width: "300px",
          borderRight: "1px solid var(--border-subtle)",
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-base)",
          flexShrink: 0,
        }}
      >
        {/* Header & Search */}
        <div
          style={{
            padding: "20px 16px",
            borderBottom: "1px solid var(--border-subtle)",
            position: "relative",
          }}
        >
          <h2
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "15px",
              fontWeight: 700,
              marginBottom: "4px",
            }}
          >
            Network DMs
          </h2>
          <p className="section-label" style={{ marginBottom: "14px" }}>
            CROSS-AGENT MESSAGING
          </p>
          <input
            type="text"
            placeholder="Search Zynd Network..."
            value={newChatQuery}
            onChange={(e) => setNewChatQuery(e.target.value)}
            className="input"
            style={{ fontSize: "12px", padding: "8px 12px" }}
          />

          {/* Live Search Dropdown */}
          {(searchResults.length > 0 || isSearching) && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: "16px",
                right: "16px",
                background: "var(--bg-overlay)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--r-md)",
                zIndex: 100,
                maxHeight: "280px",
                overflowY: "auto",
                boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
                marginTop: "4px",
              }}
            >
              {isSearching ? (
                <div
                  style={{
                    padding: "14px",
                    fontSize: "11px",
                    color: "var(--text-muted)",
                    fontFamily: "IBM Plex Mono, monospace",
                  }}
                >
                  Searching network...
                </div>
              ) : (
                searchResults.map((p) => (
                  <div
                    key={p.agent_id}
                    onClick={() => startNewChat(p)}
                    style={{
                      padding: "12px 14px",
                      borderBottom: "1px solid var(--border-subtle)",
                      cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background = "var(--bg-raised)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "transparent")
                    }
                  >
                    <div
                      style={{
                        fontFamily: "DM Sans, sans-serif",
                        fontSize: "13px",
                        fontWeight: 500,
                        color: "var(--text-primary)",
                      }}
                    >
                      {p.name}
                    </div>
                    <div
                      style={{
                        fontFamily: "IBM Plex Mono, monospace",
                        fontSize: "10px",
                        color: "var(--text-muted)",
                        marginTop: "2px",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {p.description || "Zynd Agent"}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Thread list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {/* Requests */}
          {requests.length > 0 && (
            <div style={{ padding: "12px 16px" }}>
              <p
                className="section-label"
                style={{ color: "var(--accent-coral)", marginBottom: "8px" }}
              >
                REQUESTS ({requests.length})
              </p>
              {requests.map((t) => (
                <div
                  key={t.id}
                  onClick={() => setActiveThread(t)}
                  className="card"
                  style={{
                    padding: "12px",
                    marginBottom: "6px",
                    background:
                      activeThread?.id === t.id
                        ? "var(--bg-raised)"
                        : "var(--bg-surface)",
                    borderColor:
                      activeThread?.id === t.id
                        ? "var(--border-strong)"
                        : "var(--border-default)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "DM Sans, sans-serif",
                      fontSize: "13px",
                      fontWeight: 500,
                      color: "var(--text-primary)",
                    }}
                  >
                    New Request
                  </div>
                  <div
                    style={{
                      fontFamily: "IBM Plex Mono, monospace",
                      fontSize: "10px",
                      color: "var(--text-muted)",
                      marginTop: "3px",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {getPartnerName(t)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Primary inbox */}
          <div style={{ padding: "12px 16px" }}>
            <p className="section-label" style={{ marginBottom: "8px" }}>
              PRIMARY INBOX
            </p>
            {primary.map((t) => {
              const partnerName = getPartnerName(t);
              return (
                <div
                  key={t.id}
                  onClick={() => setActiveThread(t)}
                  className="card"
                  style={{
                    padding: "12px",
                    marginBottom: "6px",
                    background:
                      activeThread?.id === t.id
                        ? "var(--bg-raised)"
                        : "var(--bg-surface)",
                    borderColor:
                      activeThread?.id === t.id
                        ? "var(--border-strong)"
                        : "var(--border-default)",
                  }}
                >
                  <div
                    style={{
                      fontFamily: "DM Sans, sans-serif",
                      fontSize: "13px",
                      fontWeight: 500,
                      color: "var(--text-primary)",
                    }}
                  >
                    {partnerName}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      marginTop: "4px",
                    }}
                  >
                    {t.status === "pending" ? (
                      <span className="tag tag-amber" style={{ fontSize: "9px" }}>
                        PENDING
                      </span>
                    ) : (
                      <span className="tag tag-teal" style={{ fontSize: "9px" }}>
                        ACTIVE
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
            {primary.length === 0 && (
              <p
                style={{
                  fontSize: "12px",
                  color: "var(--text-muted)",
                  marginTop: "16px",
                  fontFamily: "DM Sans, sans-serif",
                }}
              >
                No active chats yet.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* -- Main Chat Area -- */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-base)",
          position: "relative", // anchor for the connection-settings drawer overlay
        }}
      >
        {activeThread ? (
          <>
            {/* Chat header */}
            <div
              className="topbar"
              style={{
                gap: "14px",
                borderBottom: "1px solid var(--border-subtle)",
                flexWrap: "wrap",
                rowGap: "10px",
              }}
            >
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "var(--r-sm)",
                  background:
                    "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "Syne, sans-serif",
                  fontWeight: 800,
                  fontSize: "14px",
                  color: "#fff",
                  flexShrink: 0,
                }}
              >
                {getPartnerName(activeThread)?.charAt(0) || "Z"}
              </div>
              <div>
                <h3
                  style={{
                    fontFamily: "Syne, sans-serif",
                    fontSize: "14px",
                    fontWeight: 600,
                    color: "var(--text-primary)",
                  }}
                >
                  {getPartnerName(activeThread)}
                </h3>
                <p
                  style={{
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: "9.5px",
                    color: "var(--text-muted)",
                    maxWidth: "280px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {getPartnerId(activeThread)}
                </p>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "8px" }}>
                {(() => {
                  // Connection request was rejected — show that loud, ignore lifecycle.
                  if (activeThread.status === "blocked") {
                    return <span className="tag tag-coral" style={{ fontSize: "9px" }}>BLOCKED</span>;
                  }
                  // Otherwise surface the friendly conversation phase
                  // (pending → active → needs_human → human_handling).
                  const phase = activeThread.lifecycle || "pending";
                  const label = LIFECYCLE_LABEL[phase] || LIFECYCLE_LABEL.pending;
                  return (
                    <span className={`tag ${label.tag}`} style={{ fontSize: "9px" }}>
                      {label.text}
                    </span>
                  );
                })()}

                {/* ── Connection settings (permissions drawer) ── */}
                <button
                  onClick={() => setPermissionsOpen(true)}
                  title="Connection settings"
                  style={{
                    width: "28px",
                    height: "28px",
                    borderRadius: "999px",
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border-default)",
                    color: "var(--text-secondary)",
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "13px",
                  }}
                >
                  ⚙
                </button>

                {/* ── Mode toggle: YOUR side only. The other side is independent. ── */}
                <button
                  onClick={toggleThreadMode}
                  title={
                    myMode === "agent"
                      ? "Your AI is auto-replying on this thread. Click to take over."
                      : "You are handling this thread. Click to delegate to your AI."
                  }
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "5px 10px",
                    borderRadius: "999px",
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: "10px",
                    letterSpacing: "0.5px",
                    cursor: "pointer",
                    background:
                      myMode === "agent"
                        ? "rgba(0, 212, 180, 0.10)"
                        : "var(--bg-surface)",
                    border:
                      myMode === "agent"
                        ? "1px solid rgba(0, 212, 180, 0.30)"
                        : "1px solid var(--border-default)",
                    color:
                      myMode === "agent"
                        ? "var(--accent-teal)"
                        : "var(--text-secondary)",
                  }}
                >
                  {myMode === "agent" ? "🤖 AI HANDLING" : "👤 TAKEN OVER"}
                </button>
              </div>
            </div>

            {/* ── Channel tabs: Conversation vs Agent Activity ── */}
            <div
              style={{
                display: "flex",
                gap: "4px",
                padding: "10px 24px 0",
                borderBottom: "1px solid var(--border-subtle)",
                background: "var(--bg-base)",
              }}
            >
              {([
                { key: "human", label: "💬 Conversation", help: "Direct human-to-human messages." },
                { key: "agent", label: "🤖 Agent Activity", help: "Read-only log of what your agent and theirs have been saying to each other." },
              ] as { key: ChatChannel; label: string; help: string }[]).map((tab) => {
                const isActive = activeChannel === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setActiveChannel(tab.key)}
                    title={tab.help}
                    style={{
                      padding: "8px 14px",
                      fontFamily: "DM Sans, sans-serif",
                      fontSize: "12px",
                      fontWeight: 500,
                      cursor: "pointer",
                      background: "transparent",
                      border: "none",
                      borderBottom: `2px solid ${isActive ? "var(--accent-teal)" : "transparent"}`,
                      color: isActive ? "var(--text-primary)" : "var(--text-muted)",
                      marginBottom: "-1px",
                    }}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {/* Messages area */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "24px",
                display: "flex",
                flexDirection: "column",
                gap: "12px",
              }}
            >
              {/* ── Meeting ticket cards ── */}
              {meetings
                .filter((m) =>
                  ["proposed", "countered", "accepted", "scheduled", "book_failed"].includes(m.status)
                )
                .map((m) => {
                const lastActor = m.history[m.history.length - 1]?.actor_user_id;
                const awaitingMe =
                  !!myUserId &&
                  (m.status === "proposed" || m.status === "countered") &&
                  lastActor !== myUserId;
                const iProposed = m.initiator_user_id === myUserId;
                return (
                  <div
                    key={m.id}
                    style={{
                      alignSelf: "stretch",
                      background: "var(--bg-surface)",
                      border: `1px solid ${awaitingMe ? "rgba(245, 158, 11, 0.35)" : "var(--border-default)"}`,
                      borderRadius: "var(--r-md)",
                      padding: "16px 18px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "flex-start", gap: "12px", marginBottom: "10px" }}>
                      <div style={{ fontSize: "18px", lineHeight: 1, marginTop: "1px" }}>📅</div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p
                          style={{
                            fontFamily: "Syne, sans-serif",
                            fontSize: "14px",
                            fontWeight: 700,
                            color: "var(--text-primary)",
                            marginBottom: "2px",
                          }}
                        >
                          {m.payload?.title || "Untitled meeting"}
                        </p>
                        <p
                          style={{
                            fontFamily: "DM Sans, sans-serif",
                            fontSize: "12px",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {formatMeetingTime(m.payload?.start_time, m.payload?.end_time)}
                        </p>
                        {m.payload?.location && (
                          <p style={{ fontFamily: "DM Sans, sans-serif", fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                            📍 {m.payload.location}
                          </p>
                        )}
                        {m.payload?.description && (
                          <p style={{ fontFamily: "DM Sans, sans-serif", fontSize: "11px", color: "var(--text-muted)", marginTop: "4px", lineHeight: 1.5 }}>
                            {m.payload.description}
                          </p>
                        )}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
                        <span
                          className={
                            m.status === "proposed" || m.status === "countered"
                              ? "tag tag-amber"
                              : m.status === "scheduled"
                              ? "tag tag-teal"
                              : m.status === "accepted"
                              ? "tag tag-teal"
                              : m.status === "book_failed"
                              ? "tag tag-coral"
                              : "tag"
                          }
                          style={{ fontSize: "9px" }}
                        >
                          {m.status === "scheduled" ? "✓ ON CALENDAR" : m.status.toUpperCase()}
                        </span>
                        <button
                          onClick={() => setHistoryModal(m)}
                          title="View history"
                          style={{
                            background: "transparent",
                            border: "1px solid var(--border-default)",
                            borderRadius: "999px",
                            width: "20px",
                            height: "20px",
                            color: "var(--text-muted)",
                            cursor: "pointer",
                            fontSize: "10px",
                            display: "inline-flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          ⓘ
                        </button>
                      </div>
                    </div>

                    {/* Action row */}
                    {counterEditing === m.id ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px" }}>
                        <p className="section-label">COUNTER WITH A NEW TIME</p>
                        <div style={{ display: "flex", gap: "6px" }}>
                          <input
                            type="datetime-local"
                            className="input"
                            value={counterStart}
                            onChange={(e) => setCounterStart(e.target.value)}
                            style={{ fontSize: "12px", padding: "6px 10px" }}
                          />
                          <input
                            type="datetime-local"
                            className="input"
                            value={counterEnd}
                            onChange={(e) => setCounterEnd(e.target.value)}
                            style={{ fontSize: "12px", padding: "6px 10px" }}
                          />
                        </div>
                        <div style={{ display: "flex", gap: "6px", marginTop: "4px" }}>
                          <button
                            onClick={() => {
                              if (!counterStart || !counterEnd) return;
                              respondToMeeting(m.id, "counter", {
                                // datetime-local gives no TZ; append Z to treat as UTC
                                start_time: new Date(counterStart).toISOString(),
                                end_time: new Date(counterEnd).toISOString(),
                              });
                            }}
                            disabled={meetingBusy === m.id || !counterStart || !counterEnd}
                            className="btn-primary"
                            style={{ padding: "6px 14px", fontSize: "11px" }}
                          >
                            Send counter
                          </button>
                          <button
                            onClick={() => setCounterEditing(null)}
                            className="btn-secondary"
                            style={{ padding: "6px 14px", fontSize: "11px" }}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : awaitingMe ? (
                      <div style={{ display: "flex", gap: "6px", marginTop: "10px", flexWrap: "wrap" }}>
                        <button
                          onClick={() => respondToMeeting(m.id, "accept")}
                          disabled={meetingBusy === m.id}
                          className="btn-primary"
                          style={{ padding: "6px 14px", fontSize: "11px" }}
                        >
                          Accept
                        </button>
                        <button
                          onClick={() => {
                            setCounterEditing(m.id);
                            // Prefill with current payload
                            if (m.payload?.start_time) {
                              setCounterStart(new Date(m.payload.start_time).toISOString().slice(0, 16));
                            }
                            if (m.payload?.end_time) {
                              setCounterEnd(new Date(m.payload.end_time).toISOString().slice(0, 16));
                            }
                          }}
                          disabled={meetingBusy === m.id}
                          className="btn-secondary"
                          style={{ padding: "6px 14px", fontSize: "11px" }}
                        >
                          Counter
                        </button>
                        <button
                          onClick={() => respondToMeeting(m.id, "decline")}
                          disabled={meetingBusy === m.id}
                          className="btn-danger"
                          style={{ padding: "6px 14px", fontSize: "11px" }}
                        >
                          Decline
                        </button>
                      </div>
                    ) : m.status === "scheduled" ? (
                      // Booked on both calendars — show a confirmation line
                      // and a cancel button that removes both events.
                      <div
                        style={{
                          marginTop: "10px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "8px",
                        }}
                      >
                        <p
                          style={{
                            fontFamily: "IBM Plex Mono, monospace",
                            fontSize: "10px",
                            color: "var(--accent-teal)",
                          }}
                        >
                          ✓ Added to both calendars
                        </p>
                        <button
                          onClick={() => {
                            if (confirm("Cancel this meeting? It will be removed from both calendars.")) {
                              respondToMeeting(m.id, "cancel");
                            }
                          }}
                          disabled={meetingBusy === m.id}
                          style={{
                            padding: "4px 10px",
                            fontSize: "10px",
                            fontFamily: "IBM Plex Mono, monospace",
                            background: "transparent",
                            border: "1px solid rgba(255, 95, 109, 0.35)",
                            color: "var(--accent-coral)",
                            borderRadius: "var(--r-sm)",
                            cursor: "pointer",
                          }}
                        >
                          CANCEL MEETING
                        </button>
                      </div>
                    ) : m.status === "book_failed" ? (
                      // Booking failed — show the reason (pulled from the
                      // most recent book_failed history entry) and offer
                      // retry / abandon controls.
                      <div style={{ marginTop: "10px" }}>
                        {(() => {
                          const failure = [...m.history].reverse().find((h) => h.action === "book_failed");
                          const reason = (failure as any)?.reason || "Calendar booking failed.";
                          return (
                            <p
                              style={{
                                fontFamily: "DM Sans, sans-serif",
                                fontSize: "11px",
                                color: "var(--accent-coral)",
                                marginBottom: "8px",
                                lineHeight: 1.5,
                              }}
                            >
                              ⚠ {reason}
                            </p>
                          );
                        })()}
                        <div style={{ display: "flex", gap: "6px" }}>
                          <button
                            onClick={() => respondToMeeting(m.id, "accept")}
                            disabled={meetingBusy === m.id}
                            className="btn-primary"
                            style={{ padding: "6px 14px", fontSize: "11px" }}
                          >
                            Retry booking
                          </button>
                          <button
                            onClick={() => respondToMeeting(m.id, "cancel")}
                            disabled={meetingBusy === m.id}
                            className="btn-secondary"
                            style={{ padding: "6px 14px", fontSize: "11px" }}
                          >
                            Abandon
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        style={{
                          marginTop: "10px",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: "8px",
                        }}
                      >
                        <p
                          style={{
                            fontFamily: "IBM Plex Mono, monospace",
                            fontSize: "10px",
                            color: "var(--text-muted)",
                          }}
                        >
                          {m.status === "accepted"
                            ? "Booking in progress…"
                            : `Waiting for ${awaitingMe ? "you" : "the other side"}…`}
                        </p>
                        {iProposed && (m.status === "proposed" || m.status === "countered") && (
                          <button
                            onClick={() => respondToMeeting(m.id, "cancel")}
                            disabled={meetingBusy === m.id}
                            style={{
                              padding: "4px 10px",
                              fontSize: "10px",
                              fontFamily: "IBM Plex Mono, monospace",
                              background: "transparent",
                              border: "1px solid var(--border-default)",
                              color: "var(--text-muted)",
                              borderRadius: "var(--r-sm)",
                              cursor: "pointer",
                            }}
                          >
                            WITHDRAW
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Agent-mode banner — shows when MY side has AI handling on */}
              {myMode === "agent" && activeThread.status !== "blocked" && (
                <div
                  style={{
                    background: "rgba(0, 212, 180, 0.06)",
                    border: "1px solid rgba(0, 212, 180, 0.20)",
                    padding: "10px 14px",
                    borderRadius: "var(--r-md)",
                    color: "var(--accent-teal)",
                    fontSize: "12px",
                    fontFamily: "DM Sans, sans-serif",
                    alignSelf: "stretch",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                  }}
                >
                  <span>🤖</span>
                  <span style={{ flex: 1, color: "var(--text-secondary)" }}>
                    Your AI agent is auto-replying on this thread.
                  </span>
                  <button
                    onClick={toggleThreadMode}
                    style={{
                      padding: "4px 10px",
                      fontSize: "10px",
                      fontFamily: "IBM Plex Mono, monospace",
                      background: "transparent",
                      border: "1px solid rgba(0, 212, 180, 0.40)",
                      color: "var(--accent-teal)",
                      borderRadius: "var(--r-sm)",
                      cursor: "pointer",
                    }}
                  >
                    TAKE OVER
                  </button>
                </div>
              )}

              {/* Pending request banner */}
              {activeThread.status === "pending" &&
                (activeThread.receiver_id === sessionUser.id ||
                  activeThread.receiver_id === sessionAgentId) && (
                  <div
                    style={{
                      background: "var(--bg-surface)",
                      border: "1px solid var(--border-default)",
                      padding: "20px",
                      borderRadius: "var(--r-md)",
                      textAlign: "center",
                      alignSelf: "center",
                      maxWidth: "400px",
                    }}
                  >
                    <p
                      style={{
                        marginBottom: "16px",
                        fontSize: "13px",
                        color: "var(--text-secondary)",
                        lineHeight: 1.6,
                      }}
                    >
                      This network agent is requesting to connect with you.
                      Accepting allows them to message and orchestrate tools on
                      your behalf.
                    </p>
                    <div
                      style={{
                        display: "flex",
                        gap: "10px",
                        justifyContent: "center",
                      }}
                    >
                      <button
                        onClick={() => updateThreadStatus("accepted")}
                        className="btn-primary"
                        style={{ padding: "8px 20px", fontSize: "12px" }}
                      >
                        Accept Request
                      </button>
                      <button
                        onClick={() => updateThreadStatus("blocked")}
                        className="btn-danger"
                        style={{ padding: "8px 20px", fontSize: "12px" }}
                      >
                        Block
                      </button>
                    </div>
                  </div>
                )}

              {messages
                .filter((m) => (m.channel || "human") === activeChannel)
                .map((m) => {
                // System notes (halt notes, agent escalation summaries)
                // render as a single centered, ink-muted line — no bubble,
                // no avatar. Per the brief's S8 system-note pattern.
                if (m.sender_type === "system") {
                  return (
                    <div
                      key={m.id}
                      style={{
                        alignSelf: "center",
                        maxWidth: "90%",
                        textAlign: "center",
                        padding: "8px 14px",
                        fontFamily: "DM Sans, sans-serif",
                        fontSize: "12.5px",
                        fontStyle: "italic",
                        color: "var(--text-muted)",
                        lineHeight: 1.5,
                        opacity: 0.85,
                      }}
                    >
                      {m.content}
                      <span
                        style={{
                          fontFamily: "IBM Plex Mono, monospace",
                          fontSize: "10px",
                          marginLeft: "8px",
                          opacity: 0.7,
                        }}
                      >
                        · {new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                  );
                }

                const isMe =
                  m.sender_id === sessionUser.id ||
                  m.sender_id === sessionAgentId;
                return (
                  <div
                    key={m.id}
                    style={{
                      alignSelf: isMe ? "flex-end" : "flex-start",
                      maxWidth: "75%",
                      display: "flex",
                      gap: "10px",
                      animation: "slideIn 0.2s ease",
                    }}
                  >
                    {/* Partner avatar */}
                    {!isMe && (
                      <div
                        style={{
                          width: "28px",
                          height: "28px",
                          borderRadius: "var(--r-sm)",
                          background:
                            "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontFamily: "Syne, sans-serif",
                          fontWeight: 800,
                          fontSize: "11px",
                          color: "#fff",
                          flexShrink: 0,
                          marginTop: "2px",
                        }}
                      >
                        {getPartnerName(activeThread)?.charAt(0) || "A"}
                      </div>
                    )}
                    <div
                      className={isMe ? "msg-bubble-user" : "msg-bubble-ai"}
                      style={{ maxWidth: "100%" }}
                    >
                      <div className="markdown-content">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {m.content}
                        </ReactMarkdown>
                      </div>
                      <p
                        className="msg-timestamp"
                        style={{
                          marginTop: "6px",
                          display: "flex",
                          alignItems: "center",
                          gap: "6px",
                          justifyContent: isMe ? "flex-end" : "flex-start",
                        }}
                      >
                        {m.sender_type === "agent" && (
                          <span
                            title="Sent by an AI agent"
                            style={{
                              fontFamily: "IBM Plex Mono, monospace",
                              fontSize: "9px",
                              padding: "1px 6px",
                              borderRadius: "999px",
                              background: "rgba(0, 212, 180, 0.10)",
                              border: "1px solid rgba(0, 212, 180, 0.25)",
                              color: "var(--accent-teal)",
                              letterSpacing: "0.4px",
                            }}
                          >
                            🤖 AGENT
                          </span>
                        )}
                        <span>
                          {new Date(m.created_at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </p>
                    </div>
                  </div>
                );
              })}
              <div ref={scrollRef} />
            </div>

            {/* ── Ticket history modal ── */}
            {historyModal && (
              <div
                onClick={() => setHistoryModal(null)}
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "rgba(0,0,0,0.55)",
                  zIndex: 250,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "24px",
                }}
              >
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    width: "440px",
                    maxWidth: "95vw",
                    maxHeight: "80vh",
                    background: "var(--bg-base)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "var(--r-md)",
                    boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
                    display: "flex",
                    flexDirection: "column",
                  }}
                >
                  <div
                    style={{
                      padding: "18px 20px",
                      borderBottom: "1px solid var(--border-subtle)",
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <p
                        style={{
                          fontFamily: "Syne, sans-serif",
                          fontSize: "14px",
                          fontWeight: 700,
                          color: "var(--text-primary)",
                        }}
                      >
                        Meeting history
                      </p>
                      <p
                        style={{
                          fontFamily: "IBM Plex Mono, monospace",
                          fontSize: "9px",
                          color: "var(--text-muted)",
                          letterSpacing: "0.5px",
                          textTransform: "uppercase",
                          marginTop: "2px",
                        }}
                      >
                        {historyModal.payload?.title || "Untitled meeting"}
                      </p>
                    </div>
                    <button
                      onClick={() => setHistoryModal(null)}
                      style={{
                        width: "26px",
                        height: "26px",
                        borderRadius: "999px",
                        background: "var(--bg-surface)",
                        border: "1px solid var(--border-default)",
                        color: "var(--text-secondary)",
                        cursor: "pointer",
                        fontSize: "12px",
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  <div style={{ padding: "16px 20px", overflowY: "auto" }}>
                    {historyModal.history.length === 0 ? (
                      <p style={{ fontSize: "12px", color: "var(--text-muted)" }}>No history yet.</p>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                        {historyModal.history.map((h: any, i: number) => {
                          const when = h.at ? new Date(h.at).toLocaleString() : "";
                          const isMe = h.actor_user_id === myUserId;
                          const action = String(h.action || "").toLowerCase();
                          const verb =
                            action === "proposed"
                              ? "proposed the meeting"
                              : action === "countered"
                              ? "countered with new times"
                              : action === "accepted"
                              ? "accepted"
                              : action === "declined"
                              ? "declined"
                              : action === "cancelled"
                              ? "cancelled"
                              : action === "booked"
                              ? "booked on both calendars"
                              : action === "book_failed"
                              ? "booking failed"
                              : action;
                          return (
                            <div
                              key={i}
                              style={{
                                display: "flex",
                                gap: "12px",
                                padding: "10px 12px",
                                background: "var(--bg-surface)",
                                borderRadius: "var(--r-sm)",
                                border: "1px solid var(--border-subtle)",
                              }}
                            >
                              <div
                                style={{
                                  width: "8px",
                                  height: "8px",
                                  borderRadius: "999px",
                                  background:
                                    action === "book_failed"
                                      ? "var(--accent-coral)"
                                      : action === "booked"
                                      ? "var(--accent-teal)"
                                      : "var(--accent-blue)",
                                  marginTop: "5px",
                                  flexShrink: 0,
                                }}
                              />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <p
                                  style={{
                                    fontFamily: "DM Sans, sans-serif",
                                    fontSize: "12px",
                                    color: "var(--text-primary)",
                                  }}
                                >
                                  {isMe ? "You " : "The other side "}
                                  {verb}
                                </p>
                                {h.payload && (h.payload.start_time || h.payload.title) && (
                                  <p style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px", fontFamily: "IBM Plex Mono, monospace" }}>
                                    {h.payload.title || ""} {h.payload.start_time ? `· ${formatMeetingTime(h.payload.start_time, h.payload.end_time)}` : ""}
                                  </p>
                                )}
                                {h.reason && (
                                  <p style={{ fontSize: "10px", color: "var(--accent-coral)", marginTop: "2px", fontFamily: "DM Sans, sans-serif" }}>
                                    {h.reason}
                                  </p>
                                )}
                                <p
                                  style={{
                                    fontFamily: "IBM Plex Mono, monospace",
                                    fontSize: "9px",
                                    color: "var(--text-muted)",
                                    marginTop: "3px",
                                  }}
                                >
                                  {when}
                                </p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* ── Connection settings drawer ── */}
            {permissionsOpen && (
              <div
                onClick={() => setPermissionsOpen(false)}
                style={{
                  position: "absolute",
                  inset: 0,
                  background: "rgba(0,0,0,0.55)",
                  zIndex: 200,
                  display: "flex",
                  justifyContent: "flex-end",
                }}
              >
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    width: "360px",
                    maxWidth: "90vw",
                    height: "100%",
                    background: "var(--bg-base)",
                    borderLeft: "1px solid var(--border-default)",
                    display: "flex",
                    flexDirection: "column",
                    boxShadow: "-12px 0 32px rgba(0,0,0,0.4)",
                  }}
                >
                  <div
                    style={{
                      padding: "20px 22px",
                      borderBottom: "1px solid var(--border-subtle)",
                      display: "flex",
                      alignItems: "center",
                      gap: "10px",
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <p
                        style={{
                          fontFamily: "Syne, sans-serif",
                          fontSize: "14px",
                          fontWeight: 700,
                          color: "var(--text-primary)",
                        }}
                      >
                        Connection Settings
                      </p>
                      <p
                        style={{
                          fontFamily: "IBM Plex Mono, monospace",
                          fontSize: "9px",
                          letterSpacing: "0.5px",
                          color: "var(--text-muted)",
                          textTransform: "uppercase",
                          marginTop: "2px",
                        }}
                      >
                        {getPartnerName(activeThread)}
                      </p>
                    </div>
                    <button
                      onClick={() => setPermissionsOpen(false)}
                      style={{
                        width: "26px",
                        height: "26px",
                        borderRadius: "999px",
                        background: "var(--bg-surface)",
                        border: "1px solid var(--border-default)",
                        color: "var(--text-secondary)",
                        cursor: "pointer",
                        fontSize: "12px",
                      }}
                    >
                      ✕
                    </button>
                  </div>

                  <div style={{ padding: "16px 22px 20px", overflowY: "auto", flex: 1 }}>
                    <p
                      className="section-label"
                      style={{ marginBottom: "12px" }}
                    >
                      WHAT THIS CONNECTION CAN DO
                    </p>
                    <p
                      style={{
                        fontFamily: "DM Sans, sans-serif",
                        fontSize: "12px",
                        color: "var(--text-secondary)",
                        lineHeight: 1.55,
                        marginBottom: "18px",
                      }}
                    >
                      These toggles control what the other side's AI agent is allowed to ask
                      yours for, on this thread only. Defaults are conservative — flip on the
                      ones you trust this connection with.
                    </p>

                    {permissions === null ? (
                      <p
                        style={{
                          fontSize: "12px",
                          color: "var(--text-muted)",
                          fontFamily: "IBM Plex Mono, monospace",
                        }}
                      >
                        Loading permissions...
                      </p>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                        {PERMISSION_LABELS.map(({ key, label, help }) => {
                          const on = permissions[key];
                          const saving = permissionsSaving === key;
                          return (
                            <div
                              key={key}
                              style={{
                                padding: "12px 14px",
                                borderRadius: "var(--r-md)",
                                background: "var(--bg-surface)",
                                border: `1px solid ${on ? "rgba(0, 212, 180, 0.30)" : "var(--border-default)"}`,
                                display: "flex",
                                gap: "12px",
                                alignItems: "flex-start",
                              }}
                            >
                              <div style={{ flex: 1 }}>
                                <p
                                  style={{
                                    fontFamily: "DM Sans, sans-serif",
                                    fontSize: "13px",
                                    fontWeight: 500,
                                    color: "var(--text-primary)",
                                    marginBottom: "4px",
                                  }}
                                >
                                  {label}
                                </p>
                                <p
                                  style={{
                                    fontFamily: "DM Sans, sans-serif",
                                    fontSize: "11px",
                                    color: "var(--text-muted)",
                                    lineHeight: 1.5,
                                  }}
                                >
                                  {help}
                                </p>
                              </div>
                              <button
                                onClick={() => toggleConnectionPermission(key)}
                                disabled={saving}
                                style={{
                                  width: "38px",
                                  height: "22px",
                                  borderRadius: "999px",
                                  border: "none",
                                  cursor: saving ? "wait" : "pointer",
                                  background: on
                                    ? "var(--accent-teal)"
                                    : "var(--bg-raised)",
                                  position: "relative",
                                  flexShrink: 0,
                                  transition: "background 0.15s",
                                  opacity: saving ? 0.6 : 1,
                                }}
                                aria-pressed={on}
                                aria-label={label}
                              >
                                <span
                                  style={{
                                    position: "absolute",
                                    top: "2px",
                                    left: on ? "18px" : "2px",
                                    width: "18px",
                                    height: "18px",
                                    borderRadius: "999px",
                                    background: "#fff",
                                    transition: "left 0.15s",
                                    boxShadow: "0 1px 3px rgba(0,0,0,0.4)",
                                  }}
                                />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Input bar — only on the human channel. The agent channel is a
                read-only transparency log; humans don't type into it. */}
            {activeChannel === "human" ? (
              <div
                style={{
                  padding: "16px 24px 20px",
                  borderTop: "1px solid var(--border-subtle)",
                  background: "rgba(13, 17, 23, 0.9)",
                  backdropFilter: "blur(8px)",
                }}
              >
                <div
                  style={{ maxWidth: "720px", margin: "0 auto" }}
                >
                  <div className="input-wrap">
                    <input
                      className="chat-input"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleSend();
                      }}
                      placeholder={
                        activeThread.status === "accepted"
                          ? "Type a message..."
                          : "Awaiting approval..."
                      }
                      disabled={
                        activeThread.status !== "accepted" &&
                        (activeThread.receiver_id === sessionUser.id ||
                          activeThread.receiver_id === sessionAgentId)
                      }
                    />
                    <button
                      onClick={handleSend}
                      disabled={
                        !draft.trim() || activeThread.status === "blocked"
                      }
                      className="btn-primary"
                      style={{ padding: "8px 18px", fontSize: "12px" }}
                    >
                      Send
                    </button>
                  </div>
                </div>
              </div>
            ) : myMode === "human" ? (
              /* Taken-over mode: the user can type on the agent channel */
              <div
                style={{
                  padding: "16px 24px 20px",
                  borderTop: "1px solid var(--border-subtle)",
                  background: "rgba(13, 17, 23, 0.9)",
                  backdropFilter: "blur(8px)",
                }}
              >
                <div style={{ maxWidth: "720px", margin: "0 auto" }}>
                  <div className="input-wrap">
                    <input
                      className="chat-input"
                      value={agentDraft}
                      onChange={(e) => setAgentDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleAgentSend();
                      }}
                      placeholder="You're typing on the agent channel…"
                      disabled={agentSending}
                    />
                    <button
                      onClick={handleAgentSend}
                      disabled={!agentDraft.trim() || agentSending}
                      className="btn-primary"
                      style={{ padding: "8px 18px", fontSize: "12px" }}
                    >
                      {agentSending ? "…" : "Send"}
                    </button>
                    <button
                      onClick={toggleThreadMode}
                      title="Hand back to your AI agent"
                      style={{
                        padding: "8px 12px",
                        fontSize: "10px",
                        fontFamily: "IBM Plex Mono, monospace",
                        background: "rgba(0, 212, 180, 0.08)",
                        border: "1px solid rgba(0, 212, 180, 0.25)",
                        color: "var(--accent-teal)",
                        borderRadius: "var(--r-sm)",
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                      }}
                    >
                      🤖 Resume AI
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              /* AI Handling mode: read-only log with a Take Over button */
              <div
                style={{
                  padding: "14px 24px 18px",
                  borderTop: "1px solid var(--border-subtle)",
                  background: "rgba(13, 17, 23, 0.9)",
                  backdropFilter: "blur(8px)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "12px",
                }}
              >
                <p
                  style={{
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: "10px",
                    color: "var(--text-muted)",
                    letterSpacing: "0.4px",
                  }}
                >
                  Your AI agent is handling this conversation.
                </p>
                <button
                  onClick={toggleThreadMode}
                  style={{
                    padding: "6px 14px",
                    fontSize: "10px",
                    fontFamily: "IBM Plex Mono, monospace",
                    background: "transparent",
                    border: "1px solid var(--border-default)",
                    color: "var(--text-secondary)",
                    borderRadius: "var(--r-sm)",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  👤 Take Over
                </button>
              </div>
            )}
          </>
        ) : (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "12px",
            }}
          >
            <div
              style={{
                width: "48px",
                height: "48px",
                borderRadius: "var(--r-md)",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-default)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "20px",
                color: "var(--text-muted)",
              }}
            >
              ◈
            </div>
            <p
              style={{
                color: "var(--text-muted)",
                fontSize: "13px",
                fontFamily: "DM Sans, sans-serif",
              }}
            >
              Select a connection to start messaging
            </p>
            <p className="section-label">CROSS-NETWORK PROTOCOL</p>
          </div>
        )}
      </div>
    </div>
  );
}
