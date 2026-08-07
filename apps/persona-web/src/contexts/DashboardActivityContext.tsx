"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet } from "@/lib/api";
import {
  listIncomingInvitations,
  type GroupInvitation,
} from "@/lib/group-invitations";
import { getSupabase } from "@/lib/supabase";

export interface MeetingPayload {
  title?: string;
  start_time?: string;
  end_time?: string;
  location?: string;
  description?: string;
}

export interface MeetingTicket {
  id: string;
  status: "proposed" | "countered" | "accepted";
  initiator_user_id?: string;
  recipient_user_id?: string;
  thread_id?: string;
  payload: MeetingPayload;
  created_at?: string;
  updated_at?: string;
}

export interface PendingApproval {
  id: string;
  tool_name: string;
  tool_args?: Record<string, unknown>;
  summary?: string;
  created_at: string;
  expires_at?: string;
  thread_id?: string | null;
  status?: string;
}

export interface Todo {
  id: string;
  title: string;
  source_text?: string | null;
  done: boolean;
  created_at: string;
}

export interface ConnectionRequest {
  id: string;
  initiator_id: string;
  initiator_name: string;
  receiver_id: string;
  receiver_name: string;
  created_at: string;
  status: string;
}

export interface DashboardActivity {
  meetingsAwaitingMe: MeetingTicket[];
  meetingsAwaitingThem: MeetingTicket[];
  approvals: PendingApproval[];
  todos: Todo[];
  connectionRequests: ConnectionRequest[];
  groupInvitations: GroupInvitation[];
}

export interface DashboardActivityCounts {
  approvals: number;
  connectionRequests: number;
  todos: number;
  meetingsAction: number;
  meetingsWaiting: number;
  meetingsTotal: number;
  groupInvitations: number;
  inboxAction: number;
  inboxTotal: number;
}

const EMPTY_ACTIVITY: DashboardActivity = {
  meetingsAwaitingMe: [],
  meetingsAwaitingThem: [],
  approvals: [],
  todos: [],
  connectionRequests: [],
  groupInvitations: [],
};

function getCounts(activity: DashboardActivity): DashboardActivityCounts {
  const approvals = activity.approvals.length;
  const connectionRequests = activity.connectionRequests.length;
  const todos = activity.todos.length;
  const meetingsAction = activity.meetingsAwaitingMe.length;
  const meetingsWaiting = activity.meetingsAwaitingThem.length;
  const groupInvitations = activity.groupInvitations.length;
  const inboxAction =
    approvals + connectionRequests + todos + meetingsAction + groupInvitations;
  return {
    approvals,
    connectionRequests,
    todos,
    meetingsAction,
    meetingsWaiting,
    meetingsTotal: meetingsAction + meetingsWaiting,
    groupInvitations,
    inboxAction,
    inboxTotal: inboxAction + meetingsWaiting,
  };
}

async function loadConnectionRequests(userId: string): Promise<ConnectionRequest[]> {
  let agentId: string | null = null;
  try {
    const status = await apiGet<{ agent_id?: string; deployed?: boolean }>(
      `/api/persona/${userId}/status`,
      { noCache: true },
    );
    if (status.deployed && status.agent_id) agentId = status.agent_id;
  } catch {
    /* Match by user id if the agent status lookup flakes. */
  }

  const sb = getSupabase();
  const ids = [userId, ...(agentId ? [agentId] : [])];
  const orClause = ids.map((id) => `receiver_id.eq.${id}`).join(",");
  const { data, error } = await sb
    .from("dm_threads")
    .select("id, initiator_id, initiator_name, receiver_id, receiver_name, created_at, status")
    .eq("status", "pending")
    .or(orClause)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data || []) as ConnectionRequest[];
}

/**
 * Fetches all five activity categories in parallel. Each category falls
 * back to its `previous` value (not `[]`) when its own fetch fails — a
 * transient blip on, say, /api/todos/ shouldn't blank out approvals or
 * connection requests too. Before this, any single failed call in the
 * batch (which got a lot more likely right around "Accept", when two
 * refreshes could fire back-to-back — see the dm_threads listener below)
 * made the whole inbox look empty.
 */
async function loadDashboardActivity(
  userId: string,
  previous: DashboardActivity,
): Promise<DashboardActivity> {
  const [meetings, approvals, todos, requests, invitations] = await Promise.allSettled([
    apiGet<{ awaiting_me: MeetingTicket[]; awaiting_them: MeetingTicket[] }>(
      `/api/meetings/pending/${userId}`,
      { noCache: true },
    ),
    apiGet<{ approvals: PendingApproval[] }>("/api/approvals/", { noCache: true }),
    apiGet<{ todos: Todo[] }>("/api/todos/", { noCache: true }),
    loadConnectionRequests(userId),
    listIncomingInvitations(),
  ]);

  return {
    meetingsAwaitingMe:
      meetings.status === "fulfilled" ? meetings.value.awaiting_me ?? [] : previous.meetingsAwaitingMe,
    meetingsAwaitingThem:
      meetings.status === "fulfilled" ? meetings.value.awaiting_them ?? [] : previous.meetingsAwaitingThem,
    approvals:
      approvals.status === "fulfilled"
        ? (approvals.value.approvals ?? []).filter(
            (a) => !a.status || a.status === "pending",
          )
        : previous.approvals,
    todos:
      todos.status === "fulfilled"
        ? (todos.value.todos ?? []).filter((t) => !t.done)
        : previous.todos,
    connectionRequests: requests.status === "fulfilled" ? requests.value : previous.connectionRequests,
    groupInvitations:
      invitations.status === "fulfilled" ? invitations.value.invitations || [] : previous.groupInvitations,
  };
}

