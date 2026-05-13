"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Inbox as InboxIcon,
  Clock,
  Calendar,
  CheckSquare,
  ShieldCheck,
  ArrowRight,
} from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost } from "@/lib/api";

interface MeetingTicket {
  id: string;
  status: "proposed" | "countered" | "accepted";
  thread_id?: string;
  payload: {
    title?: string;
    start_time?: string;
    end_time?: string;
    location?: string;
  };
}

interface PendingApproval {
  id: string;
  tool_name: string;
  summary?: string;
  created_at: string;
  expires_at?: string;
  thread_id?: string | null;
}

interface Todo {
  id: string;
  title: string;
  source_text?: string | null;
  done: boolean;
  created_at: string;
}

interface InboxState {
  meetingsAwaitingMe: MeetingTicket[];
  meetingsAwaitingThem: MeetingTicket[];
  approvals: PendingApproval[];
  todos: Todo[];
}

const EMPTY_STATE: InboxState = {
  meetingsAwaitingMe: [],
  meetingsAwaitingThem: [],
  approvals: [],
  todos: [],
};

function formatMeetingTime(start?: string, end?: string): string {
  if (!start) return "Time TBD";
  try {
    const s = new Date(start);
    const dateStr = s.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    const startStr = s.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (!end) return `${dateStr} · ${startStr}`;
    const e = new Date(end);
    const endStr = e.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return `${dateStr} · ${startStr} – ${endStr}`;
  } catch {
    return start;
  }
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  try {
    const diffSec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (diffSec < 60) return "just now";
    const min = Math.round(diffSec / 60);
    if (min < 60) return `${min} min ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.round(hr / 24);
    return `${day}d ago`;
  } catch {
    return "";
  }
}

export default function InboxPage() {
  const { user } = useDashboard();
  const [state, setState] = useState<InboxState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user?.id) return;
    setError(null);
    try {
      // Parallel fetch — one failure shouldn't block the rest of the inbox.
      const [meetings, approvals, todos] = await Promise.allSettled([
        apiGet<{ awaiting_me: MeetingTicket[]; awaiting_them: MeetingTicket[] }>(
          `/api/meetings/pending/${user.id}`,
        ),
        apiGet<{ approvals: PendingApproval[] }>(`/api/approvals/`),
        apiGet<{ todos: Todo[] }>(`/api/todos/`),
      ]);

      setState({
        meetingsAwaitingMe:
          meetings.status === "fulfilled" ? meetings.value.awaiting_me ?? [] : [],
        meetingsAwaitingThem:
          meetings.status === "fulfilled" ? meetings.value.awaiting_them ?? [] : [],
        approvals: approvals.status === "fulfilled" ? approvals.value.approvals ?? [] : [],
        // Only open (undone) todos belong on the inbox; done ones live on the
        // Todos page for review.
        todos:
          todos.status === "fulfilled"
            ? (todos.value.todos ?? []).filter((t) => !t.done)
            : [],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load your inbox.");
      setState(EMPTY_STATE);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Refresh on tab focus — the inbox should never feel stale on return.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [load]);

  if (loading || !state) {
    return (
      <div style={{ padding: "40px 32px" }}>
        <p style={{ color: "var(--text-muted)" }}>Loading your inbox…</p>
      </div>
    );
  }

  const actionCount =
    state.approvals.length + state.meetingsAwaitingMe.length + state.todos.length;
  const waitingCount = state.meetingsAwaitingThem.length;
  const totalCount = actionCount + waitingCount;

  if (totalCount === 0) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: "56px 32px 48px", width: "100%" }}>
        <Header subtitle="Nothing needs you right now." />
        {error && <ErrorBanner message={error} onRetry={load} />}
        <EmptyState
          illustration={<InboxIcon />}
          title="Inbox zero."
          body="No pending approvals, meeting requests, or open todos. Your agent will surface anything new here as it comes in. While you wait, share your public agent card so people can find you."
          action={
            user?.id ? (
              <Link href={`/p/${user.id}`} target="_blank" rel="noopener noreferrer">
                <Button>Open my public card →</Button>
              </Link>
            ) : (
              <Link href="/dashboard/chat">
                <Button variant="secondary">Open chat</Button>
              </Link>
            )
          }
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "40px 32px 64px", width: "100%" }}>
      <Header
        subtitle={
          actionCount === 0
            ? "Nothing needs your input — just waiting on others."
            : `${actionCount} thing${actionCount === 1 ? "" : "s"} need${actionCount === 1 ? "s" : ""} you${waitingCount > 0 ? `, plus ${waitingCount} waiting on others.` : "."}`
        }
      />

      {error && <ErrorBanner message={error} onRetry={load} />}

      {state.approvals.length > 0 && (
        <Section
          icon={<ShieldCheck size={14} strokeWidth={1.7} />}
          title="DECISIONS NEEDED"
          count={state.approvals.length}
        >
          {state.approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} onResolved={load} />
          ))}
        </Section>
      )}

      {state.meetingsAwaitingMe.length > 0 && (
        <Section
          icon={<Calendar size={14} strokeWidth={1.7} />}
          title="MEETING REQUESTS"
          count={state.meetingsAwaitingMe.length}
        >
          {state.meetingsAwaitingMe.map((m) => (
            <MeetingRow key={m.id} ticket={m} awaitingMe />
          ))}
        </Section>
      )}

      {state.todos.length > 0 && (
        <Section
          icon={<CheckSquare size={14} strokeWidth={1.7} />}
          title="YOUR TODOS"
          count={state.todos.length}
          rightSlot={
            <Link
              href="/dashboard/todos"
              style={{
                fontSize: 12,
                color: "var(--text-muted)",
                textDecoration: "none",
              }}
            >
              See all →
            </Link>
          }
        >
          {state.todos.slice(0, 5).map((t) => (
            <TodoRow key={t.id} todo={t} />
          ))}
        </Section>
      )}

      {state.meetingsAwaitingThem.length > 0 && (
        <Section
          icon={<Clock size={14} strokeWidth={1.7} />}
          title="WAITING ON OTHERS"
          count={state.meetingsAwaitingThem.length}
          muted
        >
          {state.meetingsAwaitingThem.map((m) => (
            <MeetingRow key={m.id} ticket={m} awaitingMe={false} />
          ))}
        </Section>
      )}
    </div>
  );
}

function Header({ subtitle }: { subtitle: string }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h1 className="display-m" style={{ margin: 0, marginBottom: 8 }}>Inbox</h1>
      <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: 15, lineHeight: 1.55 }}>
        {subtitle}
      </p>
    </div>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      style={{
        padding: "10px 14px",
        marginBottom: "16px",
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-sm)",
        color: "var(--text-secondary)",
        fontSize: "13px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: "12px",
      }}
    >
      <span>Couldn&apos;t load some of your inbox: {message}</span>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={onRetry}
        style={{ fontSize: "12px", padding: "4px 12px", whiteSpace: "nowrap" }}
      >
        Retry
      </button>
    </div>
  );
}

function Section({
  title,
  count,
  icon,
  children,
  muted,
  rightSlot,
}: {
  title: string;
  count: number;
  icon?: React.ReactNode;
  children: React.ReactNode;
  muted?: boolean;
  rightSlot?: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: 28, opacity: muted ? 0.85 : 1 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 10,
          gap: 12,
        }}
      >
        <div
          className="section-label"
          style={{ display: "inline-flex", alignItems: "center", gap: 8, margin: 0 }}
        >
          {icon}
          <span>{title} · {count}</span>
        </div>
        {rightSlot}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{children}</div>
    </section>
  );
}

function CardShell({ href, children }: { href?: string; children: React.ReactNode }) {
  const style: React.CSSProperties = {
    display: "block",
    textDecoration: "none",
    color: "inherit",
    padding: "14px 16px",
    background: "var(--bg-surface)",
    border: "1px solid var(--border-default)",
    borderRadius: "var(--r-md)",
    boxShadow: "0 1px 0 rgba(15,23,42,0.02)",
  };
  return href ? (
    <Link href={href} style={style}>{children}</Link>
  ) : (
    <div style={style}>{children}</div>
  );
}

function MeetingRow({ ticket, awaitingMe }: { ticket: MeetingTicket; awaitingMe: boolean }) {
  const { title, start_time, end_time, location } = ticket.payload;
  const href = ticket.thread_id
    ? `/dashboard/messages?thread=${ticket.thread_id}`
    : "/dashboard/meetings";
  return (
    <CardShell href={href}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: "var(--text-primary)" }}>
          {title || "Untitled meeting"}
        </h3>
        <StatusPill tone={awaitingMe ? "action" : ticket.status === "accepted" ? "accepted" : "neutral"}>
          {awaitingMe ? "Your reply" : ticket.status === "accepted" ? "Accepted" : "Sent"}
        </StatusPill>
      </div>
      <div
        style={{
          display: "flex",
          gap: 16,
          marginTop: 6,
          color: "var(--text-secondary)",
          fontSize: 12.5,
          flexWrap: "wrap",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Clock size={12} strokeWidth={1.7} /> {formatMeetingTime(start_time, end_time)}
        </span>
        {location && <span>· {location}</span>}
      </div>
    </CardShell>
  );
}

function TodoRow({ todo }: { todo: Todo }) {
  return (
    <CardShell href="/dashboard/todos">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <span
            aria-hidden="true"
            style={{
              width: 14,
              height: 14,
              borderRadius: 4,
              border: "1.5px solid var(--border-default)",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontSize: 14,
              color: "var(--text-primary)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {todo.title}
          </span>
        </div>
        <span style={{ color: "var(--text-muted)", fontSize: 11.5, whiteSpace: "nowrap" }}>
          {timeAgo(todo.created_at)}
        </span>
      </div>
    </CardShell>
  );
}

function ApprovalCard({
  approval,
  onResolved,
}: {
  approval: PendingApproval;
  onResolved: () => void | Promise<void>;
}) {
  const [working, setWorking] = useState<"approve" | "decline" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const decide = async (decision: "approve" | "decline") => {
    setWorking(decision);
    setErr(null);
    try {
      await apiPost(`/api/approvals/${approval.id}/decide`, { decision });
      await onResolved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong.");
      setWorking(null);
    }
  };

  return (
    <CardShell>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>
            {prettyToolName(approval.tool_name)}
          </div>
          <div
            style={{
              marginTop: 4,
              fontSize: 14,
              color: "var(--text-primary)",
              lineHeight: 1.45,
              wordBreak: "break-word",
            }}
          >
            {approval.summary || `Approve running ${approval.tool_name}?`}
          </div>
          <div style={{ marginTop: 6, fontSize: 11.5, color: "var(--text-muted)" }}>
            {timeAgo(approval.created_at)}
            {approval.expires_at && ` · expires ${timeAgo(approval.expires_at).replace(" ago", "")} from now`}
          </div>
          {err && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--status-error-fg)" }}>{err}</div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <Button
            variant="tertiary"
            size="sm"
            onClick={() => decide("decline")}
            disabled={working !== null}
          >
            {working === "decline" ? "…" : "Decline"}
          </Button>
          <Button
            size="sm"
            onClick={() => decide("approve")}
            disabled={working !== null}
            rightIcon={<ArrowRight size={13} strokeWidth={1.8} />}
          >
            {working === "approve" ? "…" : "Approve"}
          </Button>
        </div>
      </div>
    </CardShell>
  );
}

function prettyToolName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function StatusPill({
  tone,
  children,
}: {
  tone: "action" | "accepted" | "neutral";
  children: React.ReactNode;
}) {
  const styles: Record<typeof tone, React.CSSProperties> = {
    action: {
      background: "var(--status-action-bg)",
      color: "var(--status-action-fg)",
      border: "1px solid var(--status-action-bd)",
    },
    accepted: {
      background: "var(--success-soft)",
      color: "var(--success)",
      border: "1px solid color-mix(in srgb, var(--success) 22%, transparent)",
    },
    neutral: {
      background: "var(--surface-raised)",
      color: "var(--ink-muted)",
      border: "1px solid var(--border-default)",
    },
  };
  return (
    <span
      style={{
        ...styles[tone],
        fontSize: 10.5,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 999,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}
