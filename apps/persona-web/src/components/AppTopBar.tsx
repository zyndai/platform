"use client";

import { useCallback, useState } from "react";
import { usePathname } from "next/navigation";
import { Check, Share2 } from "lucide-react";
import { Avatar } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import ApprovalsIndicator from "./ApprovalsIndicator";

const TITLES: Record<string, string> = {
  "/dashboard/inbox":    "Inbox",
  "/dashboard/chat":     "Persona · Home",
  "/dashboard/messages": "Threads",
  "/dashboard/meetings": "Meetings",
  "/dashboard/people":   "People",
  "/dashboard/brief":    "Your brief",
  "/dashboard/todos":    "Todos",
  "/dashboard/settings": "Settings",
};

export default function AppTopBar() {
  const pathname = usePathname();
  const { user } = useDashboard();

  let title = "ZyndAI";
  for (const route of Object.keys(TITLES)) {
    if (pathname === route || pathname.startsWith(route + "/")) {
      title = TITLES[route];
      break;
    }
  }

  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "You";
  const avatarUrl =
    user?.user_metadata?.avatar_url || user?.user_metadata?.picture || null;

  const shareUrl =
    user?.id && typeof window !== "undefined"
      ? `${window.location.origin}/p/${user.id}`
      : null;

  return (
    <div className="topbar-v2">
      <h3>{title}</h3>
      <div className="topbar-actions">
        <ApprovalsIndicator />
        <ShareAgentButton url={shareUrl} />
        <span className="topbar-avatar" aria-label={displayName}>
          <Avatar size="sm" src={avatarUrl} name={displayName} />
        </span>
      </div>
    </div>
  );
}

function ShareAgentButton({ url }: { url: string | null }) {
  const [copied, setCopied] = useState(false);
  const handle = useCallback(async () => {
    if (!url) return;
    try {
      if (typeof navigator !== "undefined" && navigator.share) {
        await navigator.share({ url, title: "My Zynd Persona" });
        return;
      }
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      }
    } catch {
      /* user cancelled or permission denied; no-op */
    }
  }, [url]);

  return (
    <button
      type="button"
      onClick={handle}
      className="icon-btn"
      disabled={!url}
      aria-label={copied ? "Link copied" : "Share my agent"}
      title={copied ? "Link copied" : "Share my agent"}
    >
      {copied ? <Check /> : <Share2 />}
    </button>
  );
}
