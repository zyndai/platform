"use client";

import { usePathname } from "next/navigation";
import { HelpCircle } from "lucide-react";
import { Avatar } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";

const TITLES: Record<string, string> = {
  "/dashboard/chat":     "Persona · Home",
  "/dashboard/messages": "Threads",
  "/dashboard/meetings": "Meetings",
  "/dashboard/people":   "People",
  "/dashboard/brief":    "Your brief",
  "/dashboard/settings": "Settings",
};

export default function AppTopBar() {
  const pathname = usePathname();
  const { user } = useDashboard();

  let title = "Persona";
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

  return (
    <div className="topbar-v2">
      <h3>{title}</h3>
      <div className="topbar-actions">
        <button type="button" className="icon-btn" aria-label="Help">
          <HelpCircle />
        </button>
        <span className="topbar-avatar" aria-label={displayName}>
          <Avatar size="sm" src={avatarUrl} name={displayName} />
        </span>
      </div>
    </div>
  );
}
