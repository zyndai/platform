"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowRight,
  Calendar,
  CalendarCheck,
  Clock,
  MapPin,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import {
  type MeetingTicket,
  useDashboardActivity,
} from "@/contexts/DashboardActivityContext";
import { meetingStatusLabel } from "@/lib/meetingStatus";

function formatMeetingTime(start?: string, end?: string): string {
  if (!start) return "Time TBD";
  try {
    const s = new Date(start);
    const dateStr = s.toLocaleDateString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    const startStr = s.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
    if (!end) return `${dateStr} · ${startStr}`;
    const e = new Date(end);
    const endStr = e.toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
    return `${dateStr} · ${startStr} - ${endStr}`;
  } catch {
    return start;
  }
}

export default function MeetingsPage() {
  const { activity, counts, loading, error, refresh } = useDashboardActivity();
  const awaitingMe = activity.meetingsAwaitingMe;
  const awaitingThem = activity.meetingsAwaitingThem;

  return (
    <div className="meetings-page">
      <section className="meetings-hero">
        <div>
          <span className="meetings-kicker">Meeting desk</span>
          <h1>Open proposals</h1>
          <p>
            {counts.meetingsAction > 0
              ? `${counts.meetingsAction} proposal${counts.meetingsAction === 1 ? "" : "s"} need your reply.`
              : counts.meetingsWaiting > 0
                ? `${counts.meetingsWaiting} proposal${counts.meetingsWaiting === 1 ? " is" : "s are"} waiting on the other side.`
                : "No active meeting proposals right now."}
          </p>
        </div>
        <button type="button" className="meetings-refresh" onClick={() => void refresh()}>
          <RefreshCw size={15} strokeWidth={1.8} />
          Refresh
        </button>
      </section>

      <section className="meetings-summary" aria-label="Meeting summary">
        <div>
          <span>Need reply</span>
          <strong>{counts.meetingsAction}</strong>
        </div>
        <div>
          <span>Waiting</span>
          <strong>{counts.meetingsWaiting}</strong>
        </div>
        <div>
          <span>Total active</span>
          <strong>{counts.meetingsTotal}</strong>
        </div>
      </section>

      {error && (
        <div className="meetings-error">
          Could not load all meetings: {error}
        </div>
      )}

      {loading ? (
        <div className="meetings-skeleton" aria-label="Loading meetings">
          <span />
          <span />
        </div>
      ) : counts.meetingsTotal === 0 ? (
        <section className="meetings-empty">
          <span aria-hidden>
            <Calendar size={24} strokeWidth={1.8} />
          </span>
          <h2>No meetings on the books.</h2>
          <p>When another agent proposes a time, it will appear here and in your Inbox automatically.</p>
          <Link href="/dashboard/people">
            <Button variant="secondary">See who is worth meeting</Button>
          </Link>
        </section>
      ) : (
        <div className="meetings-board">
          <MeetingColumn title="Waiting on you" count={awaitingMe.length}>
            {awaitingMe.map((ticket) => (
              <MeetingCard key={ticket.id} ticket={ticket} awaitingMe />
            ))}
          </MeetingColumn>
          <MeetingColumn title="Waiting on them" count={awaitingThem.length} muted>
            {awaitingThem.map((ticket) => (
              <MeetingCard key={ticket.id} ticket={ticket} awaitingMe={false} />
            ))}
          </MeetingColumn>
        </div>
      )}
    </div>
  );
}

function MeetingColumn({
  title,
  count,
  children,
  muted,
}: {
  title: string;
  count: number;
  children: ReactNode;
  muted?: boolean;
}) {
  return (
    <section className={`meetings-column ${muted ? "is-muted" : ""}`}>
      <div className="meetings-column-head">
        <span>{title}</span>
        <b>{count}</b>
      </div>
      <div className="meetings-column-list">
        {count > 0 ? children : <p>No proposals here.</p>}
      </div>
    </section>
  );
}

function MeetingCard({ ticket, awaitingMe }: { ticket: MeetingTicket; awaitingMe: boolean }) {
  const { user } = useDashboard();
  const { title, start_time, end_time, location, description } = ticket.payload;
  const href = ticket.thread_id
    ? `/dashboard/messages?thread=${ticket.thread_id}`
    : "/dashboard/messages";
  const statusLabel = awaitingMe
    ? "Your reply"
    : meetingStatusLabel({
        status: ticket.status,
        awaitingMe: false,
        iProposed: ticket.initiator_user_id === user?.id,
      });

  return (
    <Link href={href} className="meetings-card">
      <div className="meetings-card-top">
        <span className="meetings-card-icon" aria-hidden>
          <CalendarCheck size={17} strokeWidth={1.8} />
        </span>
        <span className={`meetings-pill ${awaitingMe ? "tone-action" : "tone-neutral"}`}>
          {statusLabel}
        </span>
      </div>
      <h3>{title || "Untitled meeting"}</h3>
      <div className="meetings-card-meta">
        <span>
          <Clock size={13} strokeWidth={1.7} />
          {formatMeetingTime(start_time, end_time)}
        </span>
        {location && (
          <span>
            <MapPin size={13} strokeWidth={1.7} />
            {location}
          </span>
        )}
      </div>
      {description && <p>{description}</p>}
      <span className="meetings-card-open">
        Open thread <ArrowRight size={13} strokeWidth={1.8} />
      </span>
    </Link>
  );
}
