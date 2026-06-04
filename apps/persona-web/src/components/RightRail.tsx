"use client";

import { useEffect, useState } from "react";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";

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
  const id = c.peer_agent_id || "";
  const short = id.includes(":") ? id.split(":").pop()!.slice(0, 10) : id.slice(0, 10);
  return short || "agent";
};

// pending → waiting on the peer; received → answer (or terminal) is in.
const callStatusLabel = (c: AgentCall): { text: string; tone: string } => {
  if (c.status === "received") return { text: "✓ done", tone: "done" };
  if (c.status === "failed" || c.status === "expired") return { text: c.status, tone: "warn" };
  return { text: "⏳ pending", tone: "pending" };
};

export default function RightRail() {
  const { user } = useDashboard();
  const [calls, setCalls] = useState<AgentCall[]>([]);
  const [selected, setSelected] = useState<AgentCall | null>(null);

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
                <div className="rail-card-title">Agent · {callPeerLabel(c)}</div>
                <div className="rail-card-sub">
                  {c.answer_text
                    ? c.answer_text.slice(0, 80)
                    : c.last_state
                    ? `Last update: ${c.last_state}`
                    : "Waiting for the agent…"}
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
              <div className="agent-call-modal-title">Agent · {callPeerLabel(selected)}</div>
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
              <div className="agent-call-row">
                <span className="k">Task ID</span>
                <span className="v">{selected.peer_task_id || "—"}</span>
              </div>
              <div className="agent-call-row">
                <span className="k">Peer agent</span>
                <span className="v">{selected.peer_agent_id}</span>
              </div>
              {selected.origin_ref?.tool && (
                <div className="agent-call-row">
                  <span className="k">Via</span>
                  <span className="v">{selected.origin_ref.tool}</span>
                </div>
              )}
              <div className="agent-call-row">
                <span className="k">Status</span>
                <span className="v">{selected.status}</span>
              </div>
              <div className="agent-call-row">
                <span className="k">Last state</span>
                <span className="v">{selected.last_state || "—"}</span>
              </div>
              <div className="agent-call-row">
                <span className="k">Dispatched</span>
                <span className="v">{new Date(selected.created_at).toLocaleString()}</span>
              </div>

              <div className="agent-call-modal-section">
                <div className="rail-call-label">Answer</div>
                {selected.answer_text ? (
                  <pre className="rail-call-pre">{selected.answer_text}</pre>
                ) : (
                  <div className="rail-call-muted">
                    No answer yet — last status: {selected.last_state || "working"}.
                  </div>
                )}
              </div>

              {selected.last_event != null && (
                <div className="agent-call-modal-section">
                  <div className="rail-call-label">Last webhook</div>
                  <pre className="rail-call-pre">
                    {JSON.stringify(selected.last_event, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
