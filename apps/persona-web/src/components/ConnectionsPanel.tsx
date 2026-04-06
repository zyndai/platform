"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { apiGet, apiDelete } from "@/lib/api";

/**
 * ConnectionsPanel
 *
 * Managed Google Workspace, Notion, and Social platforms.
 * Uses custom backend OAuth flows to get scoped API tokens.
 */

interface ConnectionStatus {
  connected: boolean;
  scopes?: string;
}

interface ConnectionsResponse {
  connections: Record<string, ConnectionStatus>;
}

const PROVIDERS = [
  {
    id: "google",
    name: "Google Workspace",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.747-.053-1.453-.16-2.053H12.48z" />
      </svg>
    ),
    color: "#ea4335",
    gradient: "linear-gradient(135deg, #ea4335, #d93025)",
    features: ["Gmail", "Calendar", "Docs", "Sheets"],
  },
  {
    id: "notion",
    name: "Notion",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M4.459 4.211c.192.154.501.405.501.927v13.56c0 .405-.212.559-.501.714l-1.93.965V3.246l1.93.965zm15.081.501c.212.154.347.386.347.675v13.464c0 .405-.212.559-.501.714l-1.93.965s-1.408-.887-1.794-1.141c-.096-.058-.231-.192-.231-.443v-1.93s-3.568.019-3.568-.019c0 .192.212.675.212.927 0 .231-.231.424-.463.559-1.041.598-1.543.887-2.296 1.331-.058.038-.27.174-.463.174-.231 0-.463-.115-.656-.251-.231-.174-2.817-1.775-2.817-1.775V6.448s.559-.347.791-.501c.192-.115.347-.212.347-.483 0-.174-.154-.347-.327-.443L5.809 3.246h11.233l2.498 1.466zm-5.057 12.352c-.174 0-.347.174-.347.347 0 .154.174.327.347.327h1.93v-.675h-1.93zm-1.041-9.932H8.399v8.948h2.063V8.899l2.488 4.228 1.042-.616-1.042-.616V7.132h2.063v1.003L15.013 7.132z" />
      </svg>
    ),
    color: "#000000",
    gradient: "linear-gradient(135deg, #333333, #000000)",
    features: ["Search pages", "Create blocks", "Append content"],
  },
  {
    id: "twitter",
    name: "X / Twitter",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
      </svg>
    ),
    color: "#1da1f2",
    gradient: "linear-gradient(135deg, #1da1f2, #0d8bd9)",
    features: ["Post tweets", "Read timeline", "Send & read DMs"],
  },
  {
    id: "linkedin",
    name: "LinkedIn",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
      </svg>
    ),
    color: "#0077b5",
    gradient: "linear-gradient(135deg, #0077b5, #005fa3)",
    features: ["Post to feed", "DMs (coming soon)"],
  },
  {
    id: "telegram",
    name: "Telegram Bot",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.539.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.295-.6.295-.002 0-.003 0-.005 0l.213-3.054 5.56-5.022c.24-.213-.054-.334-.373-.121l-6.869 4.326-2.96-.924c-.64-.203-.658-.64.135-.954l11.566-4.458c.538-.196 1.006.128.832.94z"/>
      </svg>
    ),
    color: "#0088cc",
    gradient: "linear-gradient(135deg, #0088cc, #005f8e)",
    features: ["Talk to agent from mobile", "Hands-free mobile experience"],
  },
];

const GOOGLE_SERVICES = [
  { id: "gmail", name: "Gmail", desc: "Search, read and send emails" },
  { id: "calendar", name: "Calendar", desc: "Schedule events" },
  { id: "docs", name: "Docs & Drive", desc: "Manage documents and files" },
  { id: "sheets", name: "Sheets", desc: "Create and update spreadsheets" },
];

