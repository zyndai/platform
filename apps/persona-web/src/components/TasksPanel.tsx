"use client";

/**
 * Tasks panel — unified inbox of "things waiting on me" across every
 * thread. Shows two sections:
 *
 *   1. Awaiting You    — tickets where the next move is yours.
 *                        Inline Accept / Counter / Decline buttons.
 *   2. Awaiting Them   — tickets where you're waiting on the other side,
 *                        plus 'scheduled' meetings as a reference list.
 *
 * Realtime: subscribes to agent_tasks INSERT/UPDATE/DELETE so the lists
 * stay in sync without polling. Each card has a "Open in DMs" link to
 * jump to the thread it lives on.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MeetingTask {
  id: string;
  thread_id: string;
  status: "proposed" | "countered" | "accepted" | "scheduled" | "declined" | "cancelled" | "book_failed";
  initiator_user_id: string;
  recipient_user_id: string;
  payload: {
    title?: string;
    start_time?: string;
    end_time?: string;
    location?: string;
    description?: string;
  };
  history: { at: string; actor_user_id: string; action: string }[];
  created_at: string;
}

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

export default function TasksPanel() {
  const router = useRouter();
  const [userId, setUserId] = useState<string | null>(null);
  const [awaitingMe, setAwaitingMe] = useState<MeetingTask[]>([]);
  const [awaitingThem, setAwaitingThem] = useState<MeetingTask[]>([]);
  const [scheduled, setScheduled] = useState<MeetingTask[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSupabase()
      .auth.getSession()
      .then(({ data }) => setUserId(data.session?.user?.id ?? null));
  }, []);

  // Fetch + realtime
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;

    const reload = async () => {
      try {
        const res = await fetch(`${API}/api/meetings/pending/${userId}`);
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (cancelled) return;
        setAwaitingMe(data.awaiting_me || []);
        setAwaitingThem(data.awaiting_them || []);
      } catch (e) {
        console.error("Failed to load pending tasks:", e);
      }

      // Scheduled meetings come from the same table; pull via supabase client
      // since the pending endpoint excludes terminal-ish states.
      try {
        const sb = getSupabase();
        const { data: rows } = await sb
          .from("agent_tasks")
          .select("*")
          .or(`initiator_user_id.eq.${userId},recipient_user_id.eq.${userId}`)
          .eq("status", "scheduled")
          .order("created_at", { ascending: false });
        if (!cancelled && rows) setScheduled(rows as MeetingTask[]);
      } catch (e) {
        console.error("Failed to load scheduled tasks:", e);
      }

      if (!cancelled) setLoading(false);
    };

    reload();

    // Realtime: any change to agent_tasks for me triggers a refetch.
    // Cheap because the lists are small and the endpoint is fast.
    const sb = getSupabase();
    const channel = sb
      .channel(`tasks-panel-${userId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "agent_tasks" },
        (payload) => {
          const row = (payload.new || payload.old) as any;
          if (!row) return;
          if (row.initiator_user_id === userId || row.recipient_user_id === userId) {
            reload();
          }
        }
      )
      .subscribe();

    return () => {
      cancelled = true;
      sb.removeChannel(channel);
    };
  }, [userId]);

  const respond = async (
    taskId: string,
    action: "accept" | "decline" | "cancel"
  ) => {
    if (!userId) return;
    setBusy(taskId);
    try {
      const res = await fetch(`${API}/api/meetings/${taskId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actor_user_id: userId, action }),
      });
      if (!res.ok) throw new Error(await res.text());
      // The realtime subscription will rebuild the lists shortly.
    } catch (e) {
      console.error("Failed to respond:", e);
      alert(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "40px", color: "var(--text-muted)", fontFamily: "IBM Plex Mono, monospace", fontSize: "12px" }}>
        Loading tasks…
      </div>
    );
  }

  const renderCard = (m: MeetingTask, mode: "awaiting_me" | "awaiting_them" | "scheduled") => {
    const isInitiator = m.initiator_user_id === userId;
    const accent =
      mode === "awaiting_me"
        ? "rgba(245, 158, 11, 0.35)"
        : mode === "scheduled"
        ? "rgba(0, 212, 180, 0.35)"
        : "var(--border-default)";

    return (
      <div
        key={m.id}
        style={{
          background: "var(--bg-surface)",
          border: `1px solid ${accent}`,
          borderRadius: "var(--r-md)",
          padding: "16px 18px",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
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
          </div>
          <span
            className={
              m.status === "scheduled"
                ? "tag tag-teal"
                : mode === "awaiting_me"
                ? "tag tag-amber"
                : "tag"
            }
            style={{ fontSize: "9px", flexShrink: 0 }}
          >
            {m.status === "scheduled" ? "✓ ON CALENDAR" : m.status.toUpperCase()}
          </span>
        </div>

        <div style={{ marginTop: "12px", display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
          {mode === "awaiting_me" && (
            <>
              <button
                onClick={() => respond(m.id, "accept")}
                disabled={busy === m.id}
                className="btn-primary"
                style={{ padding: "6px 14px", fontSize: "11px" }}
              >
                Accept
              </button>
              <button
                onClick={() => router.push(`/dashboard/messages?thread=${m.thread_id}`)}
                className="btn-secondary"
                style={{ padding: "6px 14px", fontSize: "11px" }}
              >
                Counter / Decline
              </button>
            </>
          )}
          {mode === "awaiting_them" && isInitiator && (
            <button
              onClick={() => respond(m.id, "cancel")}
              disabled={busy === m.id}
              className="btn-secondary"
              style={{ padding: "6px 14px", fontSize: "11px" }}
            >
              Withdraw
            </button>
          )}
          <button
            onClick={() => router.push(`/dashboard/messages?thread=${m.thread_id}`)}
            style={{
              marginLeft: "auto",
              padding: "6px 12px",
              fontSize: "10px",
              fontFamily: "IBM Plex Mono, monospace",
              background: "transparent",
              border: "1px solid var(--border-default)",
              color: "var(--text-secondary)",
              borderRadius: "var(--r-sm)",
              cursor: "pointer",
            }}
          >
            OPEN IN DMS →
          </button>
        </div>
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-base)" }}>
      <div className="topbar" style={{ flexDirection: "column", alignItems: "flex-start", justifyContent: "center", height: "auto", padding: "20px 24px" }}>
        <h1 style={{ fontFamily: "Syne, sans-serif", fontSize: "18px", fontWeight: 700, marginBottom: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "var(--accent-teal)" }}>◈</span> Tasks
        </h1>
        <p className="section-label">PENDING ACROSS ALL THREADS</p>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "28px" }}>

          {/* Awaiting You */}
          <section>
            <p className="section-label" style={{ marginBottom: "12px", color: "#f59e0b" }}>
              AWAITING YOU ({awaitingMe.length})
            </p>
            {awaitingMe.length === 0 ? (
              <p style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "DM Sans, sans-serif" }}>
                Nothing on your plate right now.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {awaitingMe.map((m) => renderCard(m, "awaiting_me"))}
              </div>
            )}
          </section>

          {/* Awaiting Them */}
          <section>
            <p className="section-label" style={{ marginBottom: "12px" }}>
              WAITING ON OTHERS ({awaitingThem.length})
            </p>
            {awaitingThem.length === 0 ? (
              <p style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "DM Sans, sans-serif" }}>
                No outstanding requests sent.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {awaitingThem.map((m) => renderCard(m, "awaiting_them"))}
              </div>
            )}
          </section>

          {/* Scheduled (calendar landed) */}
          <section>
            <p className="section-label" style={{ marginBottom: "12px", color: "var(--accent-teal)" }}>
              SCHEDULED ({scheduled.length})
            </p>
            {scheduled.length === 0 ? (
              <p style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "DM Sans, sans-serif" }}>
                No meetings booked yet.
              </p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {scheduled.map((m) => renderCard(m, "scheduled"))}
              </div>
            )}
          </section>

        </div>
      </div>
    </div>
  );
}
