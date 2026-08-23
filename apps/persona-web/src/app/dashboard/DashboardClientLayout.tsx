"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  CalendarDays,
  Users,
  FileText,
  Settings,
  LogOut,
  Menu,
  MessagesSquare,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  ListChecks,
  Home,
  Inbox,
  Share2,
  UsersRound,
  Globe,
  Plug,
  Compass,
} from "lucide-react";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import {
  DashboardActivityProvider,
  useDashboardActivity,
} from "@/contexts/DashboardActivityContext";
import { ChatProvider } from "@/contexts/ChatContext";
import TaskToasts from "@/components/TaskToasts";
import { Monogram, Avatar, BootLoader, type BootStage } from "@/components/ui";
import { stepToPath } from "@/lib/onboarding";
import { startGuidedTour } from "@/lib/tour";
import AppTopBar from "@/components/AppTopBar";
import RightRail from "@/components/RightRail";
import GuidedTour from "@/components/GuidedTour";

type NavTone = "indigo" | "violet" | "sky" | "emerald" | "amber" | "rose" | "slate";

type NavItem = {
  href: string;
  label: string;
  icon: typeof Home;
  tone: NavTone;
  badge?: "inbox" | "meetings";
  tourId?: string;
};

const ARIA_NAV: NavItem[] = [
  { href: "/dashboard/chat",     label: "Home",     icon: LayoutDashboard, tone: "indigo",  tourId: "tour-nav-chat"     },
  { href: "/dashboard/inbox",    label: "Inbox",    icon: Inbox,           tone: "sky",     badge: "inbox",    tourId: "tour-nav-inbox"    },
  { href: "/dashboard/messages", label: "Threads",  icon: MessagesSquare,  tone: "violet",  tourId: "tour-nav-messages" },
  { href: "/dashboard/meetings", label: "Meetings", icon: CalendarDays,    tone: "amber",   badge: "meetings", tourId: "tour-nav-meetings" },
  { href: "/dashboard/people",   label: "People",   icon: Users,           tone: "emerald", tourId: "tour-nav-people"   },
  { href: "/dashboard/groups",   label: "Groups",   icon: UsersRound,      tone: "rose",    tourId: "tour-nav-groups"   },
];

const YOU_NAV: NavItem[] = [
  { href: "/dashboard/brief",    label: "Your brief", icon: FileText,   tone: "amber" },
  { href: "/dashboard/pages",    label: "Pages",      icon: Globe,      tone: "sky"   },
  { href: "/dashboard/connect",  label: "MCP",        icon: Plug,       tone: "violet"},
  { href: "/dashboard/todos",    label: "Todos",      icon: ListChecks, tone: "rose"  },
  { href: "/dashboard/settings", label: "Settings",   icon: Settings,   tone: "slate", tourId: "tour-you-settings" },
];

