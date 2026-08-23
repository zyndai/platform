"use client";

import { usePathname } from "next/navigation";
import { History, MessageSquarePlus } from "lucide-react";
import { useChat } from "@/contexts/ChatContext";
import ThemeToggle from "@/components/ThemeToggle";

const TITLES: Record<string, string> = {
  "/dashboard/inbox":    "Inbox",
  "/dashboard/chat":     "Persona · Home",
  "/dashboard/messages": "Threads",
  "/dashboard/meetings": "Meetings",
  "/dashboard/people":   "People",
  "/dashboard/groups":   "Groups",
  "/dashboard/brief":    "Your brief",
  "/dashboard/todos":    "Todos",
  "/dashboard/settings": "Settings",
};

export default function AppTopBar() {
  const pathname = usePathname();
  const { newChat, toggleHistory } = useChat();

  // Hide entirely on group detail pages — the group header absorbs these controls.
  const isGroupDetail = /^\/dashboard\/groups\/[^/]+/.test(pathname) &&
    pathname !== "/dashboard/groups";
  if (isGroupDetail) return null;

  let title = "ZyndAI";
  for (const route of Object.keys(TITLES)) {
    if (pathname === route || pathname.startsWith(route + "/")) {
      title = TITLES[route];
      break;
    }
  }

  const isChatPage = pathname === "/dashboard/chat" || pathname.startsWith("/dashboard/chat/");

  return (
    <div className="topbar-v2">
      <h3>{title}</h3>
      <div className="topbar-actions">
        {isChatPage && (
          <>
            <button
              type="button"
              className="icon-btn"
              onClick={toggleHistory}
              aria-label="Chat history"
              title="Chat history"
            >
              <History size={16} strokeWidth={1.7} />
            </button>
            <button type="button" className="new-chat-btn" onClick={newChat}>
              <MessageSquarePlus size={16} strokeWidth={1.7} />
              New chat
            </button>
          </>
        )}
        <ThemeToggle />
      </div>
    </div>
  );
}
