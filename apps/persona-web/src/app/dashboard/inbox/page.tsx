"use client";

import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  CalendarCheck,
  CheckCircle2,
  CheckSquare,
  Clock,
  Inbox as InboxIcon,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import {
  type ConnectionRequest,
  type MeetingTicket,
  type PendingApproval,
  type Todo,
  useDashboardActivity,
} from "@/contexts/DashboardActivityContext";
import { apiPost } from "@/lib/api";
import {
  respondToGroupInvitation,
  type GroupInvitation,
} from "@/lib/group-invitations";
import { getSupabase } from "@/lib/supabase";
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

function relativeTime(iso?: string): string {
  if (!iso) return "";
  try {
    const diffMs = new Date(iso).getTime() - Date.now();
    const absSec = Math.max(0, Math.round(Math.abs(diffMs) / 1000));
    const suffix = diffMs >= 0 ? "from now" : "ago";
    if (absSec < 60) return diffMs >= 0 ? "soon" : "just now";
    const min = Math.round(absSec / 60);
    if (min < 60) return `${min} min ${suffix}`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr}h ${suffix}`;
    const day = Math.round(hr / 24);
    return `${day}d ${suffix}`;
  } catch {
    return "";
  }
}

function stringArg(args: Record<string, unknown> | undefined, key: string): string | undefined {
  const value = args?.[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

export default function InboxPage() {
  const { user } = useDashboard();
  const { activity, counts, loading, error, refresh } = useDashboardActivity();
  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }, [refresh]);

  const handleConnectionAction = useCallback(
    async (req: ConnectionRequest, action: "accept" | "decline") => {
      if (action === "accept") {
        const sb = getSupabase();
        const { error: updateError } = await sb
          .from("dm_threads")
          .update({ status: "accepted" })
          .eq("id", req.id);
        if (updateError) throw updateError;
      } else {
        const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const res = await fetch(`${API}/api/persona/threads/${req.id}/status`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "decline", user_id: user?.id }),
        });
        if (!res.ok) throw new Error(await res.text());
      }
      await refresh();
    },
    [refresh, user?.id],
  );

  const subtitle = useMemo(() => {
    if (loading) return "Checking the queue your Persona is building for you.";
    if (counts.inboxAction === 0 && counts.meetingsWaiting > 0) {
      return `${counts.meetingsWaiting} item${counts.meetingsWaiting === 1 ? " is" : "s are"} waiting on someone else.`;
    }
    if (counts.inboxAction === 0) return "Nothing needs your input right now.";
    return `${counts.inboxAction} item${counts.inboxAction === 1 ? " needs" : "s need"} your attention.`;
  }, [counts.inboxAction, counts.meetingsWaiting, loading]);

  return (
    <div className="inbox-page">
      <section className="inbox-hero">
        <div>
          <span className="inbox-kicker">Live queue</span>
          <h1>Needs your attention</h1>
          <p>{subtitle}</p>
        </div>
        <button
          type="button"
          className="inbox-refresh"
          onClick={() => void handleRefresh()}
          disabled={refreshing}
        >
          <RefreshCw className={refreshing ? "is-spinning" : ""} size={15} strokeWidth={1.8} />
          Refresh
        </button>
      </section>

      <section className="inbox-stats" aria-label="Inbox summary">
        <StatCard
          icon={<ShieldCheck size={16} strokeWidth={1.8} />}
          label="Approvals"
          value={counts.approvals}
          tone="blue"
        />
        <StatCard
          icon={<CalendarCheck size={16} strokeWidth={1.8} />}
          label="Meetings"
          value={counts.meetingsAction}
          tone="amber"
          sub={`${counts.meetingsWaiting} waiting`}
        />
        <StatCard
          icon={<UserPlus size={16} strokeWidth={1.8} />}
          label="Requests"
          value={counts.connectionRequests}
          tone="green"
        />
        <StatCard
          icon={<CheckSquare size={16} strokeWidth={1.8} />}
          label="Todos"
          value={counts.todos}
          tone="rose"
        />
      </section>

      {error && <ErrorBanner message={error} onRetry={handleRefresh} />}

      {loading ? (
        <InboxSkeleton />
      ) : counts.inboxTotal === 0 ? (
        <EmptyInbox userId={user?.id} />
      ) : (
        <div className="inbox-workspace">
          <main className="inbox-list">
            {activity.connectionRequests.length > 0 && (
              <Section
                icon={<UserPlus size={15} strokeWidth={1.8} />}
                title="Connection requests"
                count={activity.connectionRequests.length}
              >
                {activity.connectionRequests.map((request) => (
                  <ConnectionRequestRow
                    key={request.id}
                    request={request}
                    onAction={(action) => handleConnectionAction(request, action)}
                  />
                ))}
              </Section>
            )}

            {activity.groupInvitations.length > 0 && (
              <Section
                icon={<Users size={15} strokeWidth={1.8} />}
                title="Group invitations"
                count={activity.groupInvitations.length}
              >
                {activity.groupInvitations.map((invite) => (
                  <GroupInviteCard
                    key={invite.id}
                    invitation={invite}
                    onResolved={refresh}
                  />
                ))}
              </Section>
            )}

            {activity.approvals.length > 0 && (
              <Section
                icon={<ShieldCheck size={15} strokeWidth={1.8} />}
                title="Decisions needed"
                count={activity.approvals.length}
              >
                {activity.approvals.map((approval) => (
                  <ApprovalCard key={approval.id} approval={approval} onResolved={refresh} />
                ))}
              </Section>
            )}

            {activity.meetingsAwaitingMe.length > 0 && (
              <Section
                icon={<CalendarCheck size={15} strokeWidth={1.8} />}
                title="Meeting requests"
                count={activity.meetingsAwaitingMe.length}
              >
                {activity.meetingsAwaitingMe.map((ticket) => (
                  <MeetingRow key={ticket.id} ticket={ticket} awaitingMe />
                ))}
              </Section>
            )}

            {activity.todos.length > 0 && (
              <Section
                icon={<CheckSquare size={15} strokeWidth={1.8} />}
                title="Open todos"
                count={activity.todos.length}
                rightSlot={<Link href="/dashboard/todos">See all</Link>}
              >
                {activity.todos.slice(0, 5).map((todo) => (
                  <TodoRow key={todo.id} todo={todo} />
                ))}
              </Section>
            )}

            {activity.meetingsAwaitingThem.length > 0 && (
              <Section
                icon={<Clock size={15} strokeWidth={1.8} />}
                title="Waiting on others"
                count={activity.meetingsAwaitingThem.length}
                muted
              >
                {activity.meetingsAwaitingThem.map((ticket) => (
                  <MeetingRow key={ticket.id} ticket={ticket} awaitingMe={false} />
                ))}
              </Section>
            )}
          </main>

          <aside className="inbox-side">
            <div className="inbox-side-card">
              <span className="inbox-live-dot" aria-hidden />
              <div>
                <strong>Live updates are on</strong>
                <p>
                  New approvals, scheduled requests, and meeting changes appear here
                  automatically while you work.
                </p>
              </div>
            </div>
            <div className="inbox-side-card">
              <CheckCircle2 size={17} strokeWidth={1.8} />
              <div>
                <strong>Best next move</strong>
                <p>
                  Approve or decline anything in Decisions needed first; meeting
                  tickets move to Meetings after they become formal proposals.
                </p>
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
  sub,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  tone: "blue" | "amber" | "green" | "rose";
  sub?: string;
}) {
  return (
    <div className="inbox-stat" data-tone={tone}>
      <span className="inbox-stat-icon">{icon}</span>
      <span className="inbox-stat-value">{value}</span>
      <span className="inbox-stat-label">{label}</span>
      {sub && <span className="inbox-stat-sub">{sub}</span>}
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
  icon: ReactNode;
  children: ReactNode;
  muted?: boolean;
  rightSlot?: ReactNode;
}) {
  return (
    <section className={`inbox-section ${muted ? "is-muted" : ""}`}>
      <div className="inbox-section-head">
        <div>
          {icon}
          <span>{title}</span>
          <b>{count}</b>
        </div>
        {rightSlot && <span className="inbox-section-action">{rightSlot}</span>}
      </div>
      <div className="inbox-section-list">{children}</div>
    </section>
  );
}

function CardShell({
  href,
  children,
  className = "",
}: {
  href?: string;
  children: ReactNode;
  className?: string;
}) {
  const cls = `inbox-card ${className}`.trim();
  return href ? (
    <Link href={href} className={cls}>
      {children}
    </Link>
  ) : (
    <article className={cls}>{children}</article>
  );
}

function ConnectionRequestRow({
  request,
  onAction,
}: {
  request: ConnectionRequest;
  onAction: (action: "accept" | "decline") => Promise<void>;
}) {
  const [working, setWorking] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fromName = request.initiator_name || "Someone on the network";

  const act = async (action: "accept" | "decline") => {
    setWorking(action);
    setError(null);
    try {
      await onAction(action);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not ${action} this request.`);
      setWorking(null);
    }
  };

  return (
    <CardShell className="inbox-card-action">
      <span className="inbox-card-icon tone-green" aria-hidden>
        <UserPlus size={17} strokeWidth={1.8} />
      </span>
      <div className="inbox-card-body">
        <div className="inbox-card-title-row">
          <h3>{fromName}</h3>
          <Pill tone="neutral">Connection</Pill>
        </div>
        <p>Wants to start an agent-to-agent thread with you.</p>
        <div className="inbox-card-meta">
          <span>{relativeTime(request.created_at)}</span>
          <Link href={`/dashboard/messages?thread=${request.id}`}>
            Open thread <ArrowRight size={12} strokeWidth={1.8} />
          </Link>
        </div>
        {error && <div className="inbox-inline-error">{error}</div>}
      </div>
      <div className="inbox-card-actions">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void act("decline")}
          disabled={working !== null}
        >
          {working === "decline" ? "..." : "Decline"}
        </Button>
        <Button
          size="sm"
          onClick={() => void act("accept")}
          disabled={working !== null}
        >
          {working === "accept" ? "..." : "Accept"}
        </Button>
      </div>
    </CardShell>
  );
}

