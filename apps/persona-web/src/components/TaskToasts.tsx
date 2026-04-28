"use client";

/**
 * Global task notifier — listens for `agent_tasks` realtime events and
 * shows ephemeral toast cards so the user learns about meeting proposals,
 * counters, accepts, and bookings even when they aren't currently looking
 * at the relevant thread. Click a toast to jump to the thread.
 *
 * Mounted once at the dashboard layout level. Auto-dismisses each toast
 * after a few seconds; the user can also click × to dismiss early.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Calendar,
  CornerUpLeft,
  CheckCircle,
  AlertTriangle,
  X,
} from "lucide-react";
import { getSupabase } from "@/lib/supabase";

type Tone = "info" | "success" | "warn" | "danger";

interface Toast {
  id: string;
  threadId: string;
  taskId: string;
  title: string;
  body: string;
  tone: Tone;
}

const TOAST_TTL_MS = 8000;

interface AgentTask {
  id: string;
  thread_id: string;
  status: string;
  initiator_user_id: string | null;
  recipient_user_id: string | null;
  payload?: { title?: string };
}

function describeChange(
  task: AgentTask,
  meIsInitiator: boolean,
): { title: string; body: string; tone: Tone } | null {
  const status = task.status;
  const title = task.payload?.title || "Untitled meeting";

  if (status === "proposed") {
    if (meIsInitiator) return null;
    return {
      title: "New meeting proposal",
      body: `Someone wants to schedule "${title}" with you.`,
      tone: "info",
    };
  }
  if (status === "countered") {
    return {
      title: "Meeting countered",
      body: `The other side suggested a different time for "${title}".`,
      tone: "warn",
    };
  }
  if (status === "accepted") {
    return {
      title: "Meeting accepted",
      body: `"${title}" was accepted. I'm booking calendars now.`,
      tone: "success",
    };
  }
  if (status === "scheduled") {
    return {
      title: "On your calendar",
      body: `"${title}" was added to both calendars.`,
      tone: "success",
    };
  }
  if (status === "book_failed") {
    return {
      title: "Couldn't book that one",
      body: `"${title}" didn't make it onto a calendar. Open the thread to retry.`,
      tone: "danger",
    };
  }
  return null;
}

const TONE_ICON: Record<Tone, typeof Calendar> = {
  info:    Calendar,
  warn:    CornerUpLeft,
  success: CheckCircle,
  danger:  AlertTriangle,
};

const TONE_COLOR: Record<Tone, string> = {
  info:    "var(--info)",
  warn:    "var(--warning)",
  success: "var(--success)",
  danger:  "var(--danger)",
};

export default function TaskToasts() {
  const router = useRouter();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const dismissTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

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
      dismissTimers.current[toast.id] = setTimeout(
        () => dismiss(toast.id),
        TOAST_TTL_MS,
      );
    },
    [dismiss],
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
          const task = payload.new as AgentTask;
          if (
            task.initiator_user_id !== userId &&
            task.recipient_user_id !== userId
          )
            return;
          const desc = describeChange(task, task.initiator_user_id === userId);
          if (!desc) return;
          pushToast({
            id: `${task.id}-${task.status}-${Date.now()}`,
            threadId: task.thread_id,
            taskId: task.id,
            ...desc,
          });
        },
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "agent_tasks" },
        (payload) => {
          const task = payload.new as AgentTask;
          const old = payload.old as AgentTask;
          if (
            task.initiator_user_id !== userId &&
            task.recipient_user_id !== userId
          )
            return;
          if (old?.status === task.status) return;
          const desc = describeChange(task, task.initiator_user_id === userId);
          if (!desc) return;
          pushToast({
            id: `${task.id}-${task.status}-${Date.now()}`,
            threadId: task.thread_id,
            taskId: task.id,
            ...desc,
          });
        },
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
      Object.values(dismissTimers.current).forEach(clearTimeout);
      dismissTimers.current = {};
    };
  }, [userId, pushToast]);

  if (toasts.length === 0) return null;

  return (
    <div className="task-toast-stack">
      {toasts.map((t) => {
        const Icon = TONE_ICON[t.tone];
        const accent = TONE_COLOR[t.tone];
        return (
          <div
            key={t.id}
            className="task-toast"
            style={{ borderLeftColor: accent }}
            role="status"
            onClick={() => {
              router.push(`/dashboard/messages?thread=${t.threadId}`);
              dismiss(t.id);
            }}
          >
            <Icon
              size={16}
              strokeWidth={1.5}
              style={{ color: accent, flexShrink: 0, marginTop: 2 }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <p className="task-toast-title">{t.title}</p>
              <p className="task-toast-body">{t.body}</p>
            </div>
            <button
              type="button"
              className="task-toast-dismiss"
              onClick={(e) => {
                e.stopPropagation();
                dismiss(t.id);
              }}
              aria-label="Dismiss"
            >
              <X size={14} strokeWidth={1.5} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
