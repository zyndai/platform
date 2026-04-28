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
} from "lucide-react";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import TaskToasts from "@/components/TaskToasts";
import { Monogram, Avatar, ThinkingDot } from "@/components/ui";
import { stepToPath } from "@/lib/onboarding";

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

  // If the user hasn't finished onboarding, kick them to the right screen.
  useEffect(() => {
    if (!loading && !onboardingLoading && onboardingStep && onboardingStep !== "done") {
      router.replace(stepToPath(onboardingStep));
    }
  }, [loading, onboardingLoading, onboardingStep, router]);

  const stillBooting =
    loading ||
    onboardingLoading ||
    (onboardingStep !== null && onboardingStep !== "done");

  if (stillBooting) {
    return (
      <div className="boot-loader">
        <Monogram size="md" />
        <div className="line">
          <ThinkingDot />
          <span>Just a sec…</span>
        </div>
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
        <Icon />
        <span>{item.label}</span>
      </Link>
    );
  };

  return (
    <div className="app-shell no-rail">
      {/* Mobile top header */}
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

      {/* Sidebar */}
      <aside className={`app-sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand">
          <Monogram size="sm" />
          <span className="brand-text">Zynd</span>
        </div>

        <div className="nav-group-label">Aria</div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {ARIA_NAV.map(renderItem)}
        </nav>

        <div className="nav-group-label">You</div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {YOU_NAV.map(renderItem)}
        </nav>

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

      {/* Main */}
      <main className="app-main">{children}</main>

      {/* Global task toasts */}
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
      <DashboardShell>{children}</DashboardShell>
    </DashboardProvider>
  );
}
