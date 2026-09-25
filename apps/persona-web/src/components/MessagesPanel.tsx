"use client";

import { useEffect, useState, useRef, Fragment } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUp, Check, Settings, X, Info } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSupabase } from "@/lib/supabase";
import { meetingStatusLabel, meetingTimeline } from "@/lib/meetingStatus";

interface Thread {
  id: string;
  initiator_id: string;
  receiver_id: string;
  initiator_name: string;
  receiver_name: string;
  // ConnectionFSM status. Older rows may pre-date `declined`/`revoked`,
  // but the column accepts them since the v3 migration patched the
  // CHECK constraint.
  status: "pending" | "accepted" | "declined" | "blocked" | "revoked";
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
  pending: { text: "Waiting for them", tag: "tag-amber" },
  active: { text: "Agents talking", tag: "tag-teal" },
  needs_human: { text: "Needs you", tag: "tag-amber" },
  human_handling: { text: "You're handling this", tag: "tag-teal" },
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

  const updateThreadStatus = async (status: string, thread?: Thread) => {
    const target = thread || activeThread;
    if (!target) return;
    await getSupabase()
      .from("dm_threads")
      .update({ status })
      .eq("id", target.id);

    setThreads((prev) =>
      prev.map((t) => (t.id === target.id ? { ...t, status: status as any } : t))
    );
    setActiveThread((prev) =>
      prev && prev.id === target.id ? { ...prev, status: status as any } : prev
    );
  };

  // ConnectionFSM transitions handled by the v3 backend (decline/revoke
  // touch in-flight a2a_tasks too, so we don't update Supabase directly).
  const transitionConnection = async (
    action: "decline" | "revoke" | "unblock",
    thread?: Thread
  ) => {
    const target = thread || activeThread;
    if (!target || !sessionUser) return;
    const res = await fetch(`${API}/api/persona/threads/${target.id}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, user_id: sessionUser.id }),
    });
    if (!res.ok) {
      console.error(`[transitionConnection] ${action} failed:`, await res.text());
      return;
    }
    const data = await res.json();
    setThreads((prev) =>
      prev.map((t) => (t.id === target.id ? { ...t, status: data.new_status } : t))
    );
    setActiveThread((prev) =>
      prev && prev.id === target.id ? { ...prev, status: data.new_status } : prev
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
    if (side === "receiver") return thread.receiver_mode ?? thread.mode ?? "agent";
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

  // dm_threads.initiator_id/receiver_id are agent_ids, not user_ids — the
  // one bulk call resolves the whole visible thread list's avatars via
  // persona_agents + the cached Supabase admin-API avatar map (see
  // /api/persona/avatars), keyed by whatever id getPartnerId() returns.
  const [partnerAvatars, setPartnerAvatars] = useState<Record<string, string | null>>({});
  useEffect(() => {
    const ids = Array.from(new Set(threads.map((t) => getPartnerId(t)))).filter(
      (id) => id && !(id in partnerAvatars)
    );
    if (ids.length === 0) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/persona/avatars?ids=${encodeURIComponent(ids.join(","))}`);
        const map = res.ok ? await res.json() : {};
        if (!cancelled) {
          setPartnerAvatars((prev) => {
            const next = { ...prev };
            for (const id of ids) next[id] = map[id] ?? null;
            return next;
          });
        }
      } catch {
        if (!cancelled) {
          setPartnerAvatars((prev) => {
            const next = { ...prev };
            for (const id of ids) next[id] = null;
            return next;
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads]);

  const [agentDraft, setAgentDraft] = useState("");
  const [agentSending, setAgentSending] = useState(false);

  // Send a human-typed message on the agent channel.
  // If this was a one-off "Reply yourself" action, hand the thread back
  // to the AI agent automatically after the message is sent.
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
      if (agentManualReply) {
        setAgentManualReply(false);
        // Hand the thread back to the AI agent automatically.
        await toggleThreadMode();
      }
    } catch (e) {
      console.error("Failed to send agent-channel message:", e);
    } finally {
      setAgentSending(false);
    }
  };

