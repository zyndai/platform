"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { getSupabase } from "@/lib/supabase";

const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

type Exchange = { token: string; mcp_url: string; email: string };
type Status = "loading" | "ready" | "error";
type ClientId = "claudedesktop" | "claudecode" | "cursor" | "windsurf" | "cline" | "codex" | "opencode" | "openclaw" | "hermes";

interface Step { title: string; desc: string; }

interface AltMethod {
  label: string;
  steps: Step[];
  snippetStep: number;
  snippetLabel: string;
  snippet: (token: string, url: string) => string;
}

interface Client {
  id: ClientId;
  name: string;
  logoUrl: string;
  color: string;
  initial: string;
  steps: Step[];
  snippetStep: number;
  snippetLabel: string;
  snippet: (token: string, url: string) => string;
  altMethod?: AltMethod;
}

function Logo({ client, size = 18 }: { client: Client; size?: number }) {
  const [err, setErr] = useState(false);
  const box: CSSProperties = {
    width: size, height: size, borderRadius: Math.round(size * 0.25),
    flexShrink: 0, display: "inline-flex", alignItems: "center",
    justifyContent: "center", background: client.color,
    color: "#fff", fontSize: Math.round(size * 0.45), fontWeight: 700,
  };
  if (!client.logoUrl || err) return <span style={box}>{client.initial}</span>;
  return (
    <img src={client.logoUrl} alt="" width={size} height={size}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.25), objectFit: "contain", flexShrink: 0 }}
      onError={() => setErr(true)} />
  );
}

function CopyIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

const mcpRemoteBlock = (token: string, url: string) =>
  JSON.stringify(
    { mcpServers: { zynd: { command: "npx", args: ["-y", "mcp-remote", url, "--header", `Authorization: Bearer ${token}`] } } },
    null, 2,
  );

