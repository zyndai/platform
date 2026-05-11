"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MoreHorizontal } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface RailThread {
  id: string;
  initiator_id: string;
  receiver_id: string;
  initiator_name: string;
  receiver_name: string;
  updated_at: string;
}

interface RailMessage {
  thread_id: string;
  content: string;
  created_at: string;
}

export default function RightRail() {
  const { user } = useDashboard();
  const [threads, setThreads] = useState<RailThread[]>([]);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [agentId, setAgentId] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/persona/${user.id}/status`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data?.agent_id) setAgentId(data.agent_id);
      } catch {
        /* best effort */
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    const sb = getSupabase();
    (async () => {
      let queryStr = `initiator_id.eq.${user.id},receiver_id.eq.${user.id}`;
      if (agentId) {
        queryStr = `${queryStr},initiator_id.eq.${agentId},receiver_id.eq.${agentId}`;
      }
      const { data: threadRows } = await sb
        .from("dm_threads")
        .select("id,initiator_id,receiver_id,initiator_name,receiver_name,updated_at")
        .or(queryStr)
        .order("updated_at", { ascending: false })
        .limit(8);
      if (cancelled || !threadRows) return;
      setThreads(threadRows as RailThread[]);

      const ids = threadRows.map((t) => t.id);
      if (ids.length === 0) return;
      const { data: msgRows } = await sb
        .from("dm_messages")
        .select("thread_id,content,created_at")
        .in("thread_id", ids)
        .order("created_at", { ascending: false });
      if (cancelled || !msgRows) return;
      const seen: Record<string, string> = {};
      for (const m of msgRows as RailMessage[]) {
        if (!seen[m.thread_id]) seen[m.thread_id] = m.content;
      }
      setPreviews(seen);
    })();
    return () => { cancelled = true; };
  }, [user, agentId]);

  const peerOf = (t: RailThread) => {
    if (!agentId && !user) return "Thread";
    if (agentId && t.initiator_id === agentId) return t.receiver_name || "Network agent";
    if (agentId && t.receiver_id === agentId) return t.initiator_name || "Network agent";
    if (user && t.initiator_id === user.id) return t.receiver_name || "Network agent";
    if (user && t.receiver_id === user.id) return t.initiator_name || "Network agent";
    return t.receiver_name || t.initiator_name || "Thread";
  };

  return (
    <aside className="app-rail">
      <div className="rail-head">
        <div>
          <span className="rail-title">Threads</span>
          <span className="rail-count">({threads.length})</span>
        </div>
        <Link href="/dashboard/messages" aria-label="See all threads" className="rail-more">
          <MoreHorizontal />
        </Link>
      </div>

      {threads.length === 0 ? (
        <div className="rail-empty">No threads yet.</div>
      ) : (
        threads.map((t) => {
          const preview = previews[t.id] || "Awaiting first message…";
          return (
            <Link
              key={t.id}
              href={`/dashboard/messages?thread=${t.id}`}
              className="rail-card"
            >
              <div className="rail-card-body">
                <div className="rail-card-title">{peerOf(t)}</div>
                <div className="rail-card-sub">{preview}</div>
              </div>
              <div className="rail-card-mark" />
            </Link>
          );
        })
      )}
    </aside>
  );
}