function approvalDetails(approval: PendingApproval) {
  if (approval.tool_name === "propose_meeting") {
    const title = stringArg(approval.tool_args, "title") || "Untitled meeting";
    const start = stringArg(approval.tool_args, "start_time");
    const end = stringArg(approval.tool_args, "end_time");
    const location = stringArg(approval.tool_args, "location");
    return {
      label: "Meeting proposal",
      title,
      body: formatMeetingTime(start, end),
      meta: location ? `Location: ${location}` : "Your persona will send this proposal if you approve.",
      icon: <CalendarCheck size={17} strokeWidth={1.8} />,
    };
  }

  if (approval.tool_name === "propose_group_meeting") {
    const title = stringArg(approval.tool_args, "title") || "Untitled meeting";
    const start = stringArg(approval.tool_args, "start_time");
    const end = stringArg(approval.tool_args, "end_time");
    const location = stringArg(approval.tool_args, "location");
    const metaParts: string[] = [];
    if (location) metaParts.push(location);
    metaParts.push("Approving creates the event on your calendar and invites every other group member.");
    return {
      label: "Group meeting",
      title,
      body: formatMeetingTime(start, end),
      meta: metaParts.join(" · "),
      icon: <CalendarCheck size={17} strokeWidth={1.8} />,
    };
  }

  if (approval.tool_name === "create_calendar_event") {
    const title = stringArg(approval.tool_args, "summary") || stringArg(approval.tool_args, "title") || "Calendar event";
    const start = stringArg(approval.tool_args, "start_time") || stringArg(approval.tool_args, "start");
    const end = stringArg(approval.tool_args, "end_time") || stringArg(approval.tool_args, "end");
    return {
      label: "Calendar write",
      title,
      body: formatMeetingTime(start, end),
      meta: "Approving will add this event to your calendar.",
      icon: <CalendarCheck size={17} strokeWidth={1.8} />,
    };
  }

  return {
    label: humanizeToolName(approval.tool_name),
    title: approval.summary || `Approve ${humanizeToolName(approval.tool_name)}?`,
    body: "This action needs your confirmation before your persona runs it.",
    meta: "",
    icon: <ShieldCheck size={17} strokeWidth={1.8} />,
  };
}

