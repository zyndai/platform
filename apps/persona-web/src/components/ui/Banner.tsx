import type { ReactNode } from "react";
import { Info, CheckCircle, AlertTriangle, X } from "lucide-react";

type Tone = "info" | "success" | "warning" | "danger";

interface BannerProps {
  tone?: Tone;
  /** Either a string or any node — the message shown in the banner. */
  children: ReactNode;
  /** Optional action — typically a `<button className="text-link">Try now</button>`. */
  action?: ReactNode;
  /** When provided, renders a × dismiss button on the right. */
  onDismiss?: () => void;
}

const TONE_ICON: Record<Tone, typeof Info> = {
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
  danger: AlertTriangle,
};

/**
 * Inline notice strip. Used for non-fatal status updates: OAuth callback
 * results, save confirmations, recoverable errors. Per S18 brief, errors
 * are first-person and offer a next step — never expose codes/stack traces.
 */
export function Banner({
  tone = "info",
  children,
  action,
  onDismiss,
}: BannerProps) {
  const Icon = TONE_ICON[tone];
  return (
    <div className={`banner banner-${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <Icon size={16} strokeWidth={1.5} className="banner-icon" />
      <span className="banner-msg">{children}</span>
      {action && <span className="banner-action">{action}</span>}
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="banner-dismiss"
          aria-label="Dismiss"
        >
          <X size={14} strokeWidth={1.5} />
        </button>
      )}
    </div>
  );
}