interface DashboardActivityContextValue {
  activity: DashboardActivity;
  counts: DashboardActivityCounts;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const DashboardActivityContext =
  createContext<DashboardActivityContextValue | null>(null);

const POLL_MS = 20_000;
const REALTIME_REFRESH_DELAY_MS = 220;

export function DashboardActivityProvider({ children }: { children: ReactNode }) {
  const { user } = useDashboard();
  const [activity, setActivity] = useState<DashboardActivity>(EMPTY_ACTIVITY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshTimer = useRef<number | null>(null);
  const activeRequest = useRef(0);
  // Mirrors `activity` without being a `refresh` dependency — reading the
  // latest known-good value here (for loadDashboardActivity's per-category
  // fallback) must not make `refresh`'s identity change on every fetch,
  // which would retrigger the mount effect that calls it.
  const activityRef = useRef<DashboardActivity>(EMPTY_ACTIVITY);

  const refresh = useCallback(async () => {
    const userId = user?.id;
    const requestId = activeRequest.current + 1;
    activeRequest.current = requestId;
    if (!userId) {
      activityRef.current = EMPTY_ACTIVITY;
      setActivity(EMPTY_ACTIVITY);
      setLoading(false);
      setError(null);
      return;
    }

    try {
      const next = await loadDashboardActivity(userId, activityRef.current);
      if (activeRequest.current !== requestId) return;
      activityRef.current = next;
      setActivity(next);
      setError(null);
    } catch (e) {
      if (activeRequest.current !== requestId) return;
      setError(e instanceof Error ? e.message : "Couldn't load dashboard activity.");
    } finally {
      if (activeRequest.current === requestId) setLoading(false);
    }
  }, [user?.id]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      void refresh();
    }, REALTIME_REFRESH_DELAY_MS);
  }, [refresh]);

  useEffect(() => {
    setLoading(true);
    void refresh();
    return () => {
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
      refreshTimer.current = null;
    };
  }, [refresh]);

  useEffect(() => {
    if (!user?.id) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, POLL_MS);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(interval);
    };
  }, [refresh, user?.id]);

  // Resolved once per user so the dm_threads listener below can tell
  // whether a changed row actually involves this user (threads are keyed
  // by agent_id, not the Supabase user id).
  const myAgentId = useRef<string | null>(null);
  useEffect(() => {
    if (!user?.id) return;
    myAgentId.current = null;
    let cancelled = false;
    apiGet<{ agent_id?: string }>(`/api/persona/${user.id}/status`, { noCache: true })
      .then((data) => {
        if (!cancelled && typeof data?.agent_id === "string") myAgentId.current = data.agent_id;
      })
      .catch(() => {
        /* best-effort — the dm_threads listener just won't scope by agent_id until this resolves */
      });
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  useEffect(() => {
    if (!user?.id) return;
    const sb = getSupabase();
    const channel = sb
      .channel(`dashboard-activity-${user.id}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "pending_approvals",
          filter: `user_id=eq.${user.id}`,
        },
        scheduleRefresh,
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "agent_tasks" },
        (payload) => {
          const row = (payload.new || payload.old || {}) as {
            initiator_user_id?: string | null;
            recipient_user_id?: string | null;
          };
          if (row.initiator_user_id === user.id || row.recipient_user_id === user.id) {
            scheduleRefresh();
          }
        },
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "dm_threads" },
        (payload) => {
          // Unlike the agent_tasks listener above, this had no relevance
          // check at all — it refetched this user's whole inbox (5
          // endpoints) on every dm_threads change from every user in the
          // system. Also: accepting a connection request updates this row
          // AND the Inbox page's own handler awaits refresh() directly, so
          // an unguarded listener double-fires the same burst right when
          // the user clicks Accept.
          const row = (payload.new || payload.old || {}) as {
            initiator_id?: string | null;
            receiver_id?: string | null;
          };
          const mine =
            row.initiator_id === user.id ||
            row.receiver_id === user.id ||
            (myAgentId.current !== null &&
              (row.initiator_id === myAgentId.current || row.receiver_id === myAgentId.current));
          if (mine) scheduleRefresh();
        },
      )
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "persona_group_invitations",
          filter: `invitee_user_id=eq.${user.id}`,
        },
        scheduleRefresh,
      )
      .subscribe();

    return () => {
      sb.removeChannel(channel);
    };
  }, [scheduleRefresh, user?.id]);

  const counts = useMemo(() => getCounts(activity), [activity]);
  const value = useMemo(
    () => ({ activity, counts, loading, error, refresh }),
    [activity, counts, error, loading, refresh],
  );

  return (
    <DashboardActivityContext.Provider value={value}>
      {children}
    </DashboardActivityContext.Provider>
  );
}

export function useDashboardActivity() {
  const ctx = useContext(DashboardActivityContext);
  if (!ctx) {
    throw new Error("useDashboardActivity must be used inside DashboardActivityProvider");
  }
  return ctx;
}