export default function ConnectionsPanel() {
  const [connections, setConnections] = useState<Record<string, ConnectionStatus>>({});
  const [loading, setLoading] = useState(true);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  
  const [googleFeatures, setGoogleFeatures] = useState({
    gmail: true,
    calendar: true,
    docs: true,
    sheets: true,
  });

  const searchParams = useSearchParams();

  const fetchConnections = async () => {
    try {
      const data = await apiGet<ConnectionsResponse>("/api/connections/");
      setConnections(data.connections);
      
      const google = data.connections["google"];
      if (google?.connected && google.scopes) {
        setGoogleFeatures({
          gmail: google.scopes.includes("gmail"),
          calendar: google.scopes.includes("calendar"),
          docs: google.scopes.includes("documents") || google.scopes.includes("metadata"),
          sheets: google.scopes.includes("spreadsheets"),
        });
      }
    } catch (err) {
      console.error("Fetch connections error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const oauthProvider = searchParams.get("oauth");
    const oauthStatus = searchParams.get("status");

    if (oauthProvider && oauthStatus) {
      if (oauthStatus === "success") {
        setToast({ message: `${oauthProvider} connected successfully!`, type: "success" });
      } else {
        setToast({ message: `Failed to connect ${oauthProvider}.`, type: "error" });
      }
      window.history.replaceState(null, "", "/dashboard");
      fetchConnections();
    }
  }, [searchParams]);

  useEffect(() => {
    fetchConnections();
  }, []);

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const handleConnect = async (providerId: string) => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();

    if (!session?.access_token) {
      setToast({ message: "Please sign in first.", type: "error" });
      return;
    }

    let extraParams = "";
    if (providerId === "google") {
      const selected = [];
      if (googleFeatures.gmail) selected.push("gmail");
      if (googleFeatures.calendar) selected.push("calendar");
      if (googleFeatures.docs) selected.push("docs");
      if (googleFeatures.sheets) selected.push("sheets");
      extraParams = `&features=${selected.join(",")}`;
    }

    if (providerId === "telegram") {
      const telegramBotUsername = "zynd_persona_telegram_bot"; 
      window.open(`https://t.me/${telegramBotUsername}?start=${session.user.id}`, "_blank");
      
      // Assume success since clicking deep link auto-sends message in telegram
      setToast({ message: "Opened Telegram app! Please click 'Start' in the bot.", type: "success" });
      setTimeout(fetchConnections, 5000); // refresh after a few sec to see if they connected
      return;
    }

    const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const authorizeUrl = `${backendUrl}/api/oauth/${providerId}/authorize?token=${session.access_token}${extraParams}`;
    window.location.href = authorizeUrl;
  };

  const handleDisconnect = async (providerId: string) => {
    setDisconnecting(providerId);
    try {
      await apiDelete(`/api/connections/${providerId}`);
      setConnections((prev) => ({
        ...prev,
        [providerId]: { connected: false },
      }));
      setToast({ message: `${providerId} disconnected.`, type: "success" });
    } catch (err) {
      setToast({ message: "Failed to disconnect.", type: "error" });
    } finally {
      setDisconnecting(null);
    }
  };

  return (
    <div style={{ padding: "32px" }}>
      {toast && (
        <div
          style={{
            position: "fixed", top: "20px", right: "20px", padding: "14px 20px",
            borderRadius: "var(--radius-sm)", zIndex: 1000,
            background: toast.type === "success" ? "rgba(16, 185, 129, 0.15)" : "rgba(239, 68, 68, 0.15)",
            border: `1px solid ${toast.type === "success" ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
            color: toast.type === "success" ? "#10b981" : "#ef4444",
            backdropFilter: "blur(12px)", animation: "fadeInUp 0.3s ease forwards",
          }}
        >
          {toast.type === "success" ? "✓ " : "✗ "}{toast.message}
        </div>
      )}

      <div style={{ marginBottom: "40px" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "8px" }}>Connections</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
          Manage access to your tools and social platforms.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "24px" }}>
        {PROVIDERS.map((provider) => {
          const status = connections[provider.id];
          const isConnected = status?.connected ?? false;

          return (
            <div
              key={provider.id}
              className="glass-card"
              style={{
                padding: "24px", display: "flex", flexDirection: "column", gap: "20px",
                border: "1px solid var(--border-color)", background: "var(--bg-card)",
                borderRadius: "var(--radius)", transition: "all 0.3s ease",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <div style={{
                  width: "44px", height: "44px", borderRadius: "12px",
                  background: `${provider.color}15`, display: "flex", alignItems: "center",
                  justifyContent: "center", color: provider.color, border: `1px solid ${provider.color}30`
                }}>
                  {provider.icon}
                </div>
                <div>
                  <h3 style={{ fontSize: "1.1rem", fontWeight: 700 }}>{provider.name}</h3>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginTop: "2px" }}>
                    <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: isConnected ? "var(--success)" : "#4b5563" }} />
                    <span style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontWeight: 500 }}>
                      {isConnected ? "Connected" : "Not Linked"}
                    </span>
                  </div>
                </div>
              </div>

              {provider.id === "google" && (
                <div style={{ background: "rgba(255,255,255,0.03)", padding: "16px", borderRadius: "10px", border: "1px solid rgba(255,255,255,0.05)" }}>
                  <p style={{ fontSize: "0.7rem", fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "12px" }}>
                    Select Services
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    {GOOGLE_SERVICES.map(feat => {
                      const isActive = isConnected && status.scopes?.includes(
                        feat.id === "docs" ? "drive" : feat.id === "sheets" ? "spreadsheets" : feat.id
                      );
                      return (
                        <label key={feat.id} style={{ display: "flex", alignItems: "center", gap: "12px", cursor: "pointer" }}>
                          <input 
                            type="checkbox"
                            checked={googleFeatures[feat.id as keyof typeof googleFeatures]}
                            onChange={(e) => setGoogleFeatures(prev => ({ ...prev, [feat.id]: e.target.checked }))}
                            style={{ width: "16px", height: "16px", accentColor: "var(--accent-primary)" }}
                          />
                          <div style={{ flex: 1 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <span style={{ fontSize: "0.85rem", fontWeight: 600 }}>{feat.name}</span>
                              {isActive && <span style={{ fontSize: "0.6rem", padding: "1px 5px", background: "rgba(16, 185, 129, 0.1)", color: "#10b981", borderRadius: "4px" }}>ACTIVE</span>}
                            </div>
                            <p style={{ fontSize: "0.65rem", color: "var(--text-muted)" }}>{feat.desc}</p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}

              {provider.id !== "google" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  <div style={{ background: "rgba(255,255,255,0.02)", padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.04)' }}>
                    <p style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginBottom: '8px', textTransform: 'uppercase' }}>Capabilities</p>
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      {provider.features.map((feat, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.8rem", color: "var(--text-secondary)" }}>
                          <span style={{ width: "4px", height: "4px", borderRadius: "50%", background: provider.color, opacity: 0.6 }} />
                          {feat}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div style={{ marginTop: "auto" }}>
                {isConnected ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    {provider.id === "google" && (
                      <button className="btn btn-primary" onClick={() => handleConnect(provider.id)} style={{ width: "100%", fontSize: "0.85rem" }}>
                        Update Permissions
                      </button>
                    )}
                    <button className="btn btn-outline" onClick={() => handleDisconnect(provider.id)} disabled={disconnecting === provider.id} style={{ width: "100%", fontSize: "0.85rem", color: "#ef4444", borderColor: "rgba(239, 68, 68, 0.2)" }}>
                      {disconnecting === provider.id ? "..." : "Remove Account"}
                    </button>
                  </div>
                ) : (
                  <button className="btn btn-primary" onClick={() => handleConnect(provider.id)} style={{ width: "100%", fontSize: "0.85rem" }}>
                    Connect {provider.name}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