const CLIENTS: Client[] = [
  {
    id: "claudedesktop",
    name: "Claude Desktop",
    logoUrl: "https://anthropic.gallerycdn.vsassets.io/extensions/anthropic/claude-code/2.1.235/1787085642251/Microsoft.VisualStudio.Services.Icons.Default",
    color: "#C96442", initial: "C",
    snippetStep: 1, snippetLabel: "MCP URL",
    steps: [
      { title: "Open Connectors settings", desc: "In Claude Desktop, go to Settings, then click Connectors." },
      { title: "Add the ZYND MCP server", desc: "Click Add custom connector and paste this URL." },
      { title: "Authorize in your browser", desc: "A browser window will open automatically. Sign in to authorize." },
    ],
    snippet: (_t, url) => url,
  },
  {
    id: "claudecode",
    name: "Claude Code",
    logoUrl: "https://anthropic.gallerycdn.vsassets.io/extensions/anthropic/claude-code/2.1.235/1787085642251/Microsoft.VisualStudio.Services.Icons.Default",
    color: "#C96442", initial: "C",
    snippetStep: 0, snippetLabel: "terminal",
    steps: [
      { title: "Run the setup command", desc: "Run this in your terminal — your token is pre-filled." },
      { title: "Authorize the connection", desc: 'Type /mcp in Claude Code, select "zynd", and complete the sign-in. Required even though the token is pre-filled.' },
      { title: "Be specific when you ask", desc: "Claude Code has its own tools for things like hosting a page — say something like \"publish this as a ZYND page\" so it uses the zynd MCP tool instead of its own (e.g. Vercel)." },
    ],
    snippet: (token, url) => `claude mcp add --scope user --transport http zynd ${url} --header "Authorization: Bearer ${token}"`,
  },
  {
    id: "cursor",
    name: "Cursor",
    logoUrl: "https://cursor.com/favicon.ico",
    color: "#1a1a1a", initial: "C",
    snippetStep: 1, snippetLabel: "~/.cursor/mcp.json",
    steps: [
      { title: "Open MCP settings", desc: "Go to Settings → MCP → Add new global MCP server." },
      { title: "Add the configuration", desc: "Paste this into the config file that opens." },
      { title: "Restart Cursor", desc: "Restart Cursor to activate the new MCP server." },
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "windsurf",
    name: "Windsurf",
    logoUrl: "https://windsurf.com/favicon.ico",
    color: "#00897B", initial: "W",
    snippetStep: 1, snippetLabel: "~/.codeium/windsurf/mcp_config.json",
    steps: [
      { title: "Open MCP settings", desc: "Go to Windsurf Settings → Cascade → MCP Servers → Add Server." },
      { title: "Add the configuration", desc: "Merge this into the config file that opens." },
      { title: "Restart Windsurf", desc: "Restart Windsurf to activate the new MCP server." },
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "cline",
    name: "Cline",
    logoUrl: "https://avatars.githubusercontent.com/u/184127137?v=4",
    color: "#2563EB", initial: "C",
    snippetStep: 1, snippetLabel: "cline_mcp_settings.json",
    steps: [
      { title: "Open MCP settings", desc: "In Cline, click the MCP icon in the sidebar → Edit MCP Settings." },
      { title: "Add the configuration", desc: 'Merge this into the "mcpServers" object.' },
      { title: "Restart your editor", desc: "Restart your editor to activate the new MCP server." },
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "codex",
    name: "Codex",
    logoUrl: "https://openai.com/favicon.ico",
    color: "#10A37F", initial: "C",
    snippetStep: 1, snippetLabel: "~/.codex/config.toml",
    steps: [
      { title: "Open your config file", desc: "Edit ~/.codex/config.toml in your home directory, or .codex/config.toml in your project for a scoped setup." },
      { title: "Add the ZYND server", desc: "Add this block to your config." },
      { title: "Restart Codex", desc: "Restart Codex to pick up the new server." },
    ],
    snippet: (token, url) => `[mcp_servers.zynd]\nurl = "${url}"\nhttp_headers = { "Authorization" = "Bearer ${token}" }`,
    altMethod: {
      label: "Ask Codex to do it",
      steps: [
        { title: "Paste this into Codex's chat", desc: "Codex can edit its own config file — paste this and it'll make the edit for you." },
        { title: "Restart Codex", desc: "Restart Codex to pick up the new server." },
      ],
      snippetStep: 0,
      snippetLabel: "prompt",
      snippet: (token, url) => `Edit my Codex config so the ZYND MCP server is available.\nEdit "~/.codex/config.toml" (or ".codex/config.toml" in this project for a scoped setup), creating the file and any parent directories if they don't exist.\nAdd the following without removing any existing "[mcp_servers.*]" entries:\n\n[mcp_servers.zynd]\nurl = "${url}"\nhttp_headers = { "Authorization" = "Bearer ${token}" }\n\nThen tell me to restart Codex to pick up the new server.`,
    },
  },
  {
    id: "opencode",
    name: "OpenCode",
    logoUrl: "https://opencode.ai/favicon.ico",
    color: "#EA580C", initial: "O",
    snippetStep: 1, snippetLabel: "opencode.json",
    steps: [
      { title: "Open your config file", desc: "Edit opencode.json in your project root, or ~/.config/opencode/config.json for global setup." },
      { title: "Add the ZYND server", desc: 'Merge this into the "mcp" section of your config.' },
      { title: "Restart OpenCode", desc: "Restart OpenCode to pick up the new server." },
    ],
    snippet: (token, url) => JSON.stringify({ mcp: { zynd: { command: "npx", args: ["-y", "mcp-remote", url, "--header", `Authorization: Bearer ${token}`] } } }, null, 2),
    altMethod: {
      label: "Ask OpenCode to do it",
      steps: [
        { title: "Paste this into OpenCode's chat", desc: "OpenCode can edit its own config file — paste this and it'll make the edit for you." },
        { title: "Restart OpenCode", desc: "Restart OpenCode to pick up the new server." },
      ],
      snippetStep: 0,
      snippetLabel: "prompt",
      snippet: (token, url) => `Edit my OpenCode config so the ZYND MCP server is available.\nIf "opencode.json" exists in this project root, edit that one; otherwise create or edit "~/.config/opencode/config.json" for a global setup (create the file and any parent directories if they don't exist).\nMerge the following into the "mcp" key without removing any existing entries there (create the "mcp" key if it doesn't exist):\n\n{\n  "zynd": {\n    "command": "npx",\n    "args": ["-y", "mcp-remote", "${url}", "--header", "Authorization: Bearer ${token}"]\n  }\n}\n\nThen tell me to restart OpenCode to pick up the new server.`,
    },
  },
  {
    id: "openclaw",
    name: "OpenClaw",
    logoUrl: "https://openclaw.ai/apple-touch-icon.png",
    color: "#7C3AED", initial: "O",
    snippetStep: 1, snippetLabel: "config.json",
    steps: [
      { title: "Open your MCP config file", desc: "Edit the MCP config file for OpenClaw in your project or home directory." },
      { title: "Add the ZYND server", desc: 'Merge this into the "mcpServers" section of your config.' },
      { title: "Restart OpenClaw", desc: "Restart OpenClaw to pick up the new server." },
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "hermes",
    name: "Hermes",
    logoUrl: "",
    color: "#6366F1", initial: "H",
    snippetStep: 1, snippetLabel: "MCP URL",
    steps: [
      { title: "Open Integrations", desc: "Open Hermes settings → Integrations." },
      { title: "Add the MCP server", desc: "Add a new MCP server and paste this URL." },
      { title: "Authorize in your browser", desc: "A browser window will open automatically. Sign in to authorize." },
    ],
    snippet: (_t, url) => url,
  },
];

const FEATURES = [
  { title: "Persistent memory", desc: "Remembers what you tell it, across every tool." },
  { title: "Google Calendar & Gmail", desc: "Checks your calendar, books meetings, sends email." },
  { title: "LinkedIn search & profiles", desc: "Looks people up on LinkedIn by role or topic." },
  { title: "Notion read & write", desc: "Reads and edits your connected Notion pages." },
  { title: "Publish live web pages", desc: "Turns a chat into a shareable web page." },
  { title: "ZYND network", desc: "Finds people on ZYND — try \"find me a co-founder.\"" },
];

const PRIMARY = CLIENTS.length - 2;

export default function ConnectPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState<Exchange | null>(null);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<ClientId>("claudedesktop");
  const [copied, setCopied] = useState(false);
  const [reload, setReload] = useState(0);
  const [showMore, setShowMore] = useState(false);
  const [useAlt, setUseAlt] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setShowMore(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setStatus("loading");
      setError("");
      try {
        const { data: { session } } = await getSupabase().auth.getSession();
        const token = session?.access_token;
        if (!token) throw new Error("Not signed in — reload the page.");
        const res = await fetch(`${MEMORY_API}/token/exchange`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`Couldn't create your token (${res.status}). Try again.`);
        const data = (await res.json()) as Exchange;
        if (!cancelled) { setResult(data); setStatus("ready"); }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Something went wrong.");
          setStatus("error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [reload]);

  const active = CLIENTS.find((c) => c.id === activeId)!;
  const method: Client | AltMethod = useAlt && active.altMethod ? active.altMethod : active;
  const snippet = result ? method.snippet(result.token, result.mcp_url) : "";
  const primaryClients = CLIENTS.slice(0, PRIMARY);
  const moreClients = CLIENTS.slice(PRIMARY);
  const activeInMore = moreClients.some((c) => c.id === activeId);

  const select = (id: ClientId) => { setActiveId(id); setCopied(false); setShowMore(false); setUseAlt(false); };

  const copy = () => {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={page}>
      <p style={eyebrow}>To get started, pick your client below.</p>

      {/* ── Tab bar ── */}
      <div style={tabBar}>
        <div style={tabsInner}>
          {primaryClients.map((c) => (
            <button key={c.id} style={activeId === c.id ? tabOn : tabOff} onClick={() => select(c.id)}>
              <Logo client={c} size={20} />
              <span>{c.name}</span>
            </button>
          ))}
        </div>

        {moreClients.length > 0 && (
          <div ref={moreRef} style={{ position: "relative", flexShrink: 0 }}>
            <button
              style={activeInMore ? { ...moreBtn, fontWeight: 600, color: "var(--ink)" } : moreBtn}
              onClick={() => setShowMore((s) => !s)}
            >
              {activeInMore ? active.name : "More clients"}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: 4 }}>
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
            {showMore && (
              <div style={dropdown}>
                {moreClients.map((c) => (
                  <button key={c.id} style={activeId === c.id ? dropOn : dropOff} onClick={() => select(c.id)}>
                    <Logo client={c} size={16} />
                    <span>{c.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Status ── */}
      {status === "loading" && (
        <p style={{ fontSize: 13, color: "var(--ink-muted)", marginTop: 28 }}>Creating your connection…</p>
      )}
      {status === "error" && (
        <div style={{ marginTop: 28 }}>
          <p style={{ fontSize: 13, color: "var(--danger)", marginBottom: 10 }}>{error}</p>
          <button style={btnPrimary} onClick={() => setReload((k) => k + 1)}>Retry</button>
        </div>
      )}

      {/* ── Content ── */}
      {status === "ready" && result && (
        <div style={split}>
          <div style={mainCol}>
            <div style={toolHeader}>
              <Logo client={active} size={26} />
              <h2 style={toolName}>{active.name}</h2>
              <span style={emailBadge}>{result.email}</span>
            </div>

            {active.altMethod && (
              <div style={methodToggle}>
                <button style={!useAlt ? methodPillOn : methodPillOff} onClick={() => setUseAlt(false)}>
                  Edit config file
                </button>
                <button style={useAlt ? methodPillOn : methodPillOff} onClick={() => setUseAlt(true)}>
                  {active.altMethod.label}
                </button>
              </div>
            )}

            <div style={stepsWrap}>
              {method.steps.map((step, i) => {
                const isLast = i === method.steps.length - 1;
                return (
                  <div key={i} style={stepOuter}>
                    {/* Left: number + line */}
                    <div style={stepLeft}>
                      <div style={stepNum}>{i + 1}</div>
                      {!isLast && <div style={stepLine} />}
                    </div>

                    {/* Right: content */}
                    <div style={{ flex: 1, paddingBottom: isLast ? 0 : 32 }}>
                      <p style={stepTitle}>{step.title}</p>
                      <p style={stepDesc}>{step.desc}</p>
                      {i === method.snippetStep && (
                        <div style={codeBlock}>
                          <span style={codeLabel}>{method.snippetLabel}</span>
                          <pre style={codeText}>{snippet}</pre>
                          <button style={copyIconBtn} onClick={copy} title="Copy">
                            {copied ? <span style={{ fontSize: 12, color: "var(--accent)" }}>✓</span> : <CopyIcon />}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={tipBox}>
              <p style={tipTitle}>Try it</p>
              <p style={tipText}>
                Once connected, ask your AI to remember something about you, check your calendar, or search
                &ldquo;find me a co-founder&rdquo; to see the ZYND network in action.
              </p>
            </div>
          </div>

          <aside style={sideCol}>
            <p style={featTitle}>What ZYND gives your AI</p>
            <div style={featList}>
              {FEATURES.map((f) => (
                <div key={f.title} style={featItem}>
                  <span style={check}>•</span>
                  <div>
                    <p style={featItemTitle}>{f.title}</p>
                    <p style={featItemDesc}>{f.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

/* ── Styles ── */
const page: CSSProperties = { padding: "32px 40px 56px", maxWidth: 1080, margin: "0 auto" };
const eyebrow: CSSProperties = { fontSize: 14, color: "var(--ink-secondary)", margin: "0 0 16px" };

/* Tab bar */
const tabBar: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-md)",
  padding: "6px 8px",
  marginBottom: 28,
  gap: 8,
};
const tabsInner: CSSProperties = {
  display: "flex", alignItems: "center", gap: 2, flexWrap: "nowrap",
  flex: "1 1 auto", minWidth: 0, overflowX: "auto",
};
const tabBase: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8,
  padding: "8px 12px", borderRadius: "var(--r-sm)",
  border: "none", cursor: "pointer", fontSize: 15, fontWeight: 600,
  whiteSpace: "nowrap", transition: "background 120ms, color 120ms",
  background: "transparent",
};
const tabOff: CSSProperties = { ...tabBase, color: "var(--ink-secondary)" };
const tabOn: CSSProperties = { ...tabBase, color: "var(--ink)", background: "var(--surface)" };

const moreBtn: CSSProperties = {
  ...tabBase, color: "var(--ink-secondary)", fontWeight: 400,
  border: "1px solid var(--border-default)", background: "var(--surface)",
  borderRadius: "var(--r-sm)", padding: "5px 10px",
};

/* Dropdown */
const dropdown: CSSProperties = {
  position: "absolute", top: "calc(100% + 6px)", right: 0,
  background: "var(--surface)", border: "1px solid var(--border-default)",
  borderRadius: "var(--r-md)", boxShadow: "var(--shadow-overlay)",
  padding: "4px", zIndex: 50, minWidth: 160,
};
const dropBase: CSSProperties = {
  display: "flex", alignItems: "center", gap: 8,
  width: "100%", padding: "7px 10px", border: "none",
  borderRadius: "var(--r-sm)", cursor: "pointer", fontSize: 13,
  textAlign: "left", background: "transparent",
};
const dropOff: CSSProperties = { ...dropBase, color: "var(--ink-secondary)" };
const dropOn: CSSProperties = { ...dropBase, color: "var(--ink)", fontWeight: 600, background: "var(--accent-soft-bg)" };

/* Two-column layout */
const split: CSSProperties = { display: "flex", gap: 40, alignItems: "flex-start" };
const mainCol: CSSProperties = { flex: 1, minWidth: 0 };

/* Tool header */
const toolHeader: CSSProperties = { display: "flex", alignItems: "center", gap: 11, marginBottom: 28 };
const toolName: CSSProperties = { fontSize: 18, fontWeight: 700, color: "var(--ink)", margin: 0, flex: 1 };
const emailBadge: CSSProperties = {
  fontSize: 12, color: "var(--ink-muted)",
  background: "var(--surface-raised)", border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-sm)", padding: "3px 9px", whiteSpace: "nowrap",
};

/* Method toggle */
const methodToggle: CSSProperties = {
  display: "flex", gap: 6, marginBottom: 24,
  background: "var(--surface-raised)", border: "1px solid var(--border-default)",
  borderRadius: "var(--r-sm)", padding: 4, width: "fit-content",
};
const methodPillBase: CSSProperties = {
  padding: "6px 12px", borderRadius: "var(--r-sm)", border: "none",
  cursor: "pointer", fontSize: 13, fontWeight: 600, whiteSpace: "nowrap",
  transition: "background 120ms, color 120ms",
};
const methodPillOff: CSSProperties = { ...methodPillBase, color: "var(--ink-secondary)", background: "transparent" };
const methodPillOn: CSSProperties = { ...methodPillBase, color: "var(--ink)", background: "var(--surface)" };

/* Steps */
const stepsWrap: CSSProperties = {};
const stepOuter: CSSProperties = { display: "flex", gap: 18, alignItems: "stretch" };
const stepLeft: CSSProperties = { display: "flex", flexDirection: "column", alignItems: "center", width: 32, flexShrink: 0 };
const stepNum: CSSProperties = {
  width: 32, height: 32, borderRadius: "50%",
  background: "var(--surface-raised)", border: "1px solid var(--border-default)",
  display: "flex", alignItems: "center", justifyContent: "center",
  fontSize: 13, fontWeight: 600, color: "var(--ink-secondary)", flexShrink: 0,
};
const stepLine: CSSProperties = { width: 1, background: "var(--border-default)", flex: 1, minHeight: 16, marginTop: 4 };

const stepTitle: CSSProperties = { fontSize: 14.5, fontWeight: 600, color: "var(--ink)", margin: "4px 0 6px", lineHeight: 1.35, maxWidth: 560 };
const stepDesc: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", margin: "0 0 0", lineHeight: 1.55, maxWidth: 560 };

/* Try-it tip */
const tipBox: CSSProperties = {
  marginTop: 36, padding: "20px 22px", maxWidth: 560,
  background: "var(--surface-raised)", border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-md)",
};
const tipTitle: CSSProperties = { fontSize: 13, fontWeight: 600, color: "var(--ink)", margin: "0 0 7px" };
const tipText: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", margin: 0, lineHeight: 1.6 };

/* Side panel */
const sideCol: CSSProperties = {
  width: 320, flexShrink: 0,
  background: "var(--surface-raised)", border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-lg)", padding: "28px 26px",
  position: "sticky", top: 24,
};
const featTitle: CSSProperties = {
  fontSize: 12, fontWeight: 600, color: "var(--ink-muted)",
  textTransform: "uppercase", letterSpacing: "0.07em", margin: "0 0 24px",
};
const featList: CSSProperties = { display: "flex", flexDirection: "column", gap: 22 };
const featItem: CSSProperties = { display: "flex", alignItems: "flex-start", gap: 11 };
const check: CSSProperties = { color: "var(--accent)", fontSize: 20, lineHeight: 1, fontWeight: 700, flexShrink: 0, marginTop: -1 };
const featItemTitle: CSSProperties = { fontSize: 14.5, fontWeight: 600, color: "var(--ink)", margin: "0 0 4px", lineHeight: 1.3 };
const featItemDesc: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", margin: 0, lineHeight: 1.55 };

/* Code block */
const codeBlock: CSSProperties = {
  marginTop: 12,
  display: "flex", alignItems: "flex-start", gap: 12,
  background: "var(--surface-raised)", border: "1px solid var(--border-default)",
  borderRadius: "var(--r-md)", padding: "12px 14px",
};
const codeLabel: CSSProperties = { display: "none" };
const codeText: CSSProperties = {
  flex: 1, margin: 0, fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
  fontSize: 12.5, color: "var(--ink)", whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.65,
};
const copyIconBtn: CSSProperties = {
  background: "none", border: "none", cursor: "pointer",
  color: "var(--ink-muted)", padding: "2px", flexShrink: 0, marginTop: 1,
  display: "flex", alignItems: "center",
};

const btnPrimary: CSSProperties = {
  background: "var(--accent)", color: "#fff", border: 0,
  borderRadius: "var(--r-md)", padding: "7px 14px",
  fontSize: 13, fontWeight: 600, cursor: "pointer",
};
