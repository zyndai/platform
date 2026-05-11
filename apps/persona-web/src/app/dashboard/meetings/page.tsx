"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Calendar, Clock, MapPin } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet } from "@/lib/api";

interface MeetingPayload {
  title?: string;
  start_time?: string;
  end_time?: string;
  location?: string;
  description?: string;
}

interface MeetingTicket {
  id: string;
  status: "proposed" | "countered" | "accepted";
  initiator_user_id: string;
  recipient_user_id: string;
  thread_id?: string;
  payload: MeetingPayload;
}

interface PendingResponse {
  status: string;
  awaiting_me: MeetingTicket[];
  awaiting_them: MeetingTicket[];
}

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

export default function MeetingsPage() {
  const { user } = useDashboard();
  const [data, setData] = useState<PendingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiGet<PendingResponse>(`/api/meetings/pending/${user.id}`);
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Couldn't load meetings.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  if (loading) {
    return (
      <div style={{ padding: "40px 32px" }}>
        <p style={{ color: "var(--text-muted)" }}>Loading meetings…</p>
      </div>
    );
  }

  if (error) {
    return (
      <EmptyState
        illustration={<Calendar />}
        title="Couldn't load meetings."
        body={error}
      />
    );
  }

  const awaitingMe = data?.awaiting_me ?? [];
  const awaitingThem = data?.awaiting_them ?? [];
  const total = awaitingMe.length + awaitingThem.length;

  if (total === 0) {
    return (
      <EmptyState
        illustration={<Calendar />}
        title="No meetings on the books."
        body="Say hi to someone and we'll get something scheduled."
        action={
          <Link href="/dashboard/people">
            <Button variant="secondary">See who&apos;s worth meeting</Button>
          </Link>
        }
      />
    );
  }

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "40px 32px 48px", width: "100%" }}>
      <h1 className="display-m" style={{ margin: "0 0 8px" }}>Meetings</h1>
      <p style={{ margin: "0 0 28px", color: "var(--text-secondary)", fontSize: 15, lineHeight: 1.55 }}>
        Open proposals and counters across your connected agents.
      </p>

      {awaitingMe.length > 0 && (
        <Section title="WAITING ON YOU" count={awaitingMe.length}>
          {awaitingMe.map((m) => (
            <MeetingCard key={m.id} ticket={m} awaitingMe />
          ))}
        </Section>
      )}
      {awaitingThem.length > 0 && (
        <Section title="WAITING ON THEM" count={awaitingThem.length} muted>
          {awaitingThem.map((m) => (
            <MeetingCard key={m.id} ticket={m} awaitingMe={false} />
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  children,
  muted,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div style={{ marginBottom: 28, opacity: muted ? 0.85 : 1 }}>
      <p className="section-label" style={{ marginBottom: 10 }}>
        {title} · {count}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>{children}</div>
    </div>
  );
}

function MeetingCard({ ticket, awaitingMe }: { ticket: MeetingTicket; awaitingMe: boolean }) {
  const { title, start_time, end_time, location } = ticket.payload;
  const statusLabel =
    ticket.status === "proposed"
      ? "Proposed"
      : ticket.status === "countered"
        ? "Countered"
        : "Accepted";
  const href = ticket.thread_id
    ? `/dashboard/messages?thread=${ticket.thread_id}`
    : "/dashboard/messages";

  return (
    <Link
      href={href}
      style={{
        display: "block",
        textDecoration: "none",
        color: "inherit",
        padding: "16px 18px",
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-md)",
        boxShadow: "0 1px 0 rgba(15,23,42,0.02)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--text-primary)" }}>
          {title || "Untitled meeting"}
        </h3>
        <MeetingPill
          kind={awaitingMe ? "action" : ticket.status === "accepted" ? "accepted" : "neutral"}
        >
          {statusLabel}
        </MeetingPill>
      </div>
      <div
        style={{
          display: "flex",
          gap: 18,
          marginTop: 8,
          color: "var(--text-secondary)",
          fontSize: 13,
          flexWrap: "wrap",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <Clock size={13} strokeWidth={1.7} /> {formatMeetingTime(start_time, end_time)}
        </span>
        {location && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <MapPin size={13} strokeWidth={1.7} /> {location}
          </span>
        )}
      </div>
    </Link>
  );
}

function MeetingPill({
  kind,
  children,
}: {
  kind: "action" | "accepted" | "neutral";
  children: React.ReactNode;
}) {
  const styles: Record<"action" | "accepted" | "neutral", React.CSSProperties> = {
    action: {
      background: "rgba(245, 158, 11, 0.14)",
      color: "#b45309",
      border: "1px solid rgba(245, 158, 11, 0.24)",
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
        ...styles[kind],
        fontSize: 11,
        fontWeight: 600,
        padding: "3px 9px",
        borderRadius: 999,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}