function humanizeToolName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function ApprovalCard({
  approval,
  onResolved,
}: {
  approval: PendingApproval;
  onResolved: () => void | Promise<void>;
}) {
  const [working, setWorking] = useState<"approve" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const details = approvalDetails(approval);

  const decide = async (decision: "approve" | "decline") => {
    setWorking(decision);
    setError(null);
    try {
      await apiPost(`/api/approvals/${approval.id}/decide`, { decision });
      await onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      setWorking(null);
    }
  };

  return (
    <CardShell className="inbox-card-action">
      <span className="inbox-card-icon tone-blue" aria-hidden>
        {details.icon}
      </span>
      <div className="inbox-card-body">
        <div className="inbox-card-title-row">
          <h3>{details.title}</h3>
          <Pill tone="action">{details.label}</Pill>
        </div>
        <p>{details.body}</p>
        <div className="inbox-card-meta">
          <span>{relativeTime(approval.created_at)}</span>
          {approval.expires_at && <span>Expires {relativeTime(approval.expires_at)}</span>}
          {details.meta && <span>{details.meta}</span>}
        </div>
        {error && <div className="inbox-inline-error">{error}</div>}
      </div>
      <div className="inbox-card-actions">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void decide("decline")}
          disabled={working !== null}
        >
          {working === "decline" ? "..." : "Decline"}
        </Button>
        <Button
          size="sm"
          onClick={() => void decide("approve")}
          disabled={working !== null}
          rightIcon={<ArrowRight size={13} strokeWidth={1.8} />}
        >
          {working === "approve" ? "..." : "Approve"}
        </Button>
      </div>
    </CardShell>
  );
}