  const [newChatQuery, setNewChatQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [agentManualReply, setAgentManualReply] = useState(false);

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
        // Use new v2 search endpoint on zns01.zynd.ai
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
            `https://zns01.zynd.ai/v1/search`,
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
                try { parsed = JSON.parse(caps); } catch { }
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
      <div className="messages-loading">
        <div className="status-pill">
          <span className="status-dot" />
          Authenticating...
        </div>
      </div>
    );

  return (
    <div className={`messages-panel ${activeThread ? "has-active-thread" : ""}`}>
      {/* -- Left: Thread Inbox -- */}
      <div className="messages-sidebar">
        {/* Header & Search */}
        <div
          className="messages-sidebar-head"
          style={{
            padding: "20px 16px",
            borderBottom: "1px solid var(--border-subtle)",
            position: "relative",
          }}
        >
          <h2>Network DMs</h2>
          <p className="section-label">Cross-agent messaging</p>
          <input
            type="text"
            placeholder="Search Zynd Network..."
            value={newChatQuery}
            onChange={(e) => setNewChatQuery(e.target.value)}
            className="input"
          />

          {/* Live Search Dropdown */}
          {(searchResults.length > 0 || isSearching) && (
            <div className="messages-search-popover">
              {isSearching ? (
                <div className="messages-search-popover-item desc" style={{ cursor: "default" }}>
                  Searching network...
                </div>
              ) : (
                searchResults.map((p) => (
                  <div
                    key={p.agent_id}
                    onClick={() => startNewChat(p)}
                    className="messages-search-popover-item"
                  >
                    <div className="name">{p.name}</div>
                    <div className="desc">{p.description || "Zynd Agent"}</div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Thread list */}
        <div className="messages-thread-list">
          {/* Requests */}
          {requests.length > 0 && (
            <div className="messages-thread-section">
              <p className="section-label" style={{ color: "var(--accent)" }}>
                Requests ({requests.length})
              </p>
              {requests.map((t) => {
                const partnerId = getPartnerId(t);
                const avatarUrl = partnerAvatars[partnerId];
                const partnerName = getPartnerName(t);
                return (
                  <div
                    key={t.id}
                    onClick={() => setActiveThread(t)}
                    className={`messages-thread-card messages-request-card ${activeThread?.id === t.id ? "is-active" : ""}`}
                  >
                    <Link
                      href={`/p/${partnerId}`}
                      onClick={(e) => e.stopPropagation()}
                      className="messages-request-avatar"
                      aria-label={`View ${partnerName || "profile"}`}
                    >
                      {avatarUrl ? (
                        <img src={avatarUrl} alt="" referrerPolicy="no-referrer" />
                      ) : (
                        <span>{partnerName?.charAt(0) || "Z"}</span>
                      )}
                    </Link>
                    <div className="messages-request-body">
                      <div className="name">New Request</div>
                      <div className="meta">{partnerName}</div>
                    </div>
                    <div className="messages-request-actions">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          updateThreadStatus("accepted", t);
                        }}
                        className="icon-btn-xs accept"
                        title="Accept"
                        aria-label="Accept request"
                      >
                        <Check size={14} strokeWidth={2.4} />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          transitionConnection("decline", t);
                        }}
                        className="icon-btn-xs decline"
                        title="Decline"
                        aria-label="Decline request"
                      >
                        <X size={14} strokeWidth={2.4} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Primary inbox */}
          <div className="messages-thread-section" style={{ padding: "12px 16px" }}>
            <p className="section-label" style={{ marginBottom: "8px" }}>
              PRIMARY INBOX
            </p>
            {primary.map((t) => {
              const partnerName = getPartnerName(t);
              const partnerId = getPartnerId(t);
              const avatarUrl = partnerAvatars[partnerId];
              return (
                <div
                  key={t.id}
                  onClick={() => setActiveThread(t)}
                  className={`messages-thread-card messages-thread-card-row ${activeThread?.id === t.id ? "is-active" : ""}`}
                >
                  <Link
                    href={`/p/${partnerId}`}
                    onClick={(e) => e.stopPropagation()}
                    className="messages-request-avatar"
                    aria-label={`View ${partnerName || "profile"}`}
                  >
                    {avatarUrl ? (
                      <img src={avatarUrl} alt="" referrerPolicy="no-referrer" />
                    ) : (
                      <span>{partnerName?.charAt(0) || "Z"}</span>
                    )}
                  </Link>
                  <div className="messages-request-body">
                  <div className="name">{partnerName}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "4px" }}>
                    {(() => {
                      // Terminal connection states first — these threads rarely
                      // stay in the primary list, but surface them plainly if they do.
                      if (t.status === "blocked") {
                        return (
                          <span className="tag tag-coral">
                            BLOCKED
                          </span>
                        );
                      }
                      if (t.status === "declined") {
                        return (
                          <span className="tag tag-coral">
                            DECLINED
                          </span>
                        );
                      }
                      if (t.status === "revoked") {
                        return (
                          <span className="tag tag-coral">
                            ENDED
                          </span>
                        );
                      }
                      if (t.status === "pending") {
                        return (
                          <span className="tag tag-amber">
                            AWAITING APPROVAL
                          </span>
                        );
                      }
                      // Accepted connection: say "Connected" and add a lifecycle
                      // hint so the user knows what is actually happening on the
                      // agent channel.
                      const phase = t.lifecycle || "pending";
                      const lifecycleHint:
                        | { text: string; tone: "teal" | "amber" }
                        | undefined =
                        phase === "needs_human"
                          ? { text: " · Needs you", tone: "amber" }
                          : phase === "human_handling"
                            ? { text: " · You're handling", tone: "teal" }
                            : phase === "active"
                              ? { text: " · Agents talking", tone: "teal" }
                              : phase === "pending"
                                ? { text: " · Waiting for them", tone: "amber" }
                                : undefined;
                      return (
                        <span
                          className={`tag ${lifecycleHint?.tone === "amber" ? "tag-amber" : "tag-teal"}`}
                        >
                          CONNECTED
                          {lifecycleHint?.text}
                        </span>
                      );
                    })()}
                  </div>
                  </div>
                </div>
              );
            })}
            {primary.length === 0 && (
              <p className="messages-thread-empty">No active chats yet.</p>
            )}
          </div>
        </div>
      </div>

      {/* -- Main Chat Area -- */}
      <div
        className="messages-chat-panel"
        style={{
          position: "relative", // anchor for the connection-settings drawer overlay
        }}
      >
        {activeThread ? (
          <>
            {/* Chat header */}
            <div className="topbar messages-chat-header">
              <button
                type="button"
                className="messages-mobile-back"
                onClick={() => setActiveThread(null)}
                aria-label="Back to threads"
              >
                <ArrowLeft size={16} strokeWidth={1.8} />
              </button>
              <div className="messages-chat-avatar">
                {partnerAvatars[getPartnerId(activeThread)] ? (
                  <img
                    src={partnerAvatars[getPartnerId(activeThread)]!}
                    alt=""
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  getPartnerName(activeThread)?.charAt(0) || "Z"
                )}
              </div>
              <div className="messages-chat-heading">
                <h3>{getPartnerName(activeThread)}</h3>
              </div>
              <div className="messages-chat-actions">
                {(() => {
                  // Terminal connection states take precedence over the
                  // conversation-phase pill — blocked/declined/revoked
                  // mean no traffic flows here at all.
                  if (activeThread.status === "blocked") {
                    return <span className="tag tag-coral">BLOCKED</span>;
                  }
                  if (activeThread.status === "declined") {
                    return <span className="tag tag-coral">DECLINED</span>;
                  }
                  if (activeThread.status === "revoked") {
                    return <span className="tag tag-coral">ENDED</span>;
                  }
                  // Otherwise surface the friendly conversation phase
                  // (pending → active → needs_human → human_handling).
                  const phase = activeThread.lifecycle || "pending";
                  const label = LIFECYCLE_LABEL[phase] || LIFECYCLE_LABEL.pending;
                  return (
                    <span className={`tag ${label.tag}`}>
                      {label.text}
                    </span>
                  );
                })()}

                {/* ── Connection settings (permissions drawer) ── */}
                <button
                  onClick={() => setPermissionsOpen(true)}
                  title="Connection settings"
                  className="icon-btn-sm"
                >
                  <Settings size={16} strokeWidth={1.8} />
                </button>

                {/* ── Mode toggle: controls the AGENT channel only. The human
                    Conversation tab is always manual. ── */}
                <button
                  onClick={toggleThreadMode}
                  title={
                    myMode === "agent"
                      ? "AI is replying on the Agent Activity channel. Click to switch to manual replies."
                      : "You are manually replying on the Agent Activity channel. Click to let your AI take over."
                  }
                  className={`messages-mode-toggle ${myMode === "agent" ? "on" : ""}`}
                >
                  {myMode === "agent" ? "AI replies" : "Manual replies"}
                </button>
              </div>
            </div>

            {/* ── Channel tabs: Conversation vs Agent Activity ── */}
            <div className="messages-channel-tabs">
              {([
                { key: "human", label: "💬 Conversation", help: "Direct human-to-human messages." },
                { key: "agent", label: "🤖 Agent Activity", help: "Read-only log of what your agent and theirs have been saying to each other." },
              ] as { key: ChatChannel; label: string; help: string }[]).map((tab) => {
                const isActive = activeChannel === tab.key;
                return (
                  <button
                    key={tab.key}
                    className={`messages-channel-tab ${isActive ? "is-active" : ""}`}
                    onClick={() => setActiveChannel(tab.key)}
                    title={tab.help}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>

            {/* Messages area */}
            <div className="messages-scroll">
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
                              fontFamily: "var(--font-chakra-petch), system-ui, sans-serif",
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
                              fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif",
                              fontSize: "12px",
                              color: "var(--text-secondary)",
                            }}
                          >
                            {formatMeetingTime(m.payload?.start_time, m.payload?.end_time)}
                          </p>
                          {m.payload?.location && (
                            <p style={{ fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif", fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                              📍 {m.payload.location}
                            </p>
                          )}
                          {m.payload?.description && (
                            <p style={{ fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif", fontSize: "11px", color: "var(--text-muted)", marginTop: "4px", lineHeight: 1.5 }}>
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
                            {meetingStatusLabel({
                              status: m.status,
                              awaitingMe,
                              iProposed,
                            }).toUpperCase()}
                          </span>
                          <button
                            onClick={() => setHistoryModal(m)}
                            title="View history"
                            className="icon-btn-xs"
                          >
                            <Info size={12} strokeWidth={1.8} />
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
                              className="btn btn-primary btn-xs"
                            >
                              Send counter
                            </button>
                            <button
                              onClick={() => setCounterEditing(null)}
                              className="btn btn-secondary btn-xs"
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
                            className="btn btn-primary btn-xs"
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
                            className="btn btn-secondary btn-xs"
                          >
                            Counter
                          </button>
                          <button
                            onClick={() => respondToMeeting(m.id, "decline")}
                            disabled={meetingBusy === m.id}
                            className="btn btn-danger btn-xs"
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
                              fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
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
                            className="messages-pill-btn xs danger"
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
                                  fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif",
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
                              className="btn btn-primary btn-xs"
                            >
                              Retry booking
                            </button>
                            <button
                              onClick={() => respondToMeeting(m.id, "cancel")}
                              disabled={meetingBusy === m.id}
                              className="btn btn-secondary btn-xs"
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
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "6px",
                              flexWrap: "wrap",
                            }}
                          >
                            {meetingTimeline({ status: m.status, awaitingMe, iProposed }).map(
                              (step, idx, arr) => (
                                <Fragment key={step.label}>
                                  <span
                                    style={{
                                      fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
                                      fontSize: "9px",
                                      padding: "2px 8px",
                                      borderRadius: "999px",
                                      background:
                                        step.state === "active"
                                          ? "var(--accent-soft-bg)"
                                          : step.state === "done"
                                            ? "rgba(0, 212, 180, 0.12)"
                                            : "var(--bg-raised)",
                                      color:
                                        step.state === "active"
                                          ? "var(--accent)"
                                          : step.state === "done"
                                            ? "var(--accent-teal)"
                                            : "var(--text-muted)",
                                      border:
                                        step.state === "pending"
                                          ? "1px dashed var(--border-default)"
                                          : "1px solid transparent",
                                    }}
                                  >
                                    {step.state === "done" ? "✓ " : ""}
                                    {step.label}
                                  </span>
                                  {idx < arr.length - 1 && (
                                    <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>
                                      →
                                    </span>
                                  )}
                                </Fragment>
                              )
                            )}
                          </div>
                          {iProposed && (m.status === "proposed" || m.status === "countered") && (
                            <button
                              onClick={() => respondToMeeting(m.id, "cancel")}
                              disabled={meetingBusy === m.id}
                              className="messages-pill-btn xs"
                            >
                              WITHDRAW
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}

              {/* Agent-mode banner — only shown inside the Agent Activity channel.
                  The Conversation tab is always human-to-human; the AI never posts there. */}
              {activeChannel === "agent" &&
                myMode === "agent" &&
                activeThread.status !== "blocked" && (
                  <div
                    style={{
                      background: "rgba(0, 212, 180, 0.06)",
                      border: "1px solid rgba(0, 212, 180, 0.20)",
                      padding: "10px 14px",
                      borderRadius: "var(--r-md)",
                      color: "var(--accent-teal)",
                      fontSize: "12px",
                      fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif",
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
                      onClick={() => {
                        setAgentManualReply(true);
                        toggleThreadMode();
                      }}
                      className="messages-pill-btn xs teal"
                    >
                      Reply yourself
                    </button>
                  </div>
                )}

              {/* Pending request banner */}
              {activeThread.status === "pending" &&
                (activeThread.receiver_id === sessionUser.id ||
                  activeThread.receiver_id === sessionAgentId) && (
                  <div
                    style={{
                      background: "var(--surface)",
                      border: "1px solid var(--border-subtle)",
                      padding: "24px 28px",
                      borderRadius: "16px",
                      textAlign: "center",
                      alignSelf: "center",
                      maxWidth: "460px",
                      boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
                    }}
                  >
                    <p
                      style={{
                        margin: "0 0 18px",
                        fontSize: "13.5px",
                        color: "var(--text-secondary)",
                        lineHeight: 1.55,
                      }}
                    >
                      This network agent is requesting to connect with you.
                      Accepting allows them to message and orchestrate tools on
                      your behalf.
                    </p>
                    <div
                      style={{
                        display: "flex",
                        gap: "8px",
                        justifyContent: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <button
                        onClick={() => updateThreadStatus("accepted")}
                        className="btn btn-primary"
                      >
                        Accept request
                      </button>
                      <button
                        onClick={() => transitionConnection("decline")}
                        className="btn btn-secondary"
                      >
                        Decline
                      </button>
                      <button
                        onClick={() => updateThreadStatus("blocked")}
                        className="btn btn-secondary btn-danger-quiet"
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
                          fontFamily: "var(--font-geist), 'Inter', system-ui, sans-serif",
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
                            fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
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
                      className={`messages-bubble-row ${isMe ? "is-mine" : ""}`}
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
                          className="messages-bubble-avatar"
                          style={{
                            width: "28px",
                            height: "28px",
                            borderRadius: "var(--r-sm)",
                            overflow: "hidden",
                            background: partnerAvatars[getPartnerId(activeThread)]
                              ? "var(--surface-raised)"
                              : "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontFamily: "var(--font-chakra-petch), system-ui, sans-serif",
                            fontWeight: 800,
                            fontSize: "11px",
                            color: "#fff",
                            flexShrink: 0,
                            marginTop: "2px",
                          }}
                        >
                          {partnerAvatars[getPartnerId(activeThread)] ? (
                            <img
                              src={partnerAvatars[getPartnerId(activeThread)]!}
                              alt=""
                              referrerPolicy="no-referrer"
                              style={{ width: "100%", height: "100%", objectFit: "cover" }}
                            />
                          ) : (
                            getPartnerName(activeThread)?.charAt(0) || "A"
                          )}
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
                                fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
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
              <div className="messages-modal-scrim" onClick={() => setHistoryModal(null)}>
                <div className="messages-modal-shell" onClick={(e) => e.stopPropagation()}>
                  <div className="messages-panel-head">
                    <div style={{ flex: 1 }}>
                      <p className="messages-panel-title">Meeting history</p>
                      <p className="messages-panel-subtitle">
                        {historyModal.payload?.title || "Untitled meeting"}
                      </p>
                    </div>
                    <button
                      onClick={() => setHistoryModal(null)}
                      className="messages-panel-close"
                      aria-label="Close"
                    >
                      <X size={14} strokeWidth={1.8} />
                    </button>
                  </div>

                  <div className="messages-panel-body">
                    {historyModal.history.length === 0 ? (
                      <p className="messages-history-empty">No history yet.</p>
                    ) : (
                      <div className="messages-history-list">
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
                          const dotClass =
                            action === "book_failed"
                              ? "messages-history-dot is-failed"
                              : action === "booked"
                                ? "messages-history-dot is-booked"
                                : "messages-history-dot";
                          return (
                            <div key={i} className="messages-history-row">
                              <div className={dotClass} />
                              <div className="messages-history-row-body">
                                <p className="action">
                                  {isMe ? "You " : "The other side "}
                                  {verb}
                                </p>
                                {h.payload && (h.payload.start_time || h.payload.title) && (
                                  <p className="meta">
                                    {h.payload.title || ""} {h.payload.start_time ? `· ${formatMeetingTime(h.payload.start_time, h.payload.end_time)}` : ""}
                                  </p>
                                )}
                                {h.reason && <p className="reason">{h.reason}</p>}
                                <p className="when">{when}</p>
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
              <div className="messages-drawer-scrim" onClick={() => setPermissionsOpen(false)}>
                <div className="messages-drawer-shell" onClick={(e) => e.stopPropagation()}>
                  <div className="messages-panel-head">
                    <div style={{ flex: 1 }}>
                      <p className="messages-panel-title">Connection Settings</p>
                      <p className="messages-panel-subtitle">{getPartnerName(activeThread)}</p>
                    </div>
                    <button
                      onClick={() => setPermissionsOpen(false)}
                      className="messages-panel-close"
                      aria-label="Close"
                    >
                      <X size={14} strokeWidth={1.8} />
                    </button>
                  </div>

                  <div className="messages-panel-body">
                    <p className="section-label" style={{ marginBottom: "12px" }}>
                      WHAT THIS CONNECTION CAN DO
                    </p>
                    <p className="messages-panel-lead">
                      These toggles control what the other side's AI agent is allowed to ask
                      yours for, on this thread only. Defaults are conservative — flip on the
                      ones you trust this connection with.
                    </p>

                    {permissions === null ? (
                      <p className="messages-history-empty">Loading permissions...</p>
                    ) : (
                      <div>
                        {PERMISSION_LABELS.map(({ key, label, help }) => {
                          const on = permissions[key];
                          const saving = permissionsSaving === key;
                          return (
                            <div key={key} className={`permission-row ${on ? "is-on" : ""}`}>
                              <div className="permission-row-label">
                                <p className="name">{label}</p>
                                <p className="help">{help}</p>
                              </div>
                              <button
                                onClick={() => toggleConnectionPermission(key)}
                                disabled={saving}
                                className={`permission-toggle ${on ? "is-on" : ""}`}
                                aria-pressed={on}
                                aria-label={label}
                              >
                                <span className="knob" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Connection management — Revoke for accepted, Unblock for blocked */}
                    {activeThread.status === "accepted" && (
                      <div className="messages-mgmt-card">
                        <p>
                          End this connection. Past messages stay visible for
                          your records, but no new traffic flows in either
                          direction. Any in-flight agent work is canceled.
                        </p>
                        <button
                          onClick={async () => {
                            if (
                              window.confirm(
                                "End this connection? The other side will see it as ended.",
                              )
                            ) {
                              await transitionConnection("revoke");
                              setPermissionsOpen(false);
                            }
                          }}
                          className="btn btn-danger btn-xs"
                        >
                          End connection
                        </button>
                      </div>
                    )}
                    {activeThread.status === "blocked" && (
                      <div className="messages-mgmt-card">
                        <p>
                          You blocked this connection. Unblocking restores it
                          to accepted; future messages flow normally.
                        </p>
                        <button
                          onClick={async () => {
                            await transitionConnection("unblock");
                            setPermissionsOpen(false);
                          }}
                          className="btn btn-xs btn-accent"
                        >
                          Unblock
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Input bar — human channel is always manual. Agent channel defaults
                to AI replies but supports one-off manual replies via "Reply yourself". */}
            {activeChannel === "human" ? (
              <div className="messages-composer">
                <div className="messages-composer-inner">
                  <div className="input-wrap">
                    <div className="input-wrap-inner">
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
                            : activeThread.status === "declined"
                              ? "Connection declined."
                              : activeThread.status === "revoked"
                                ? "Connection ended."
                                : activeThread.status === "blocked"
                                  ? "Blocked."
                                  : "Awaiting approval..."
                        }
                        disabled={
                          activeThread.status !== "accepted"
                        }
                      />
                      <button
                        onClick={handleSend}
                        disabled={
                          !draft.trim() || activeThread.status !== "accepted"
                        }
                        className="btn-primary"
                        aria-label="Send"
                      >
                        <ArrowUp />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ) : myMode === "human" || agentManualReply ? (
              /* User is typing on the agent channel (permanent take-over or one-off reply). */
              <div className="messages-composer">
                <div className="messages-composer-inner">
                  <div className="input-wrap">
                    <div className="input-wrap-inner">
                      <input
                        className="chat-input"
                        value={agentDraft}
                        onChange={(e) => setAgentDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleAgentSend();
                        }}
                        placeholder={
                          agentManualReply
                            ? "Type your reply… (AI will resume after you send)"
                            : "You're typing on the agent channel…"
                        }
                        disabled={agentSending}
                      />
                      <button
                        onClick={handleAgentSend}
                        disabled={!agentDraft.trim() || agentSending}
                        className="btn-primary"
                        aria-label="Send"
                      >
                        <ArrowUp />
                      </button>
                    </div>
                  </div>
                  {!agentManualReply && (
                    <button
                      onClick={toggleThreadMode}
                      title="Hand back to your AI agent"
                      className="messages-pill-btn teal"
                    >
                      🤖 Resume AI
                    </button>
                  )}
                  {agentManualReply && (
                    <button
                      onClick={() => setAgentManualReply(false)}
                      title="Cancel and keep AI handling"
                      className="messages-pill-btn"
                    >
                      Cancel
                    </button>
                  )}
                </div>
              </div>
            ) : (
              /* AI Handling mode: offer a one-off manual reply without permanently taking over. */
              <div className="messages-ai-notice">
                <p>Your AI agent is handling this conversation.</p>
                <button
                  onClick={() => {
                    setAgentManualReply(true);
                    toggleThreadMode();
                  }}
                  className="messages-pill-btn"
                >
                  ✍️ Reply yourself
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="messages-empty-state">
            <div className="icon-box">◈</div>
            <p>Select a connection to start messaging</p>
            <p className="section-label">CROSS-NETWORK PROTOCOL</p>
          </div>
        )}
      </div>
    </div>
  );
}
