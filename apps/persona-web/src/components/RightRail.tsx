"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";
import { Avatar } from "@/components/ui";

interface AgentCall {
  id: string;
  peer_agent_id: string;
  peer_task_id: string | null;
  status: string;
  last_state: string | null;
  answer_text: string | null;
  last_event: unknown;
  created_at: string;
  origin_ref: { tool?: string; entity_id?: string } | null;
}

const callPeerLabel = (c: AgentCall) => {
  // Never show raw agent/service IDs to end users.
  const origin = c.origin_ref;
  if (origin?.entity_id?.startsWith("zns:svc:")) return "Service call";
  if (origin?.entity_id?.startsWith("zns:")) return "Agent call";
  return "Network call";
};

const friendlyPreview = (text: string | null): string => {
  if (!text) return "Waiting for the agent…";
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return trimmed.slice(0, 80);
  }
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return `Received ${parsed.length} item${parsed.length === 1 ? "" : "s"}`;
    }
    const keys = Object.keys(parsed);
    // Look for a human-readable summary field first.
    const summaryKey = keys.find((k) =>
      ["summary", "reply_text", "result", "answer", "text"].includes(k),
    );
    if (summaryKey) {
      const value = parsed[summaryKey];
      if (typeof value === "string") return value.slice(0, 80);
    }
    return `Received response with ${keys.length} field${keys.length === 1 ? "" : "s"}`;
  } catch {
    return trimmed.slice(0, 80);
  }
};

// A2A task-lifecycle states (submitted → working → completed/failed) the
// peer reports via last_state — friendlier labels than a flat "pending"
// for the whole in-flight window.
const IN_FLIGHT_STATE_LABELS: Record<string, string> = {
  working: "🔄 working",
  submitted: "⏳ queued",
  "input-required": "❓ needs input",
  "auth-required": "🔑 needs auth",
};

// pending → waiting on the peer; received → answer (or terminal) is in.
const callStatusLabel = (c: AgentCall): { text: string; tone: string } => {
  if (c.status === "received") return { text: "✓ done", tone: "done" };
  if (c.status === "failed" || c.status === "expired") return { text: c.status, tone: "warn" };
  const stateLabel = c.last_state ? IN_FLIGHT_STATE_LABELS[c.last_state] : undefined;
  return { text: stateLabel || "⏳ pending", tone: "pending" };
};

export default function RightRail() {
  const { user } = useDashboard();
  const [calls, setCalls] = useState<AgentCall[]>([]);
  const [selected, setSelected] = useState<AgentCall | null>(null);

  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "You";
  const avatarUrl =
    user?.user_metadata?.avatar_url || user?.user_metadata?.picture || null;

  // Agent/service calls our persona made. The row lands "pending" the moment
  // we dispatch and flips to "received" (with an answer) when the peer's push
  // arrives — both via realtime.
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const sb = getSupabase();

    const upsert = (row: AgentCall) =>
      setCalls((prev) => {
        const idx = prev.findIndex((c) => c.id === row.id);
        if (idx === -1) return [row, ...prev].slice(0, 20);
        const next = [...prev];
        next[idx] = { ...next[idx], ...row };
        return next;
      });

    // Authoritative load. We also poll on an interval so the panel works even
    // if realtime isn't enabled for the table — a just-dispatched call shows
    // up within a few seconds either way.
    const fetchCalls = async () => {
      const { data } = await sb
        .from("outbound_callbacks")
        .select("id,peer_agent_id,peer_task_id,status,last_state,answer_text,last_event,created_at,origin_ref")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(20);
      if (!cancelled && data) setCalls(data as AgentCall[]);
    };

    fetchCalls();
    const interval = setInterval(fetchCalls, 8000);

    const channel = sb
      .channel(`rail-agent-calls-${user.id}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "outbound_callbacks", filter: `user_id=eq.${user.id}` },
        (payload) => upsert(payload.new as AgentCall),
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "outbound_callbacks", filter: `user_id=eq.${user.id}` },
        (payload) => {
          const row = payload.new as AgentCall;
          upsert(row);
          // Keep an open modal in sync if its call just resolved.
          setSelected((sel) => (sel && sel.id === row.id ? { ...sel, ...row } : sel));
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      clearInterval(interval);
      sb.removeChannel(channel);
    };
  }, [user]);

  // Close the modal on Escape.
  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  return (
    <aside className="app-rail">
      <div className="rail-head">
        <div>
          <span className="rail-title">Agent calls</span>
          <span className="rail-count">({calls.length})</span>
        </div>
        <Link
          href="/dashboard/settings/you"
          className="icon-btn rail-avatar-btn"
          aria-label={`Edit ${displayName}'s profile`}
          title="Edit profile"
        >
          <Avatar size="sm" src={avatarUrl} name={displayName} />
        </Link>
      </div>

      {calls.length === 0 ? (
        <div className="rail-empty">No agent calls yet.</div>
      ) : (
        calls.map((c) => {
          const status = callStatusLabel(c);
          return (
            <button
              type="button"
              key={c.id}
              className="rail-call"
              onClick={() => setSelected(c)}
            >
              <div className="rail-call-body">
                <div className="rail-card-title">{callPeerLabel(c)}</div>
                <div className="rail-card-sub">
                  {friendlyPreview(c.answer_text)}
                </div>
              </div>
              <span className={`rail-call-status ${status.tone}`}>{status.text}</span>
            </button>
          );
        })
      )}

      {selected && (
        <div className="modal-scrim" onClick={() => setSelected(null)}>
          <div
            className="agent-call-modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="agent-call-modal-header">
              <div className="agent-call-modal-title">{callPeerLabel(selected)}</div>
              <span className={`rail-call-status ${callStatusLabel(selected).tone}`}>
                {callStatusLabel(selected).text}
              </span>
              <button
                type="button"
                className="agent-call-modal-close"
                onClick={() => setSelected(null)}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="agent-call-modal-body">
              {selected.origin_ref?.tool && (
                <div className="agent-call-row">
                  <span className="k">Via</span>
                  <span className="v">{selected.origin_ref.tool}</span>
                </div>
              )}
              <div className="agent-call-row">
                <span className="k">Status</span>
                <span className="v">{callStatusLabel(selected).text}</span>
              </div>
              <div className="agent-call-row">
                <span className="k">Dispatched</span>
                <span className="v">{new Date(selected.created_at).toLocaleString()}</span>
              </div>

              <div className="agent-call-modal-section">
                <div className="rail-call-label">Answer</div>
                {selected.answer_text ? (
                  <pre className="rail-call-pre">{friendlyPreview(selected.answer_text)}</pre>
                ) : (
                  <div className="rail-call-muted">
                    No answer yet — last status: {selected.last_state || "working"}.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