function GroupInviteCard({
  invitation,
  onResolved,
}: {
  invitation: GroupInvitation;
  onResolved: () => void | Promise<void>;
}) {
  const [working, setWorking] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: "accept" | "decline") => {
    setWorking(decision);
    setError(null);
    try {
      await respondToGroupInvitation(invitation.id, decision);
      await onResolved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update the invitation.");
      setWorking(null);
    }
  };

  const groupName = invitation.group?.name || "a group";
  const inviterName = invitation.inviter_name || "Someone";
  const memberCountSuffix =
    typeof invitation.group?.member_count === "number"
      ? `${invitation.group.member_count} member${
          invitation.group.member_count === 1 ? "" : "s"
        }`
      : null;

  return (
    <CardShell className="inbox-card-action">
      <span className="inbox-card-icon tone-blue" aria-hidden>
        <Users size={17} strokeWidth={1.8} />
      </span>
      <div className="inbox-card-body">
        <div className="inbox-card-title-row">
          <h3>{groupName}</h3>
          <Pill tone="action">
            {invitation.invitee_role === "admin" ? "Admin invite" : "Group invite"}
          </Pill>
        </div>
        <p>
          <strong>{inviterName}</strong> invited you to join <strong>{groupName}</strong>.
          {invitation.message ? ` "${invitation.message}"` : ""}
        </p>
        <div className="inbox-card-meta">
          <span>{relativeTime(invitation.created_at)}</span>
          {invitation.expires_at && (
            <span>Expires {relativeTime(invitation.expires_at)}</span>
          )}
          {memberCountSuffix && <span>{memberCountSuffix}</span>}
        </div>
        {error && <div className="inbox-inline-error">{error}</div>}
      </div>
      <div className="inbox-card-actions">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void decide("decline")}
          disabled={working !== null}
        >
          {working === "decline" ? "..." : "Decline"}
        </Button>
        <Button
          size="sm"
          onClick={() => void decide("accept")}
          disabled={working !== null}
          rightIcon={<ArrowRight size={13} strokeWidth={1.8} />}
        >
          {working === "accept" ? "..." : "Accept"}
        </Button>
      </div>
    </CardShell>
  );
}

