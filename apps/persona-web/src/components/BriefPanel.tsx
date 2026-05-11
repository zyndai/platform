"use client";

import { useEffect, useState } from "react";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost } from "@/lib/api";

interface BriefState {
  exists: boolean;
  doc_id?: string;
  url?: string;
  content?: string;
  title?: string;
  fallback_description?: string;
  error?: string;
}

export default function BriefPanel() {
  const { user } = useDashboard();
  const [brief, setBrief] = useState<BriefState | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBrief = async () => {
    if (!user?.id) return;
    try {
      const data = await apiGet<BriefState>(`/api/persona/${user.id}/brief`);
      setBrief(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load brief.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.id) fetchBrief();
  }, [user?.id]);

  const handleCreate = async () => {
    if (!user?.id) return;
    setCreating(true);
    setError(null);
    try {
      await apiPost(`/api/persona/${user.id}/brief/init`, {});
      await fetchBrief();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create brief doc.");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <Header />
        <EmptyContainer>Loading brief…</EmptyContainer>
      </Shell>
    );
  }

  if (error) {
    return (
      <Shell>
        <Header />
        <EmptyContainer style={{ color: "#f87171" }}>{error}</EmptyContainer>
      </Shell>
    );
  }

  if (!brief?.exists) {
    return (
      <Shell>
        <Header />
        <EmptyContainer>
          <h2 style={{ fontFamily: "Syne, sans-serif", fontSize: "20px", marginBottom: "8px" }}>
            Create your Brief
          </h2>
          <p style={{ color: "var(--text-secondary)", marginBottom: "20px", maxWidth: "480px" }}>
            Your Brief is the long-form context the AI agent uses to represent you. It lives as
            a single Google Doc your agent created — the agent can only see this one doc, never
            the rest of your Drive. Edit it here or in Google Docs, and your agent picks up
            the changes automatically.
          </p>
          {brief?.fallback_description && (
            <div
              style={{
                background: "var(--bg-void)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--r-sm)",
                padding: "12px 14px",
                maxWidth: "480px",
                marginBottom: "20px",
                fontSize: "13px",
                color: "var(--text-secondary)",
                whiteSpace: "pre-wrap",
              }}
            >
              <p
                className="section-label"
                style={{ marginBottom: "6px" }}
              >
                CURRENT SHORT BRIEF (will seed the doc)
              </p>
              {brief.fallback_description}
            </div>
          )}
          <button
            className="btn-primary"
            onClick={handleCreate}
            disabled={creating}
            style={{ minWidth: "200px" }}
          >
            {creating ? "Creating…" : "Create my Brief"}
          </button>
        </EmptyContainer>
      </Shell>
    );
  }

  // Brief exists — embed the Google Doc editor.
  const embedUrl = `https://docs.google.com/document/d/${brief.doc_id}/edit?embedded=true&rm=minimal`;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--bg-base)",
      }}
    >
      <Header
        rightSlot={
          brief.url && (
            <a
              href={brief.url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
              style={{ fontSize: "12px", textDecoration: "none" }}
            >
              Open in Google Docs ↗
            </a>
          )
        }
      />
      {brief.error && (
        <div
          style={{
            background: "rgba(248, 113, 113, 0.1)",
            border: "1px solid rgba(248, 113, 113, 0.3)",
            color: "#f87171",
            padding: "8px 16px",
            fontSize: "12px",
          }}
        >
          Couldn’t fetch live content from Google: {brief.error}. The embed below may still work.
        </div>
      )}
      <div style={{ flex: 1, padding: "0", background: "white" }}>
        <iframe
          src={embedUrl}
          title="Brief"
          style={{
            width: "100%",
            height: "100%",
            border: "none",
          }}
        />
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--bg-base)",
      }}
    >
      {children}
    </div>
  );
}

function EmptyContainer({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "32px",
        gap: "12px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function Header({ rightSlot }: { rightSlot?: React.ReactNode }) {
  return (
    <div
      className="topbar"
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        height: "auto",
        padding: "20px 24px",
        gap: "16px",
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "18px",
            fontWeight: 700,
            color: "var(--text-primary)",
            marginBottom: "4px",
          }}
        >
          Brief
        </h1>
        <p className="section-label">YOUR AGENT'S SOURCE OF TRUTH ABOUT YOU</p>
      </div>
      {rightSlot}
    </div>
  );
}
