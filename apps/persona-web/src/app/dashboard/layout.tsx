"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import {
  Home,
  Calendar,
  Users,
  FileText,
  Settings,
  LogOut,
  Menu,
  MessageSquare,
  Search,
  PanelLeftClose,
  PanelLeftOpen,
  CheckSquare,
} from "lucide-react";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import { ChatProvider } from "@/contexts/ChatContext";
import TaskToasts from "@/components/TaskToasts";
import { Monogram, Avatar } from "@/components/ui";
import { stepToPath } from "@/lib/onboarding";
import AppTopBar from "@/components/AppTopBar";
import RightRail from "@/components/RightRail";
import ThemeToggle from "@/components/ThemeToggle";

const BOOT_QUOTES: string[] = [
  "Networking, but only the parts you actually like.",
  "Reading the room so you don't have to.",
  "Finding three humans who'd light up your week.",
  "Skipping the small talk, keeping the warmth.",
  "Drafting intros worth replying to.",
  "Listening to your network — back in a sec.",
  "Only the calendars worth filling get filled.",
  "The right person, on a real Tuesday afternoon.",
];

type NavItem = {
  href: string;
  label: string;
  icon: typeof Home;
};

const ARIA_NAV: NavItem[] = [
  { href: "/dashboard/chat",     label: "Home",     icon: Home },
  { href: "/dashboard/messages", label: "Threads",  icon: MessageSquare },
  { href: "/dashboard/meetings", label: "Meetings", icon: Calendar },
  { href: "/dashboard/people",   label: "People",   icon: Users },
];

const YOU_NAV: NavItem[] = [
  { href: "/dashboard/brief",    label: "Your brief", icon: FileText },
  { href: "/dashboard/todos",    label: "Todos",      icon: CheckSquare },
  { href: "/dashboard/settings", label: "Settings",   icon: Settings },
];

function DashboardShell({ children }: { children: React.ReactNode }) {
  const {
    user,
    loading,
    onboardingStep,
    onboardingLoading,
    handleLogout,
  } = useDashboard();
  const pathname = usePathname();
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("zynd:sidebar-collapsed");
      if (saved === "1") setSidebarCollapsed(true);
    } catch {
      /* localStorage unavailable */
    }
  }, []);

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

  const stillBooting =
    loading ||
    onboardingLoading ||
    (onboardingStep !== null && onboardingStep !== "done");

  const [bootQuote] = useState(
    () => BOOT_QUOTES[Math.floor(Math.random() * BOOT_QUOTES.length)],
  );

  if (stillBooting) {
    return (
      <div className="boot-loader" role="status" aria-live="polite">
        <span className="mark">
          <img src="/zynd.png" alt="" />
        </span>
        <p className="quote">&ldquo;{bootQuote}&rdquo;</p>
        <span className="quote-attrib">Zynd Persona</span>
        <span className="pulse-bar" aria-hidden="true" />
      </div>
    );
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
    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => setSidebarOpen(false)}
        className={`nav-item ${isActive ? "active" : ""}`}
      >
        <span className="nav-icon"><Icon /></span>
        <span className="nav-label">{item.label}</span>
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
          <span style={{ fontFamily: "var(--font-fraunces), serif", fontWeight: 500, fontSize: 15 }}>
            Zynd
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
          <span className="brand-left">
            <Monogram size="sm" />
            <span className="brand-text">Zynd</span>
          </span>
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

        <label
          className="sidebar-search"
          aria-label="Search"
          title={sidebarCollapsed ? "Search" : undefined}
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
          {YOU_NAV.map(renderItem)}
        </nav>

        <div style={{ flex: 1 }} />

        <ThemeToggle />

        <div className="user-card">
          <Avatar size="sm" src={avatarUrl} name={displayName} />
          <div className="info">
            <div className="name">{displayName}</div>
            <div className="email">{user?.email}</div>
          </div>
          <button
            onClick={handleLogout}
            className="logout"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut size={14} strokeWidth={1.5} />
          </button>
        </div>
      </aside>

      <main className="app-main">
        <AppTopBar />
        {children}
      </main>

      {showRail && <RightRail />}

      <TaskToasts />
    </div>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardProvider>
      <ChatProvider>
        <DashboardShell>{children}</DashboardShell>
      </ChatProvider>
    </DashboardProvider>
  );
}