function MeetingRow({ ticket, awaitingMe }: { ticket: MeetingTicket; awaitingMe: boolean }) {
  const { user } = useDashboard();
  const { title, start_time, end_time, location } = ticket.payload;
  const href = ticket.thread_id
    ? `/dashboard/messages?thread=${ticket.thread_id}`
    : "/dashboard/meetings";
  return (
    <CardShell href={href}>
      <span className="inbox-card-icon tone-amber" aria-hidden>
        <CalendarCheck size={17} strokeWidth={1.8} />
      </span>
      <div className="inbox-card-body">
        <div className="inbox-card-title-row">
          <h3>{title || "Untitled meeting"}</h3>
          <Pill tone={awaitingMe ? "action" : ticket.status === "accepted" ? "accepted" : "neutral"}>
            {awaitingMe
              ? "Your reply"
              : meetingStatusLabel({
                  status: ticket.status,
                  awaitingMe: false,
                  iProposed: ticket.initiator_user_id === user?.id,
                })}
          </Pill>
        </div>
        <p>{formatMeetingTime(start_time, end_time)}</p>
        <div className="inbox-card-meta">
          {location && <span>{location}</span>}
          <span>Open in Threads</span>
        </div>
      </div>
      <ArrowRight className="inbox-card-arrow" size={16} strokeWidth={1.8} />
    </CardShell>
  );
}

function TodoRow({ todo }: { todo: Todo }) {
  return (
    <CardShell href="/dashboard/todos">
      <span className="inbox-card-icon tone-rose" aria-hidden>
        <CheckSquare size={17} strokeWidth={1.8} />
      </span>
      <div className="inbox-card-body">
        <div className="inbox-card-title-row">
          <h3>{todo.title}</h3>
          <Pill tone="neutral">Todo</Pill>
        </div>
        {todo.source_text && <p>{todo.source_text}</p>}
        <div className="inbox-card-meta">
          <span>{relativeTime(todo.created_at)}</span>
        </div>
      </div>
      <ArrowRight className="inbox-card-arrow" size={16} strokeWidth={1.8} />
    </CardShell>
  );
}

function Pill({
  tone,
  children,
}: {
  tone: "action" | "accepted" | "neutral";
  children: ReactNode;
}) {
  return (
    <span className={`inbox-pill tone-${tone}`}>
      {children}
    </span>
  );
}

function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => Promise<void>;
}) {
  return (
    <div className="inbox-error">
      <AlertCircle size={16} strokeWidth={1.8} />
      <span>Could not load part of your inbox: {message}</span>
      <button type="button" onClick={() => void onRetry()}>
        Retry
      </button>
    </div>
  );
}

function EmptyInbox({ userId }: { userId?: string }) {
  return (
    <section className="inbox-empty">
      <span className="inbox-empty-icon" aria-hidden>
        <InboxIcon size={24} strokeWidth={1.8} />
      </span>
      <h2>Nothing is waiting on you.</h2>
      <p>
        New approvals, meeting requests, connection requests, and open todos will
        appear here automatically.
      </p>
      <div className="inbox-empty-actions">
        {userId && (
          <Link href={`/p/${userId}`} target="_blank" rel="noopener noreferrer">
            <Button>Open public card</Button>
          </Link>
        )}
        <Link href="/dashboard/people">
          <Button variant="secondary">Find people</Button>
        </Link>
      </div>
    </section>
  );
}

function InboxSkeleton() {
  return (
    <div className="inbox-skeleton" aria-label="Loading inbox">
      <span />
      <span />
      <span />
    </div>
  );
}
