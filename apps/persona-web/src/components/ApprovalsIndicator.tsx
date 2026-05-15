"use client";

import Link from "next/link";
import { Bell } from "lucide-react";
import { useDashboardActivity } from "@/contexts/DashboardActivityContext";

/**
 * Top-bar bell + badge for anything that needs the user's attention.
 * The dashboard activity provider owns polling + realtime refreshes so
 * this stays in sync with Inbox and Meetings without a page reload.
 */
export default function ApprovalsIndicator() {
  const { counts } = useDashboardActivity();
  const count = counts.inboxAction;

  const ariaLabel =
    count === 0
      ? "No pending items"
      : `${count} item${count === 1 ? "" : "s"} need your attention. Open inbox.`;

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
