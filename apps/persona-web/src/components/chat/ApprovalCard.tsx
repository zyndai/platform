"use client";

import { useState } from "react";
import { Calendar, Clock } from "lucide-react";
import { Button } from "@/components/ui";

export interface PendingApproval {
  id: string;
  user_id: string;
  thread_id: string | null;
  tool_name: string;
  tool_args: Record<string, unknown>;
  summary: string | null;
  status: "pending" | "approved" | "declined" | "expired";
  created_at: string;
  expires_at: string;
}

interface ApprovalCardProps {
  approval: PendingApproval;
  onDecide: (
    approvalId: string,
    decision: "approve" | "decline",
  ) => Promise<void>;
}

/**
 * Sticky card surfaced at the top of the chat thread when the orchestrator
 * has staged a commitment-class action that needs the user's blessing.
 * The card is its own surface — independent of the conversational stream
 * so it survives reloads and isn't tied to chat history.
 */
export default function ApprovalCard({ approval, onDecide }: ApprovalCardProps) {
  const [working, setWorking] = useState<"approve" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handle = async (decision: "approve" | "decline") => {
    setWorking(decision);
    setError(null);
    try {
      await onDecide(approval.id, decision);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't decide right now.");
      setWorking(null);
    }
  };

  const headline = headlineFor(approval);
  const timeLine = timeLineFor(approval);

  return (
    <div className="approval-card">
      <div className="approval-icon">
        <Calendar size={18} strokeWidth={1.5} />
      </div>
      <div className="approval-body">
        <div className="approval-headline">{headline}</div>
        {timeLine && (
          <div className="approval-meta">
            <Clock size={12} strokeWidth={1.5} />
            <span>{timeLine}</span>
          </div>
        )}
        {approval.summary && (
          <div className="approval-summary body-s">{approval.summary}</div>
        )}
        {error && (
          <p className="body-s" style={{ color: "var(--danger)", marginTop: 6 }}>
            {error}
          </p>
        )}
      </div>
      <div className="approval-actions">
        <Button
          size="sm"
          variant="tertiary"
          disabled={working !== null}
          onClick={() => handle("decline")}
        >
          {working === "decline" ? "…" : "No, decline"}
        </Button>
        <Button
          size="sm"
          disabled={working !== null}
          onClick={() => handle("approve")}
        >
          {working === "approve" ? "…" : "Yes, go ahead"}
        </Button>
      </div>
    </div>
  );
}

function headlineFor(a: PendingApproval): string {
  if (a.tool_name === "propose_meeting") {
    const title = (a.tool_args.title as string) || "a meeting";
    return `I'd like to propose ${title}`;
  }
  return `I'd like to ${a.tool_name.replace(/_/g, " ")}`;
}

function timeLineFor(a: PendingApproval): string | null {
  if (a.tool_name !== "propose_meeting") return null;
  const start = a.tool_args.start_time as string | undefined;
  const end = a.tool_args.end_time as string | undefined;
  if (!start) return null;
  try {
    const s = new Date(start);
    const e = end ? new Date(end) : null;
    const day = s.toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
    const sTime = s.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    const eTime = e ? e.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    return e ? `${day} · ${sTime} – ${eTime}` : `${day} · ${sTime}`;
  } catch {
    return start;
  }
}
