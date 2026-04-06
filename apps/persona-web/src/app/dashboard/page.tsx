"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { type User } from "@supabase/supabase-js";
import ChatInterface from "@/components/ChatInterface";
import ConnectionsPanel from "@/components/ConnectionsPanel";
import PersonaBuilder from "@/components/PersonaBuilder";
import MessagesPanel from "@/components/MessagesPanel";

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"chat" | "connections" | "persona" | "messages">("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    const sb = getSupabase();

    // Listen for auth state changes (covers hash-fragment token exchange too)
    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((event, session) => {
      if (!session) {
        router.replace("/");
      } else {
        setUser(session.user);
        setLoading(false);
      }
    });

    // Also do an immediate session check
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/");
      } else {
        setUser(session.user);
        setLoading(false);
      }
    });

    return () => subscription.unsubscribe();
  }, [router]);

  const handleLogout = async () => {
    await getSupabase().auth.signOut();
    router.push("/");
  };

  if (loading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg-primary)",
        }}
      >
        <div className="shimmer-bg glass-card" style={{ padding: "40px 60px", borderRadius: "var(--radius)" }}>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>Loading…</p>
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
    <div style={{ minHeight: "100vh", background: "var(--bg-primary)" }} className="dot-grid">
      {/* ── Mobile top header block ── */}
      <div className="mobile-header">
        <button onClick={() => setSidebarOpen(true)} className="btn btn-outline" style={{ padding: "8px 12px", border: "none" }}>
          ☰
        </button>
        <span style={{ fontSize: "1.1rem", fontWeight: 700, marginLeft: "12px" }}>Zynd AI</span>
      </div>

      <div 
        className={`mobile-overlay ${sidebarOpen ? 'open' : ''}`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* ── Sidebar ────────────────────────────────────── */}
      <aside
        className={`desktop-sidebar ${sidebarOpen ? 'open' : ''}`}
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          height: "100vh",
          background: "var(--bg-secondary)",
          borderRight: "1px solid var(--border-color)",
          display: "flex",
          flexDirection: "column",
          padding: "24px 16px",
          zIndex: 50,
        }}
      >
        {/* Logo */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            marginBottom: "40px",
            paddingLeft: "4px",
          }}
        >
          <div
            style={{
              width: "32px",
              height: "32px",
              minWidth: "32px",
              borderRadius: "8px",
              background: "linear-gradient(135deg, var(--accent-primary), #8b5cf6)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "0.95rem",
              fontWeight: 800,
              color: "#fff",
            }}
          >
            Z
          </div>
          <span className="sidebar-text" style={{ fontSize: "1.15rem", fontWeight: 700 }}>Zynd AI</span>
        </div>

        {/* Navigation */}
        <nav style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1 }}>
          {[
            { id: "chat" as const, label: "AI Chat", icon: "💬" },
            { id: "messages" as const, label: "Network Messages", icon: "📬" },
            { id: "persona" as const, label: "My Persona", icon: "🧬" },
            { id: "connections" as const, label: "Connections", icon: "🔗" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
                padding: "12px 14px",
                borderRadius: "var(--radius-sm)",
                border: "none",
                background:
                  activeTab === tab.id
                    ? "rgba(108, 92, 231, 0.12)"
                    : "transparent",
                color:
                  activeTab === tab.id
                    ? "var(--accent-secondary)"
                    : "var(--text-secondary)",
                fontSize: "0.9rem",
                fontWeight: activeTab === tab.id ? 600 : 500,
                cursor: "pointer",
                transition: "all 0.2s ease",
                textAlign: "left",
                fontFamily: "var(--font-sans)",
              }}
            >
              <span style={{ fontSize: "1.1rem", minWidth: "24px" }}>{tab.icon}</span>
              <span className="sidebar-text">{tab.label}</span>
            </button>
          ))}
        </nav>

        {/* User profile */}
        <div
          className="user-profile-widget"
          style={{
            borderTop: "1px solid var(--border-color)",
            paddingTop: "16px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt=""
              style={{
                width: "34px",
                height: "34px",
                borderRadius: "50%",
                objectFit: "cover",
              }}
            />
          ) : (
            <div
              style={{
                width: "34px",
                height: "34px",
                borderRadius: "50%",
                background: "linear-gradient(135deg, var(--accent-primary), #8b5cf6)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: "0.8rem",
                fontWeight: 700,
                color: "#fff",
              }}
            >
              {displayName[0]?.toUpperCase()}
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <p
              style={{
                fontSize: "0.85rem",
                fontWeight: 600,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {displayName}
            </p>
            <p
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user?.email}
            </p>
          </div>
          <button
            onClick={handleLogout}
            title="Sign out"
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              cursor: "pointer",
              fontSize: "1rem",
              padding: "4px",
              transition: "color 0.2s ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = "var(--danger)")}
            onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
          >
            ⏻
          </button>
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────── */}
      <main className="desktop-main" style={{ minHeight: "100vh" }}>
        {activeTab === "chat" && <ChatInterface />}
        {activeTab === "messages" && <MessagesPanel />}
        {activeTab === "persona" && <PersonaBuilder userId={user?.id || ""} />}
        {activeTab === "connections" && <ConnectionsPanel />}
      </main>
    </div>
  );
}
