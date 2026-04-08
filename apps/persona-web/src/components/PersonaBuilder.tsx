"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PersonaBuilder({ userId }: { userId: string }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [success, setSuccess] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    description: "",
    price: "Free",
  });

  const [capabilities, setCapabilities] = useState<string[]>([
    "calendar_management",
    "social_media",
  ]);

  useEffect(() => {
    async function checkStatus() {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/persona/${userId}/status`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.deployed) {
            setSuccess(data);
          }
        }
      } catch (e) {
        console.error("Failed to check persona status", e);
      } finally {
        setInitialLoad(false);
      }
    }
    checkStatus();
  }, [userId]);

  const allCapabilities = [
    { id: "calendar_management", label: "Manage Calendar & Meetings", icon: "◈" },
    { id: "social_media", label: "Post & Read Social Media (X/LinkedIn)", icon: "◎" },
    { id: "email_manager", label: "Read & Send Emails (Gmail)", icon: "⬡" },
    { id: "docs_drive", label: "Navigate Google Drive & Docs", icon: "▣" },
    { id: "notion_workspace", label: "Build & Query Notion Databases", icon: "◇" },
    { id: "web_search", label: "Live Web Search & Scraping", icon: "⊕" },
  ];

  const handleToggleCapability = (id: string) => {
    setCapabilities((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  };

  const handleDeploy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.description) {
      setError("Please fill out your Agent's Name and Description.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/persona/register`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            user_id: userId,
            name: formData.name,
            description: formData.description,
            capabilities,
            price: formData.price,
          }),
        }
      );

      if (!res.ok) {
        throw new Error((await res.text()) || "Failed to deploy agent");
      }

      const data = await res.json();
      setSuccess(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (initialLoad) {
    return (
      <div
        style={{
          height: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg-base)",
        }}
      >
        <div className="status-pill">
          <span className="status-dot" />
          Checking registry...
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100vh",
          background: "var(--bg-base)",
        }}
      >
        {/* Header */}
        <div
          className="topbar"
          style={{
            flexDirection: "column",
            alignItems: "flex-start",
            justifyContent: "center",
            height: "auto",
            padding: "20px 24px",
          }}
        >
          <h1
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "18px",
              fontWeight: 700,
              marginBottom: "4px",
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            <span style={{ color: "var(--accent-teal)" }}>◎</span> Agent Deployed
          </h1>
          <p className="section-label">IDENTITY ACTIVE ON ZYND NETWORK</p>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
          <div style={{ maxWidth: "640px", margin: "0 auto" }}>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: "14px",
                lineHeight: 1.65,
                marginBottom: "24px",
              }}
            >
              Your autonomous Persona is now live on the Zynd AI Network. Other
              agents can discover and interact with you.
            </p>

            {/* DID Block */}
            <div className="identity-block" style={{ marginBottom: "16px" }}>
              <p className="section-label" style={{ marginBottom: "8px" }}>
                NETWORK IDENTITY (DID)
              </p>
              <div className="did-string">{success.did}</div>
              <div className="verified-badge" style={{ marginTop: "10px" }}>
                <span>✓</span> Verified on Network
              </div>
            </div>

            {/* Webhook */}
            <div className="identity-block" style={{ marginBottom: "24px" }}>
              <p className="section-label" style={{ marginBottom: "8px" }}>
                PUBLIC WEBHOOK ENDPOINT
              </p>
              <div className="did-string">{success.webhook_url}</div>
            </div>

            <button
              onClick={() => router.push("/dashboard/chat")}
              className="btn-primary"
              style={{ width: "100%", marginBottom: "10px", padding: "14px", fontSize: "14px" }}
            >
              Go to AI Chat →
            </button>
            <button
              onClick={() => setSuccess(null)}
              className="btn-secondary"
              style={{ width: "100%" }}
            >
              Update Configuration
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--bg-base)",
      }}
    >
      {/* Header */}
      <div
        className="topbar"
        style={{
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "center",
          height: "auto",
          padding: "20px 24px",
        }}
      >
        <h1
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "18px",
            fontWeight: 700,
            marginBottom: "4px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span style={{ color: "var(--accent-purple)" }}>◎</span> Identity Builder
        </h1>
        <p className="section-label">CONFIGURE YOUR AUTONOMOUS AI AGENT</p>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        <div style={{ maxWidth: "640px", margin: "0 auto" }}>
          <p
            style={{
              color: "var(--text-secondary)",
              fontSize: "14px",
              lineHeight: 1.65,
              marginBottom: "28px",
            }}
          >
            Design the autonomous AI agent that represents{" "}
            <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>
              you
            </span>{" "}
            on the network. Configure its personality, capabilities, and
            permissions.
          </p>

          <form onSubmit={handleDeploy}>
            {error && (
              <div
                style={{
                  background: "rgba(255, 95, 109, 0.08)",
                  border: "1px solid rgba(255, 95, 109, 0.20)",
                  padding: "12px 16px",
                  borderRadius: "var(--r-md)",
                  marginBottom: "20px",
                  color: "var(--accent-coral)",
                  fontSize: "13px",
                }}
              >
                {error}
              </div>
            )}

            {/* Persona Name */}
            <div style={{ marginBottom: "24px" }}>
              <label
                style={{
                  display: "block",
                  marginBottom: "8px",
                  fontFamily: "DM Sans, sans-serif",
                  fontSize: "13px",
                  fontWeight: 500,
                  color: "var(--text-secondary)",
                }}
              >
                Persona Name
              </label>
              <input
                type="text"
                className="input"
                value={formData.name}
                onChange={(e) =>
                  setFormData({ ...formData, name: e.target.value })
                }
                placeholder="e.g. Dillu's Autonomous Assistant"
              />
            </div>

            {/* System Prompt */}
            <div style={{ marginBottom: "24px" }}>
              <label
                style={{
                  display: "block",
                  marginBottom: "8px",
                  fontFamily: "DM Sans, sans-serif",
                  fontSize: "13px",
                  fontWeight: 500,
                  color: "var(--text-secondary)",
                }}
              >
                Operational Parameters (System Prompt)
              </label>
              <textarea
                className="input"
                value={formData.description}
                onChange={(e) =>
                  setFormData({ ...formData, description: e.target.value })
                }
                placeholder="Describe what your agent is allowed to do..."
                style={{
                  height: "110px",
                  resize: "none",
                  lineHeight: 1.6,
                }}
              />
            </div>

            {/* Capabilities */}
            <div style={{ marginBottom: "28px" }}>
              <label
                style={{
                  display: "block",
                  marginBottom: "6px",
                  fontFamily: "DM Sans, sans-serif",
                  fontSize: "13px",
                  fontWeight: 500,
                  color: "var(--text-secondary)",
                }}
              >
                Granted Network Capabilities
              </label>
              <p className="section-label" style={{ marginBottom: "14px" }}>
                SELECT ACTIVE PERMISSIONS
              </p>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "10px",
                }}
              >
                {allCapabilities.map((cap) => {
                  const active = capabilities.includes(cap.id);
                  return (
                    <div
                      key={cap.id}
                      onClick={() => handleToggleCapability(cap.id)}
                      style={{
                        padding: "14px",
                        borderRadius: "var(--r-md)",
                        cursor: "pointer",
                        background: active
                          ? "rgba(0, 212, 180, 0.08)"
                          : "var(--bg-surface)",
                        border: active
                          ? "1px solid rgba(0, 212, 180, 0.25)"
                          : "1px solid var(--border-default)",
                        transition: "all 0.15s ease",
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                      }}
                    >
                      <div
                        style={{
                          width: "18px",
                          height: "18px",
                          borderRadius: "4px",
                          background: active ? "var(--accent-teal)" : "transparent",
                          border: active
                            ? "none"
                            : "1.5px solid var(--text-muted)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        {active && (
                          <span
                            style={{
                              color: "var(--bg-void)",
                              fontSize: "11px",
                              fontWeight: "bold",
                            }}
                          >
                            ✓
                          </span>
                        )}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span
                          style={{
                            fontFamily: "IBM Plex Mono, monospace",
                            fontSize: "12px",
                            color: active ? "var(--accent-teal)" : "var(--text-muted)",
                          }}
                        >
                          {cap.icon}
                        </span>
                        <span
                          style={{
                            fontSize: "12px",
                            fontFamily: "DM Sans, sans-serif",
                            color: active
                              ? "var(--text-primary)"
                              : "var(--text-secondary)",
                          }}
                        >
                          {cap.label}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
              <p
                style={{
                  marginTop: "12px",
                  fontFamily: "IBM Plex Mono, monospace",
                  fontSize: "10px",
                  color: "var(--text-muted)",
                  lineHeight: 1.5,
                }}
              >
                * Even if granted here, the agent can only perform these actions
                if you have linked the respective accounts in the Connections
                tab.
              </p>
            </div>

            {/* Deploy button */}
            <button
              type="submit"
              className="btn-primary"
              disabled={loading}
              style={{
                width: "100%",
                padding: "14px",
                fontSize: "14px",
                fontWeight: 600,
              }}
            >
              {loading ? (
                <span style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="status-dot" /> Provisioning Identity...
                </span>
              ) : (
                "Deploy Persona to Zynd Network"
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
