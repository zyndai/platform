"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";

const NAV_ITEMS = [
  { href: "/dashboard/chat", label: "AI Chat", icon: "⚡" },
  { href: "/dashboard/messages", label: "Network DMs", icon: "◈" },
  { href: "/dashboard/identity", label: "Identity", icon: "◎" },
  { href: "/dashboard/connections", label: "Connections", icon: "⬡" },
];

function DashboardShell({ children }: { children: React.ReactNode }) {
  const { user, loading, handleLogout } = useDashboard();
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg-void)",
        }}
      >
        <div className="status-pill">
          <span className="status-dot" />
          <span>Connecting to network...</span>
        </div>
      </div>
    );
  }

  const displayName =
    user?.user_metadata?.full_name ||
    user?.user_metadata?.name ||
    user?.email?.split("@")[0] ||
    "User";

  const avatarUrl =
    user?.user_metadata?.avatar_url || user?.user_metadata?.picture || null;

  return (
    <div className="page-bg">
      {/* ── Mobile top header ── */}
      <div className="mobile-header">
        <button
          onClick={() => setSidebarOpen(true)}
          style={{
            background: "none",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-sm)",
            padding: "6px 10px",
            color: "var(--text-primary)",
            cursor: "pointer",
            fontSize: "14px",
          }}
        >
          ☰
        </button>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            className="sidebar-logo-icon"
            style={{ width: 24, height: 24, fontSize: 10 }}
          >
            Z
          </div>
          <span
            style={{
              fontFamily: "Syne, sans-serif",
              fontWeight: 700,
              fontSize: "14px",
            }}
          >
            Zynd <span style={{ color: "var(--accent-teal)" }}>AI</span>
          </span>
        </div>
      </div>

      <div
        className={`mobile-overlay ${sidebarOpen ? "open" : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* ── Sidebar ────────────────────────────────────── */}
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        {/* Logo */}
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">Z</div>
          <span className="sidebar-logo-text">
            Zynd <span className="ai">AI</span>
          </span>
        </div>

        {/* Section label */}
        <p
          className="section-label"
          style={{ padding: "0 4px", marginBottom: "12px" }}
        >
          Navigation
        </p>

        {/* Navigation */}
        <nav
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "2px",
            flex: 1,
          }}
        >
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setSidebarOpen(false)}
                className={`nav-item ${isActive ? "active" : ""}`}
                style={{ textDecoration: "none" }}
              >
                <span className="nav-item-icon">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* User card */}
        <div className="user-card">
          <div className="user-card-avatar">
            {avatarUrl ? (
              <img src={avatarUrl} alt="" />
            ) : (
              <div className="user-card-avatar-fallback">
                {displayName[0]?.toUpperCase()}
              </div>
            )}
            <span className="online-dot" />
          </div>
          <div className="user-card-info">
            <p className="user-card-name">{displayName}</p>
            <p className="user-card-did">{user?.email}</p>
          </div>
          <button
            onClick={handleLogout}
            title="Sign out"
            className="user-card-logout"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────── */}
      <main className="dashboard-main">{children}</main>
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
