"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet } from "@/lib/api";

const POLL_INTERVAL_MS = 30_000;

interface ApprovalRow {
  id: string;
  status?: string;
}

/**
 * Top-bar bell + badge that shows how many pending approvals the user has.
 * Polls /api/approvals/ every 30s while the tab is visible; pauses when
 * hidden so we don't burn the registry from background tabs. Clicking the
 * button routes to /dashboard/inbox where the approvals render with
 * approve/decline actions.
 *
 * Silently no-ops when the user isn't authenticated yet (e.g. on first
 * mount before DashboardContext resolves) and on errors — this is an
 * ambient indicator, not a critical path.
 */
export default function ApprovalsIndicator() {
  const { user } = useDashboard();
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!user?.id) {
      setCount(0);
      return;
    }
    let cancelled = false;

    const tick = async () => {
      try {
        const data = await apiGet<{ approvals: ApprovalRow[] }>("/api/approvals/");
        if (cancelled) return;
        const fresh = (data.approvals || []).filter(
          (a) => !a.status || a.status === "pending",
        );
        setCount(fresh.length);
      } catch {
        /* keep last known count; transient errors shouldn't drop the badge */
      }
    };

    void tick();
    let interval = window.setInterval(() => void tick(), POLL_INTERVAL_MS);

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void tick();
        if (!interval) interval = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
      } else if (interval) {
        window.clearInterval(interval);
        interval = 0;
      }
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      if (interval) window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [user?.id]);

  const ariaLabel =
    count === 0
      ? "No pending approvals"
      : `${count} pending approval${count === 1 ? "" : "s"}. Open inbox.`;

  return (
    <Link
      href="/dashboard/inbox"
      className="approvals-indicator"
      aria-label={ariaLabel}
      title={ariaLabel}
      data-has-pending={count > 0 ? "true" : "false"}
    >
      <Bell size={16} strokeWidth={1.7} />
      {count > 0 && (
        <span className="approvals-indicator-badge" aria-hidden="true">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
