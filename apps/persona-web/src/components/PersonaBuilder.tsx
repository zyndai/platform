"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useDashboard } from "@/contexts/DashboardContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const ALL_CAPABILITIES = [
  { id: "calendar_management", label: "Manage Calendar & Meetings", icon: "◈" },
  { id: "social_media", label: "Post & Read Social Media (X/LinkedIn)", icon: "◎" },
  { id: "email_manager", label: "Read & Send Emails (Gmail)", icon: "⬡" },
  { id: "docs_drive", label: "Navigate Google Drive & Docs", icon: "▣" },
  { id: "notion_workspace", label: "Build & Query Notion Databases", icon: "◇" },
  { id: "web_search", label: "Live Web Search & Scraping", icon: "⊕" },
];

interface ProfileData {
  title: string;
  organization: string;
  location: string;
  twitter: string;
  linkedin: string;
  github: string;
  website: string;
  interests: string;
}

export default function PersonaBuilder({ userId }: { userId: string }) {
  const router = useRouter();
  const { refreshPersona } = useDashboard();

  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [persona, setPersona] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Form state (used for both create and edit)
  const [formData, setFormData] = useState({
    name: "",
    agent_handle: "",
    description: "",
    price: "Free",
  });
  const [capabilities, setCapabilities] = useState<string[]>([
    "calendar_management",
    "social_media",
  ]);
  const [profile, setProfile] = useState<ProfileData>({
    title: "",
    organization: "",
    location: "",
    twitter: "",
    linkedin: "",
    github: "",
    website: "",
    interests: "",
  });

  useEffect(() => {
    async function checkStatus() {
      try {
        const res = await fetch(`${API}/api/persona/${userId}/status`);
        if (res.ok) {
          const data = await res.json();
          if (data.deployed) {
            setPersona(data);
            setFormData({
              name: data.name || "",
              agent_handle: data.agent_handle || "",
              description: data.description || "",
              price: "Free",
            });
            setCapabilities(data.capabilities || []);
            const p = data.profile || {};
            setProfile({
              title: p.title || "",
              organization: p.organization || "",
              location: p.location || "",
              twitter: p.twitter || "",
              linkedin: p.linkedin || "",
              github: p.github || "",
              website: p.website || "",
              interests: Array.isArray(p.interests) ? p.interests.join(", ") : p.interests || "",
            });
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
      const res = await fetch(`${API}/api/persona/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          name: formData.name,
          agent_handle: formData.agent_handle.trim() || null,
          description: formData.description,
          capabilities,
          price: formData.price,
        }),
      });

      if (!res.ok) throw new Error((await res.text()) || "Failed to deploy agent");

      const data = await res.json();

      // Save profile if any fields are set
      const profilePayload = buildProfilePayload();
      if (Object.keys(profilePayload).length > 0) {
        await fetch(`${API}/api/persona/${userId}/profile`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: profilePayload }),
        });
      }

      await refreshPersona();

      // Reload full status
      const statusRes = await fetch(`${API}/api/persona/${userId}/status`);
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setPersona(statusData);
      } else {
        setPersona(data);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveProfile = async () => {
    setLoading(true);
    setSaveMsg(null);
    setError(null);

    try {
      const profilePayload = buildProfilePayload();
      const res = await fetch(`${API}/api/persona/${userId}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: formData.name || undefined,
          // Send empty string to explicitly clear the agent_handle on the backend
          agent_handle: formData.agent_handle.trim() === "" ? "" : formData.agent_handle.trim(),
          description: formData.description || undefined,
          capabilities,
          profile: profilePayload,
        }),
      });

      if (!res.ok) throw new Error((await res.text()) || "Failed to save");

      const data = await res.json();
      setPersona(data);
      setEditing(false);
      setSaveMsg("Profile updated successfully.");
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Nuke the user's whole account. After success:
  //   1. Sign out the Supabase client so any cached session is dropped.
  //   2. Redirect to "/" so the user lands on the public landing page.
  // The user can then sign back in with the same Google/LinkedIn account
  // and will get a brand new auth.users row with a brand new UUID.
  const handleDeleteAccount = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch(`${API}/api/persona/${userId}/account`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "delete failed");
        throw new Error(txt || "delete failed");
      }

      // Tear down the local session and bounce.
      try {
        await (await import("@/lib/supabase")).getSupabase().auth.signOut();
      } catch {
        /* ignore — we're about to navigate anyway */
      }
      router.replace("/");
    } catch (e: any) {
      setDeleteError(e?.message || String(e));
      setDeleting(false);
    }
  };

  const buildProfilePayload = () => {
    const p: any = {};
    if (profile.title.trim()) p.title = profile.title.trim();
    if (profile.organization.trim()) p.organization = profile.organization.trim();
    if (profile.location.trim()) p.location = profile.location.trim();
    if (profile.twitter.trim()) p.twitter = profile.twitter.trim();
    if (profile.linkedin.trim()) p.linkedin = profile.linkedin.trim();
    if (profile.github.trim()) p.github = profile.github.trim();
    if (profile.website.trim()) p.website = profile.website.trim();
    if (profile.interests.trim()) {
      p.interests = profile.interests.split(",").map((s: string) => s.trim()).filter(Boolean);
    }
    return p;
  };

  if (initialLoad) {
    return (
      <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg-base)" }}>
        <div className="status-pill"><span className="status-dot" />Checking registry...</div>
      </div>
    );
  }

  // ── DEPLOYED STATE: Show full profile ───────────────────────────
  if (persona && !editing) {
    const p = persona.profile || {};
    const socials = [
      { key: "twitter", label: "X / Twitter", prefix: "x.com/", icon: "𝕏" },
      { key: "linkedin", label: "LinkedIn", prefix: "linkedin.com/in/", icon: "in" },
      { key: "github", label: "GitHub", prefix: "github.com/", icon: "◆" },
      { key: "website", label: "Website", prefix: "", icon: "◎" },
    ];

    const profileFields = [
      { label: "Title / Role", value: p.title },
      { label: "Organization", value: p.organization },
      { label: "Location", value: p.location },
    ];

    const emptyStyle = {
      fontFamily: "IBM Plex Mono, monospace",
      fontSize: "12px",
      color: "var(--text-muted)",
      fontStyle: "italic" as const,
      opacity: 0.5,
    };

    const valueStyle = {
      fontFamily: "DM Sans, sans-serif",
      fontSize: "13px",
      color: "var(--text-primary)",
    };

    const labelStyle = {
      fontFamily: "IBM Plex Mono, monospace",
      fontSize: "10px",
      color: "var(--text-muted)",
      letterSpacing: "0.5px",
      textTransform: "uppercase" as const,
      marginBottom: "4px",
    };

    return (
      <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-base)" }}>
        <div className="topbar" style={{ flexDirection: "column", alignItems: "flex-start", justifyContent: "center", height: "auto", padding: "20px 24px" }}>
          <h1 style={{ fontFamily: "Syne, sans-serif", fontSize: "18px", fontWeight: 700, marginBottom: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ color: "var(--accent-teal)" }}>◎</span> My Identity
          </h1>
          <p className="section-label">YOUR ZYND NETWORK PROFILE</p>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
          <div style={{ maxWidth: "640px", margin: "0 auto" }}>

            {saveMsg && (
              <div style={{ background: "rgba(0, 212, 180, 0.08)", border: "1px solid rgba(0, 212, 180, 0.25)", padding: "10px 16px", borderRadius: "var(--r-md)", marginBottom: "20px", color: "var(--accent-teal)", fontSize: "13px" }}>
                {saveMsg}
              </div>
            )}

            {/* ── Header Card ── */}
            <div className="identity-block" style={{ marginBottom: "16px", padding: "24px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "20px" }}>
                <div style={{ width: "56px", height: "56px", borderRadius: "var(--r-md)", background: "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Syne, sans-serif", fontWeight: 800, fontSize: "22px", color: "#fff", flexShrink: 0 }}>
                  {persona.name?.charAt(0) || "Z"}
                </div>
                <div style={{ flex: 1 }}>
                  <h2 style={{ fontFamily: "Syne, sans-serif", fontSize: "18px", fontWeight: 700, color: "var(--text-primary)" }}>{persona.name}</h2>
                  {persona.agent_handle && (
                    <p style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                      AI agent: <span style={{ color: "var(--accent-teal)" }}>{persona.agent_handle}</span>
                    </p>
                  )}
                  <div className="verified-badge" style={{ marginTop: "4px" }}><span>✓</span> Active on Zynd Network</div>
                </div>
              </div>

              {/* System Prompt / Bio */}
              <div style={{ marginBottom: "20px" }}>
                <p style={labelStyle}>System Prompt</p>
                <p style={{ fontSize: "13px", color: persona.description ? "var(--text-secondary)" : "var(--text-muted)", lineHeight: 1.6, borderLeft: "2px solid var(--border-default)", paddingLeft: "12px", fontStyle: persona.description ? "normal" : "italic", opacity: persona.description ? 1 : 0.5 }}>
                  {persona.description || "Not set"}
                </p>
              </div>
            </div>

            {/* ── Profile Details ── */}
            <div className="identity-block" style={{ marginBottom: "16px", padding: "20px" }}>
              <p className="section-label" style={{ marginBottom: "16px" }}>PROFILE DETAILS</p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "20px" }}>
                {profileFields.map((f) => (
                  <div key={f.label}>
                    <p style={labelStyle}>{f.label}</p>
                    <p style={f.value ? valueStyle : emptyStyle}>{f.value || "Not set"}</p>
                  </div>
                ))}
                <div>
                  <p style={labelStyle}>Interests</p>
                  {p.interests && (Array.isArray(p.interests) ? p.interests : [p.interests]).length > 0 ? (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                      {(Array.isArray(p.interests) ? p.interests : [p.interests]).map((tag: string, i: number) => (
                        <span key={i} className="tag tag-teal" style={{ fontSize: "10px" }}>{tag}</span>
                      ))}
                    </div>
                  ) : (
                    <p style={emptyStyle}>Not set</p>
                  )}
                </div>
              </div>
            </div>

            {/* ── Social Links ── */}
            <div className="identity-block" style={{ marginBottom: "16px", padding: "20px" }}>
              <p className="section-label" style={{ marginBottom: "16px" }}>SOCIAL LINKS</p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                {socials.map((s) => {
                  const val = p[s.key];
                  const hasVal = !!val;
                  const url = hasVal ? (val.startsWith("http") ? val : (s.prefix ? `https://${s.prefix}${val}` : val)) : "#";

                  const inner = (
                    <div style={{
                      display: "flex", alignItems: "center", gap: "10px", padding: "12px 14px",
                      borderRadius: "var(--r-md)", background: "var(--bg-surface)",
                      border: `1px solid ${hasVal ? "var(--border-default)" : "var(--border-subtle)"}`,
                      transition: "border-color 0.15s",
                    }}>
                      <span style={{ fontWeight: 700, fontSize: "14px", color: hasVal ? "var(--text-primary)" : "var(--text-muted)", width: "20px", textAlign: "center" }}>{s.icon}</span>
                      <div>
                        <p style={{ ...labelStyle, marginBottom: "2px" }}>{s.label}</p>
                        <p style={hasVal ? { ...valueStyle, fontSize: "12px" } : emptyStyle}>{val || "Not linked"}</p>
                      </div>
                    </div>
                  );

                  return hasVal ? (
                    <a key={s.key} href={url} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
                      {inner}
                    </a>
                  ) : (
                    <div key={s.key}>{inner}</div>
                  );
                })}
              </div>
            </div>

            {/* ── Capabilities ── */}
            <div className="identity-block" style={{ marginBottom: "16px", padding: "20px" }}>
              <p className="section-label" style={{ marginBottom: "14px" }}>GRANTED CAPABILITIES</p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                {ALL_CAPABILITIES.map((cap) => {
                  const active = (persona.capabilities || []).includes(cap.id);
                  return (
                    <span key={cap.id} style={{
                      display: "inline-flex", alignItems: "center", gap: "6px",
                      padding: "6px 12px", borderRadius: "var(--r-sm)",
                      background: active ? "rgba(0, 212, 180, 0.06)" : "var(--bg-surface)",
                      border: `1px solid ${active ? "rgba(0, 212, 180, 0.15)" : "var(--border-subtle)"}`,
                      fontSize: "11px", fontFamily: "IBM Plex Mono, monospace",
                      color: active ? "var(--accent-teal)" : "var(--text-muted)",
                      opacity: active ? 1 : 0.4,
                    }}>
                      {cap.icon} {cap.label}
                    </span>
                  );
                })}
              </div>
            </div>

            {/* ── Network Identity ── */}
            <div className="identity-block" style={{ marginBottom: "16px", padding: "20px" }}>
              <p className="section-label" style={{ marginBottom: "14px" }}>NETWORK IDENTITY</p>
              <div style={{ marginBottom: "14px" }}>
                <p style={labelStyle}>Agent ID</p>
                <div className="did-string">{persona.agent_id}</div>
              </div>
              <div>
                <p style={labelStyle}>Public Webhook Endpoint</p>
                <div className="did-string">{persona.webhook_url}</div>
              </div>
            </div>

            {/* ── Actions ── */}
            <div style={{ display: "flex", gap: "10px" }}>
              <button onClick={() => setEditing(true)} className="btn-primary" style={{ flex: 1, padding: "14px", fontSize: "14px" }}>
                Edit Profile
              </button>
              <button onClick={() => router.push("/dashboard/chat")} className="btn-secondary" style={{ flex: 1, padding: "14px", fontSize: "14px" }}>
                Go to AI Chat →
              </button>
            </div>

            {/* ── Danger Zone ── */}
            <div
              style={{
                marginTop: "32px",
                padding: "20px",
                borderRadius: "var(--r-md)",
                background: "rgba(255, 95, 109, 0.03)",
                border: "1px solid rgba(255, 95, 109, 0.20)",
              }}
            >
              <p
                className="section-label"
                style={{ color: "var(--accent-coral)", marginBottom: "10px" }}
              >
                DANGER ZONE
              </p>
              <p
                style={{
                  fontFamily: "DM Sans, sans-serif",
                  fontSize: "12px",
                  color: "var(--text-secondary)",
                  lineHeight: 1.6,
                  marginBottom: "14px",
                }}
              >
                Deleting your account removes your persona from the Zynd Network, wipes
                all your conversations and meeting tickets, disconnects all linked
                accounts (Google, LinkedIn, etc.), and removes your login. You can sign
                back in afterwards with the same Google/LinkedIn account to start fresh
                with a new identity.
              </p>
              <button
                onClick={() => setDeleteOpen(true)}
                className="btn-danger"
                style={{
                  padding: "10px 18px",
                  fontSize: "12px",
                }}
              >
                Delete My Account
              </button>
            </div>
          </div>
        </div>

        {/* ── Delete confirmation modal ── */}
        {deleteOpen && (
          <DeleteAccountModal
            userId={userId}
            personaName={persona.name}
            onCancel={() => {
              setDeleteOpen(false);
              setDeleteError(null);
            }}
            deleting={deleting}
            error={deleteError}
            onConfirm={handleDeleteAccount}
          />
        )}
      </div>
    );
  }

  // ── CREATE / EDIT FORM ────────────────────────────────────────────
  const isEditMode = persona && editing;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-base)" }}>
      <div className="topbar" style={{ flexDirection: "column", alignItems: "flex-start", justifyContent: "center", height: "auto", padding: "20px 24px" }}>
        <h1 style={{ fontFamily: "Syne, sans-serif", fontSize: "18px", fontWeight: 700, marginBottom: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ color: "var(--accent-purple)" }}>◎</span> {isEditMode ? "Edit Profile" : "Identity Builder"}
        </h1>
        <p className="section-label">{isEditMode ? "UPDATE YOUR AGENT PROFILE" : "CONFIGURE YOUR AUTONOMOUS AI AGENT"}</p>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        <div style={{ maxWidth: "640px", margin: "0 auto" }}>
          {!isEditMode && (
            <p style={{ color: "var(--text-secondary)", fontSize: "14px", lineHeight: 1.65, marginBottom: "28px" }}>
              Design the autonomous AI agent that represents <span style={{ color: "var(--text-primary)", fontWeight: 500 }}>you</span> on the network.
            </p>
          )}

          <form onSubmit={isEditMode ? (e) => { e.preventDefault(); handleSaveProfile(); } : handleDeploy}>
            {error && (
              <div style={{ background: "rgba(255, 95, 109, 0.08)", border: "1px solid rgba(255, 95, 109, 0.20)", padding: "12px 16px", borderRadius: "var(--r-md)", marginBottom: "20px", color: "var(--accent-coral)", fontSize: "13px" }}>
                {error}
              </div>
            )}

            {/* Name (principal — what the network sees) */}
            <FieldLabel label="Your Name (visible on the network)" />
            <input type="text" className="input" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder="e.g. Dillu" style={{ marginBottom: "6px" }} />
            <p style={{ marginTop: 0, marginBottom: "20px", fontFamily: "IBM Plex Mono, monospace", fontSize: "10px", color: "var(--text-muted)", lineHeight: 1.5 }}>
              * This is your name as a person on the Zynd Network. Other agents discover you under this name.
            </p>

            {/* Agent handle (optional internal nickname) */}
            <FieldLabel label="Agent Nickname (optional)" />
            <input type="text" className="input" value={formData.agent_handle} onChange={(e) => setFormData({ ...formData, agent_handle: e.target.value })} placeholder="e.g. Aria — leave blank if you don't want a separate name" style={{ marginBottom: "6px" }} />
            <p style={{ marginTop: 0, marginBottom: "20px", fontFamily: "IBM Plex Mono, monospace", fontSize: "10px", color: "var(--text-muted)", lineHeight: 1.5 }}>
              * Optional name for the AI agent itself, so it can introduce itself as e.g. "I'm Aria, the AI agent representing Dillu". Never advertised on the network — stays in your account only.
            </p>

            {/* Description */}
            <FieldLabel label="Operational Parameters (System Prompt)" />
            <textarea className="input" value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} placeholder="Describe what your agent is allowed to do..." style={{ height: "100px", resize: "none", lineHeight: 1.6, marginBottom: "20px" }} />

            {/* Profile Section */}
            <p className="section-label" style={{ marginBottom: "14px", marginTop: "8px" }}>PROFILE DETAILS (OPTIONAL)</p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "20px" }}>
              <div>
                <FieldLabel label="Title / Role" />
                <input type="text" className="input" value={profile.title} onChange={(e) => setProfile({ ...profile, title: e.target.value })} placeholder="e.g. AI Researcher" />
              </div>
              <div>
                <FieldLabel label="Organization" />
                <input type="text" className="input" value={profile.organization} onChange={(e) => setProfile({ ...profile, organization: e.target.value })} placeholder="e.g. Zynd Labs" />
              </div>
              <div>
                <FieldLabel label="Location" />
                <input type="text" className="input" value={profile.location} onChange={(e) => setProfile({ ...profile, location: e.target.value })} placeholder="e.g. San Francisco, CA" />
              </div>
              <div>
                <FieldLabel label="Interests (comma-separated)" />
                <input type="text" className="input" value={profile.interests} onChange={(e) => setProfile({ ...profile, interests: e.target.value })} placeholder="e.g. AI, Blockchain, Music" />
              </div>
            </div>

            <p className="section-label" style={{ marginBottom: "14px" }}>SOCIAL LINKS (OPTIONAL)</p>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "24px" }}>
              <div>
                <FieldLabel label="X / Twitter" />
                <input type="text" className="input" value={profile.twitter} onChange={(e) => setProfile({ ...profile, twitter: e.target.value })} placeholder="@username" />
              </div>
              <div>
                <FieldLabel label="LinkedIn" />
                <input type="text" className="input" value={profile.linkedin} onChange={(e) => setProfile({ ...profile, linkedin: e.target.value })} placeholder="username or URL" />
              </div>
              <div>
                <FieldLabel label="GitHub" />
                <input type="text" className="input" value={profile.github} onChange={(e) => setProfile({ ...profile, github: e.target.value })} placeholder="username" />
              </div>
              <div>
                <FieldLabel label="Website" />
                <input type="text" className="input" value={profile.website} onChange={(e) => setProfile({ ...profile, website: e.target.value })} placeholder="https://..." />
              </div>
            </div>

            {/* Capabilities */}
            <p className="section-label" style={{ marginBottom: "14px" }}>GRANTED NETWORK CAPABILITIES</p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "12px" }}>
              {ALL_CAPABILITIES.map((cap) => {
                const active = capabilities.includes(cap.id);
                return (
                  <div key={cap.id} onClick={() => handleToggleCapability(cap.id)}
                    style={{ padding: "14px", borderRadius: "var(--r-md)", cursor: "pointer", background: active ? "rgba(0, 212, 180, 0.08)" : "var(--bg-surface)", border: active ? "1px solid rgba(0, 212, 180, 0.25)" : "1px solid var(--border-default)", transition: "all 0.15s ease", display: "flex", alignItems: "center", gap: "10px" }}>
                    <div style={{ width: "18px", height: "18px", borderRadius: "4px", background: active ? "var(--accent-teal)" : "transparent", border: active ? "none" : "1.5px solid var(--text-muted)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      {active && <span style={{ color: "var(--bg-void)", fontSize: "11px", fontWeight: "bold" }}>✓</span>}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "12px", color: active ? "var(--accent-teal)" : "var(--text-muted)" }}>{cap.icon}</span>
                      <span style={{ fontSize: "12px", fontFamily: "DM Sans, sans-serif", color: active ? "var(--text-primary)" : "var(--text-secondary)" }}>{cap.label}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <p style={{ marginTop: "4px", marginBottom: "24px", fontFamily: "IBM Plex Mono, monospace", fontSize: "10px", color: "var(--text-muted)", lineHeight: 1.5 }}>
              * Even if granted here, the agent can only perform these actions if you have linked the respective accounts in the Connections tab.
            </p>

            {/* Submit */}
            <button type="submit" className="btn-primary" disabled={loading} style={{ width: "100%", padding: "14px", fontSize: "14px", fontWeight: 600 }}>
              {loading ? (
                <span style={{ display: "flex", alignItems: "center", gap: "8px" }}><span className="status-dot" /> {isEditMode ? "Saving..." : "Provisioning Identity..."}</span>
              ) : (
                isEditMode ? "Save Changes" : "Deploy Persona to Zynd Network"
              )}
            </button>
            {isEditMode && (
              <button type="button" onClick={() => setEditing(false)} className="btn-secondary" style={{ width: "100%", marginTop: "10px" }}>
                Cancel
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}

function FieldLabel({ label }: { label: string }) {
  return (
    <label style={{ display: "block", marginBottom: "6px", fontFamily: "DM Sans, sans-serif", fontSize: "13px", fontWeight: 500, color: "var(--text-secondary)" }}>
      {label}
    </label>
  );
}


// ── Delete account confirmation modal ─────────────────────────────
//
// The user has to type the persona name EXACTLY to enable the button —
// this is the friction that prevents accidental nukes. List out every
// category of data that's about to be wiped so nothing is a surprise.

function DeleteAccountModal({
  userId,
  personaName,
  deleting,
  error,
  onCancel,
  onConfirm,
}: {
  userId: string;
  personaName: string;
  deleting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const [typed, setTyped] = useState("");
  const canConfirm = typed.trim() === personaName && !deleting;

  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.65)",
        zIndex: 500,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "480px",
          maxWidth: "95vw",
          maxHeight: "90vh",
          background: "var(--bg-base)",
          border: "1px solid rgba(255, 95, 109, 0.35)",
          borderRadius: "var(--r-md)",
          boxShadow: "0 16px 48px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "22px 24px 16px",
            borderBottom: "1px solid var(--border-subtle)",
          }}
        >
          <p
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "16px",
              fontWeight: 700,
              color: "var(--accent-coral)",
            }}
          >
            ⚠ Delete your account
          </p>
          <p
            style={{
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "9px",
              color: "var(--text-muted)",
              letterSpacing: "0.5px",
              textTransform: "uppercase",
              marginTop: "3px",
            }}
          >
            IRREVERSIBLE · USER {userId.slice(0, 8)}
          </p>
        </div>

        <div style={{ padding: "18px 24px", overflowY: "auto" }}>
          <p
            style={{
              fontFamily: "DM Sans, sans-serif",
              fontSize: "13px",
              color: "var(--text-secondary)",
              lineHeight: 1.6,
              marginBottom: "14px",
            }}
          >
            This will permanently delete:
          </p>
          <ul
            style={{
              fontFamily: "DM Sans, sans-serif",
              fontSize: "12px",
              color: "var(--text-secondary)",
              lineHeight: 1.8,
              paddingLeft: "18px",
              marginBottom: "18px",
            }}
          >
            <li>
              Your persona <strong>{personaName}</strong> — deregistered from the Zynd Network
            </li>
            <li>All DM conversations and message history</li>
            <li>All pending and scheduled meeting tickets</li>
            <li>Linked accounts (Google, LinkedIn, Notion, Twitter, etc.)</li>
            <li>Chat history with your AI agent</li>
            <li>Your Zynd login itself</li>
          </ul>
          <p
            style={{
              fontFamily: "DM Sans, sans-serif",
              fontSize: "12px",
              color: "var(--text-muted)",
              lineHeight: 1.6,
              marginBottom: "18px",
              fontStyle: "italic",
            }}
          >
            You can sign back in afterwards with the same Google/LinkedIn account to
            start fresh. Your new identity will have a different agent ID — people
            connected to your old persona will need to reconnect.
          </p>

          <FieldLabel label={`Type "${personaName}" to confirm`} />
          <input
            type="text"
            className="input"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={personaName}
            autoFocus
            disabled={deleting}
          />

          {error && (
            <p
              style={{
                marginTop: "12px",
                padding: "8px 12px",
                fontFamily: "DM Sans, sans-serif",
                fontSize: "12px",
                color: "var(--accent-coral)",
                background: "rgba(255, 95, 109, 0.08)",
                border: "1px solid rgba(255, 95, 109, 0.25)",
                borderRadius: "var(--r-sm)",
              }}
            >
              ⚠ {error}
            </p>
          )}
        </div>

        <div
          style={{
            padding: "16px 24px 20px",
            borderTop: "1px solid var(--border-subtle)",
            display: "flex",
            gap: "10px",
            justifyContent: "flex-end",
          }}
        >
          <button
            onClick={onCancel}
            disabled={deleting}
            className="btn-secondary"
            style={{ padding: "10px 18px", fontSize: "12px" }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={!canConfirm}
            className="btn-danger"
            style={{
              padding: "10px 18px",
              fontSize: "12px",
              opacity: canConfirm ? 1 : 0.5,
            }}
          >
            {deleting ? "Deleting…" : "Delete Account"}
          </button>
        </div>
      </div>
    </div>
  );
}
