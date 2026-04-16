"use client";

/**
 * Global task notifier — listens for agent_tasks realtime events and shows
 * ephemeral toast cards so the user learns about meeting proposals,
 * counters, accepts, and bookings even when they aren't currently looking
 * at the relevant thread. Click a toast to jump straight to the message
 * thread that owns the ticket.
 *
 * Mounted once at the dashboard layout level. Auto-dismisses each toast
 * after a few seconds; the user can also click the × to dismiss early.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

interface Toast {
  id: string;
  threadId: string;
  taskId: string;
  title: string;
  body: string;
  tone: "info" | "success" | "warn" | "danger";
}

const TOAST_TTL_MS = 8000;

// Map an agent_tasks status change to a toast title/body/tone.
// Returns null if the change isn't worth notifying about (e.g. cancelled,
// declined — those are dead ends).
function describeChange(
  task: any,
  meIsInitiator: boolean
): { title: string; body: string; tone: Toast["tone"] } | null {
  const status: string = task.status;
  const payload = task.payload || {};
  const title = payload.title || "Untitled meeting";

  if (status === "proposed") {
    if (meIsInitiator) return null; // I'm the one who sent it
    return {
      title: "📅 New meeting proposal",
      body: `Someone wants to schedule "${title}" with you.`,
      tone: "info",
    };
  }
  if (status === "countered") {
    return {
      title: "↩ Meeting countered",
      body: `The other side suggested a different time for "${title}".`,
      tone: "warn",
    };
  }
  if (status === "accepted") {
    return {
      title: "✓ Meeting accepted",
      body: `"${title}" was accepted. Booking calendars now…`,
      tone: "success",
    };
  }
  if (status === "scheduled") {
    return {
      title: "✓ Meeting on your calendar",
      body: `"${title}" was added to both calendars.`,
      tone: "success",
    };
  }
  if (status === "book_failed") {
    return {
      title: "⚠ Calendar booking failed",
      body: `"${title}" could not be added to a calendar. Open the thread to retry.`,
      tone: "danger",
    };
  }
  return null;
}

export default function TaskToasts() {
  const router = useRouter();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const dismissTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Resolve current user once.
  useEffect(() => {
    getSupabase()
      .auth.getSession()
      .then(({ data }) => setUserId(data.session?.user?.id ?? null));
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const timer = dismissTimers.current[id];
    if (timer) {
      clearTimeout(timer);
      delete dismissTimers.current[id];
    }
  }, []);

  const pushToast = useCallback(
    (toast: Toast) => {
      setToasts((prev) => {
        // Replace any existing toast for the same task id so we don't pile
        // up "proposed → countered → accepted" notifications.
        const filtered = prev.filter((t) => t.taskId !== toast.taskId);
        return [...filtered, toast];
      });
      const existing = dismissTimers.current[toast.id];
      if (existing) clearTimeout(existing);
      dismissTimers.current[toast.id] = setTimeout(() => dismiss(toast.id), TOAST_TTL_MS);
    },
    [dismiss]
  );

  useEffect(() => {
    if (!userId) return;

    const sb = getSupabase();
    const channel = sb
      .channel(`task-toasts-${userId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "agent_tasks" },
        (payload) => {
          const task = payload.new as any;
          // Only notify if the user is a participant
          if (task.initiator_user_id !== userId && task.recipient_user_id !== userId) return;
          const desc = describeChange(task, task.initiator_user_id === userId);
          if (!desc) return;
          pushToast({
            id: `${task.id}-${task.status}-${Date.now()}`,
            threadId: task.thread_id,
            taskId: task.id,
            ...desc,
          });
        }
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "agent_tasks" },
        (payload) => {
          const task = payload.new as any;
          const old = payload.old as any;
          if (task.initiator_user_id !== userId && task.recipient_user_id !== userId) return;
          // Only fire when the status actually changed (skip payload edits etc.)
          if (old?.status === task.status) return;
          const desc = describeChange(task, task.initiator_user_id === userId);
          if (!desc) return;
          pushToast({
            id: `${task.id}-${task.status}-${Date.now()}`,
            threadId: task.thread_id,
            taskId: task.id,
            ...desc,
          });
        }
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
      // Clean up any pending dismiss timers
      Object.values(dismissTimers.current).forEach(clearTimeout);
      dismissTimers.current = {};
    };
  }, [userId, pushToast]);

  if (toasts.length === 0) return null;

  return (
    <div
      style={{
        position: "fixed",
        bottom: "24px",
        right: "24px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
        zIndex: 1000,
        maxWidth: "340px",
      }}
    >
      {toasts.map((t) => {
        const accent =
          t.tone === "success"
            ? "var(--accent-teal)"
            : t.tone === "warn"
            ? "#f59e0b"
            : t.tone === "danger"
            ? "var(--accent-coral)"
            : "var(--accent-blue)";
        return (
          <div
            key={t.id}
            onClick={() => {
              router.push(`/dashboard/messages?thread=${t.threadId}`);
              dismiss(t.id);
            }}
            style={{
              cursor: "pointer",
              background: "var(--bg-overlay)",
              border: `1px solid ${accent}`,
              borderLeft: `3px solid ${accent}`,
              borderRadius: "var(--r-md)",
              padding: "12px 14px",
              boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
              animation: "slideIn 0.2s ease",
              display: "flex",
              gap: "10px",
              alignItems: "flex-start",
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <p
                style={{
                  fontFamily: "Syne, sans-serif",
                  fontSize: "13px",
                  fontWeight: 700,
                  color: "var(--text-primary)",
                  marginBottom: "2px",
                }}
              >
                {t.title}
              </p>
              <p
                style={{
                  fontFamily: "DM Sans, sans-serif",
                  fontSize: "11.5px",
                  color: "var(--text-secondary)",
                  lineHeight: 1.45,
                }}
              >
                {t.body}
              </p>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                dismiss(t.id);
              }}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: 0,
                fontSize: "14px",
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
