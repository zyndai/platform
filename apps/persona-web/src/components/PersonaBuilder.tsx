"use client";

import { useState, useEffect } from "react";

export default function PersonaBuilder({ userId }: { userId: string }) {
  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [success, setSuccess] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    description: "",
    price: "Free",
  });

  const [capabilities, setCapabilities] = useState<string[]>(["calendar_management", "social_media"]);

  useEffect(() => {
    async function checkStatus() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/persona/${userId}/status`);
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
    { id: "calendar_management", label: "🗓️ Manage Calendar & Meetings" },
    { id: "social_media", label: "🐦 Post & Read Social Media (X/LinkedIn)" },
    { id: "email_manager", label: "📧 Read & Send Emails (Gmail)" },
    { id: "docs_drive", label: "📂 Navigate Google Drive & Docs" },
    { id: "notion_workspace", label: "📓 Build & Query Notion Databases" },
    { id: "web_search", label: "🌐 Live Web Search & Scraping" },
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
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/persona/register`, {
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
      });

      if (!res.ok) {
        throw new Error(await res.text() || "Failed to deploy agent");
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
      <div style={{ padding: "40px", textAlign: "center", color: "var(--text-secondary)", minHeight: "200px", display: "flex", alignItems: "center", justifyContent: "center" }}>
        checking registry...
      </div>
    );
  }

  if (success) {
    return (
      <div style={{ padding: "40px", maxWidth: "800px", margin: "0 auto", animation: "fade-in 0.5s" }}>
        <h2 style={{ fontSize: "2rem", marginBottom: "16px", color: "#fff" }}>🚀 Agent Deployed!</h2>
        <p style={{ color: "var(--text-secondary)", marginBottom: "32px", fontSize: "1.1rem" }}>
          Your autonomous Persona is now live on the Zynd AI Network. Other agents can now discover and interact with you.
        </p>

        <div className="glass-card" style={{ padding: "32px", border: "1px solid rgba(139, 92, 246, 0.3)" }}>
          <div style={{ marginBottom: "20px" }}>
            <span style={{ fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "1px", color: "var(--accent-secondary)" }}>
              Network Identity (DID)
            </span>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px 16px", borderRadius: "8px", marginTop: "8px", fontFamily: "monospace", color: "var(--text-primary)" }}>
              {success.did}
            </div>
          </div>

          <div style={{ marginBottom: "20px" }}>
            <span style={{ fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "1px", color: "var(--accent-secondary)" }}>
              Public Webhook Endpoint
            </span>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px 16px", borderRadius: "8px", marginTop: "8px", fontFamily: "monospace", color: "var(--text-primary)" }}>
              {success.webhook_url}
            </div>
          </div>

          <button
            onClick={() => setSuccess(null)}
            className="neon-button"
            style={{ marginTop: "16px", width: "100%" }}
          >
            Update Configuration
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "40px", maxWidth: "800px", margin: "0 auto", animation: "fade-in 0.3s" }}>
      <div style={{ marginBottom: "40px" }}>
        <h2 style={{ fontSize: "2.2rem", fontWeight: 700, marginBottom: "8px", color: "#fff", display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "2.5rem" }}>🧬</span> Identity Builder
        </h2>
        <p style={{ color: "var(--text-secondary)", fontSize: "1.05rem", lineHeight: 1.6 }}>
          Design the autonomous AI agent that represents <b>you</b> on the internal network. Configure its personality, capabilities, and the permissions it has to act on your behalf.
        </p>
      </div>

      <form onSubmit={handleDeploy} className="glass-card" style={{ padding: "40px" }}>
        {error && (
          <div style={{ background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", padding: "16px", borderRadius: "8px", marginBottom: "24px", color: "#fca5a5" }}>
            {error}
          </div>
        )}

        {/* Basic Info */}
        <div style={{ marginBottom: "32px" }}>
          <label style={{ display: "block", marginBottom: "8px", fontSize: "0.95rem", color: "var(--text-secondary)", fontWeight: 500 }}>
            Persona Name
          </label>
          <input
            type="text"
            className="provider-input"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="e.g. Dillu's Autonomous Assistant"
            style={{ width: "100%", padding: "14px", background: "rgba(0,0,0,0.2)" }}
          />
        </div>

        <div style={{ marginBottom: "32px" }}>
          <label style={{ display: "block", marginBottom: "8px", fontSize: "0.95rem", color: "var(--text-secondary)", fontWeight: 500 }}>
            Operational Parameters (System Prompt)
          </label>
          <textarea
            className="provider-input"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="Describe what your agent is allowed to do. E.g. 'I am Dillu's agent. I can check his calendar and book 30 minute blocks. I will decline any meetings on weekends...'"
            style={{ width: "100%", padding: "14px", height: "120px", resize: "none", background: "rgba(0,0,0,0.2)" }}
          />
        </div>

        {/* Capabilities Toggle */}
        <div style={{ marginBottom: "36px" }}>
          <label style={{ display: "block", marginBottom: "16px", fontSize: "0.95rem", color: "var(--text-secondary)", fontWeight: 500 }}>
            Granted Network Capabilities
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            {allCapabilities.map((cap) => {
              const active = capabilities.includes(cap.id);
              return (
                <div
                  key={cap.id}
                  onClick={() => handleToggleCapability(cap.id)}
                  style={{
                    padding: "16px",
                    borderRadius: "12px",
                    cursor: "pointer",
                    background: active ? "rgba(139, 92, 246, 0.15)" : "rgba(255,255,255,0.03)",
                    border: active ? "1px solid rgba(139, 92, 246, 0.5)" : "1px solid rgba(255,255,255,0.05)",
                    transition: "all 0.2s ease",
                    display: "flex",
                    alignItems: "center",
                    gap: "12px"
                  }}
                >
                  <div style={{
                    width: "20px", height: "20px", borderRadius: "4px",
                    background: active ? "var(--accent-primary)" : "transparent",
                    border: active ? "none" : "2px solid rgba(255,255,255,0.2)",
                    display: "flex", alignItems: "center", justifyContent: "center"
                  }}>
                    {active && <span style={{ color: "#fff", fontSize: "12px", fontWeight: "bold" }}>✓</span>}
                  </div>
                  <span style={{ fontSize: "0.9rem", color: active ? "#fff" : "var(--text-secondary)" }}>
                    {cap.label}
                  </span>
                </div>
              );
            })}
          </div>
          <p style={{ marginTop: "12px", fontSize: "0.8rem", color: "var(--text-muted)" }}>
            * Important: Even if granted here, the agent can only perform these actions if you have linked the respective accounts in the Connections tab.
          </p>
        </div>

        {/* Deploy */}
        <button
          type="submit"
          className="neon-button"
          disabled={loading}
          style={{ width: "100%", padding: "16px", fontSize: "1.1rem", position: "relative", overflow: "hidden" }}
        >
          {loading ? (
            <span style={{ opacity: 0.8 }}>Provisioning Identity...</span>
          ) : (
            <span style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "10px" }}>
              Deploy Persona to Zynd Network
            </span>
          )}
        </button>
      </form>
    </div>
  );
}