function DashboardShell({ children }: { children: React.ReactNode }) {
  const {
    user,
    loading,
    onboardingStep,
    onboardingLoading,
    personaLoading,
    knownOnboarded,
    handleLogout,
  } = useDashboard();
  const pathname = usePathname();
  const router = useRouter();
  const { counts } = useDashboardActivity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      const saved = window.localStorage.getItem("zynd:sidebar-collapsed");
      return saved === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(
        "zynd:sidebar-collapsed",
        sidebarCollapsed ? "1" : "0",
      );
    } catch {
      /* localStorage unavailable */
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    if (!loading && !onboardingLoading && onboardingStep && onboardingStep !== "done") {
      router.replace(stepToPath(onboardingStep));
    }
  }, [loading, onboardingLoading, onboardingStep, router]);

  // Returning, already-onboarded users (cached) only wait on the fast local
  // auth check — the shell renders immediately and the persona/calendar fetches
  // (+ the onboarding-redirect effect) reconcile in the background. First-time /
  // un-onboarded users keep the protective full-screen loader until status
  // resolves, so they never flash the dashboard before the onboarding redirect.
  const stillBooting =
    loading ||
    (!knownOnboarded &&
      (onboardingLoading ||
        (onboardingStep !== null && onboardingStep !== "done")));

  if (stillBooting) {
    let stage: BootStage = "signin";
    if (!loading && user) {
      if (personaLoading) stage = "persona";
      else if (onboardingLoading) stage = "accounts";
      else stage = "ready";
    }
    return <BootLoader stage={stage} />;
  }

  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "You";

  const avatarUrl =
    user?.user_metadata?.avatar_url || user?.user_metadata?.picture || null;

  const renderItem = (item: NavItem) => {
    const Icon = item.icon;
    const isActive =
      pathname === item.href || pathname.startsWith(item.href + "/");
    const badgeCount =
      item.badge === "inbox"
        ? counts.inboxAction
        : item.badge === "meetings"
          ? counts.meetingsAction
          : 0;
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => setSidebarOpen(false)}
        className={`nav-item ${isActive ? "active" : ""}`}
        data-tone={item.tone}
        data-tour={item.tourId}
      >
        <span className="nav-icon"><Icon /></span>
        <span className="nav-label">{item.label}</span>
        {badgeCount > 0 && (
          <span className="nav-count" aria-label={`${badgeCount} pending`}>
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </Link>
    );
  };

  const showRail = pathname === "/dashboard/chat" || pathname.startsWith("/dashboard/chat/");

  return (
    <div
      className={`app-shell-v2 ${showRail ? "" : "no-rail"} ${
        sidebarCollapsed ? "sidebar-collapsed" : ""
      }`}
    >
      <div className="mobile-header">
        <button
          className="menu-btn"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open menu"
        >
          <Menu size={20} strokeWidth={1.5} />
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Monogram size="sm" />
          <span style={{ fontFamily: "var(--font-chakra-petch), sans-serif", fontWeight: 500, fontSize: 15 }}>
            ZyndAI
          </span>
        </div>
      </div>

      {sidebarOpen && (
        <div
          className="mobile-overlay open"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside className={`app-sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <Link
            href="/dashboard/chat"
            className="brand-left"
            style={{ textDecoration: "none", color: "inherit", cursor: "pointer" }}
          >
            <Monogram size="sm" />
            <span className="brand-text">ZyndAI</span>
          </Link>
          <button
            type="button"
            className="collapse-btn"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => {
              setSidebarOpen(false);
              setSidebarCollapsed((c) => !c);
            }}
          >
            {sidebarCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </button>
        </div>

        <div className="sidebar-body">
          <label
            className="sidebar-search"
            aria-label="Search"
            title={sidebarCollapsed ? "Search" : undefined}
            data-tour="tour-search"
            onClick={() => {
              if (sidebarCollapsed) setSidebarCollapsed(false);
            }}
          >
            <Search />
            <input
              type="text"
              placeholder="Search"
              aria-label="Search"
            />
            <span className="kbd">⌘K</span>
          </label>

          <div className="nav-group-label">Persona</div>
          <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {ARIA_NAV.map(renderItem)}
          </nav>

          <div className="nav-group-label">You</div>
          <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {YOU_NAV.filter(i => i.label !== "Settings").map(renderItem)}
          </nav>
        </div>

        <div className="sidebar-footer">
          {renderItem(YOU_NAV.find(i => i.label === "Settings")!)}
          <div className="sidebar-footer-row">
            <button
              type="button"
              className="tour-replay-btn"
              onClick={() => startGuidedTour()}
              title="Take the tour"
              aria-label="Replay the guided tour"
            >
              <Compass size={14} strokeWidth={1.5} />
            </button>
          </div>
          <div className="user-card" data-tour="tour-user-card">
          <Link
            href="/dashboard/settings/you"
            className="user-card-link"
            title="Edit your profile"
            aria-label="Edit your profile"
          >
            <Avatar size="sm" src={avatarUrl} name={displayName} />
            <div className="info">
              <div className="name">{displayName}</div>
              <div className="email">{user?.email}</div>
            </div>
          </Link>
          {user?.id && (
            <Link
              href={`/p/${user.id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="logout"
              title="Open my public agent card"
              aria-label="Open my public agent card"
            >
              <Share2 size={14} strokeWidth={1.5} />
            </Link>
          )}
          <button
            onClick={handleLogout}
            className="logout"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut size={14} strokeWidth={1.5} />
          </button>
        </div>
        </div>
      </aside>

      <main className="app-main">
        <AppTopBar />
        {children}
      </main>

      {showRail && <RightRail />}

      <TaskToasts />
      <GuidedTour
        sidebarCollapsed={sidebarCollapsed}
        onExpandSidebar={() => setSidebarCollapsed(false)}
      />
    </div>
  );
}

export default function DashboardClientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardProvider>
      <DashboardActivityProvider>
        <ChatProvider>
          <DashboardShell>{children}</DashboardShell>
        </ChatProvider>
      </DashboardActivityProvider>
    </DashboardProvider>
  );
}
