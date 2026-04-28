import type { ReactNode } from "react";

interface EmptyStateProps {
  /** Title — typically Aria reframing absence as opportunity. Fraunces. */
  title: string;
  /** Supporting line. Geist body. */
  body?: string;
  /** Optional action button row — pass any ReactNode (Button + Link, etc.). */
  action?: ReactNode;
  /** Optional small illustration above the title. */
  illustration?: ReactNode;
  className?: string;
}

/**
 * S17 empty-state pattern.
 * Always reframe as opportunity, not absence ("Quiet today" beats "No matches").
 * Always include a specific next step. Never an "Oops" or sad-trombone tone.
 */
export function EmptyState({
  title,
  body,
  action,
  illustration,
  className = "",
}: EmptyStateProps) {
  return (
    <div className={`empty-state ${className}`.trim()}>
      {illustration && <div className="illust">{illustration}</div>}
      <h3 className="display-s">{title}</h3>
      {body && <p className="body secondary">{body}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}
