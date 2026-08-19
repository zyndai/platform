"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { getSupabase } from "@/lib/supabase";

const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

type Exchange = { token: string; mcp_url: string; email: string };
type Status = "loading" | "ready" | "error";
type ClientId = "claudedesktop" | "claudecode" | "cursor" | "windsurf" | "cline" | "opencode" | "openclaw" | "hermes";

interface Client {
  id: ClientId;
  name: string;
  logoUrl: string;
  color: string;
  initial: string;
  label: string;
  steps: string[];
  snippet: (token: string, url: string) => string;
}

function Logo({ client, size = 28 }: { client: Client; size?: number }) {
  const [err, setErr] = useState(false);
  const box: CSSProperties = {
    width: size,
    height: size,
    borderRadius: 7,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: client.color,
    color: "#fff",
    fontSize: size * 0.45,
    fontWeight: 700,
  };
  if (!client.logoUrl || err) return <span style={box}>{client.initial}</span>;
  return (
    <img
      src={client.logoUrl}
      alt=""
      width={size}
      height={size}
      style={{ width: size, height: size, borderRadius: 7, objectFit: "contain", flexShrink: 0 }}
      onError={() => setErr(true)}
    />
  );
}

const mcpRemoteBlock = (token: string, url: string) =>
  JSON.stringify(
    { mcpServers: { zynd: { command: "npx", args: ["-y", "mcp-remote", url, "--header", `Authorization: Bearer ${token}`] } } },
    null,
    2,
  );

const CLIENTS: Client[] = [
  {
    id: "claudedesktop",
    name: "Claude Desktop",
    logoUrl: "https://claude.ai/favicon.ico",
    color: "#C96442",
    initial: "C",
    label: "MCP URL",
    steps: [
      "Open Settings → Connectors.",
      "Click Add custom connector and paste this URL.",
      "A browser window will open — sign in to authorize.",
    ],
    snippet: (_t, url) => url,
  },
  {
    id: "claudecode",
    name: "Claude Code",
    logoUrl: "https://claude.ai/favicon.ico",
    color: "#C96442",
    initial: "C",
    label: "terminal",
    steps: [
      "Run this in your terminal — your token is pre-filled.",
      "Verify: type /mcp — ZYND should appear.",
    ],
    snippet: (token, url) =>
      `claude mcp add --scope user --transport http zynd ${url} --header "Authorization: Bearer ${token}"`,
  },
  {
    id: "cursor",
    name: "Cursor",
    logoUrl: "https://www.cursor.com/favicon.ico",
    color: "#1a1a1a",
    initial: "C",
    label: "~/.cursor/mcp.json",
    steps: [
      "Open Settings → MCP → Add new global MCP server.",
      "Paste this into the config file that opens.",
      "Restart Cursor.",
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "windsurf",
    name: "Windsurf",
    logoUrl: "https://windsurf.com/favicon.ico",
    color: "#00897B",
    initial: "W",
    label: "~/.codeium/windsurf/mcp_config.json",
    steps: [
      "Go to Windsurf Settings → Cascade → MCP Servers → Add Server.",
      "Merge this into the config file that opens.",
      "Restart Windsurf.",
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "cline",
    name: "Cline",
    logoUrl: "https://cline.bot/favicon.ico",
    color: "#2563EB",
    initial: "C",
    label: "cline_mcp_settings.json",
    steps: [
      "In Cline, click the MCP icon in the sidebar → Edit MCP Settings.",
      'Merge this into the "mcpServers" object.',
      "Restart your editor.",
    ],
    snippet: mcpRemoteBlock,
  },
  {
    id: "opencode",
    name: "OpenCode",
    logoUrl: "https://opencode.ai/favicon.ico",
    color: "#EA580C",
    initial: "O",
    label: "prompt",
    steps: ["Paste this prompt into OpenCode. The AI configures itself — no file editing needed."],
    snippet: (token, url) =>
      `Add a new MCP server called "zynd" with transport type HTTP.\nUse the URL ${url} and add the header\n"Authorization: Bearer ${token}".`,
  },
  {
    id: "openclaw",
    name: "OpenClaw",
    logoUrl: "",
    color: "#7C3AED",
    initial: "O",
    label: "prompt",
    steps: ["Paste this prompt into OpenClaw. The AI configures itself — no file editing needed."],
    snippet: (token, url) =>
      `Add a new MCP server called "zynd" with transport type HTTP.\nUse the URL ${url} and add the header\n"Authorization: Bearer ${token}".`,
  },
  {
    id: "hermes",
    name: "Hermes",
    logoUrl: "",
    color: "#6366F1",
    initial: "H",
    label: "MCP URL",
    steps: [
      "Open Hermes settings → Integrations.",
      "Add a new MCP server and paste this URL.",
      "A browser window will open — sign in to authorize.",
    ],
    snippet: (_t, url) => url,
  },
];

const FEATURES = [
  "Persistent memory across all tools",
  "Google Calendar & Gmail",
  "LinkedIn search & profiles",
  "Notion read & write",
  "Publish live web pages",
  "ZYND network — find people",
];

export default function ConnectPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState<Exchange | null>(null);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<ClientId>("claudedesktop");
  const [copied, setCopied] = useState(false);
  const [reload, setReload] = useState(0);

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
  const snippet = result ? active.snippet(result.token, result.mcp_url) : "";

  const copy = () => {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // 3-step clients: code block goes in middle step (index 1). 1–2 step: first step (index 0).
  const codeStepIndex = active.steps.length === 3 ? 1 : 0;

  return (
    <div style={page}>
      <h1 style={h1}>Connect your AI tool</h1>
      <p style={sub}>Pick your tool. Your token is pre-filled.</p>

      {status === "loading" && (
        <p style={{ fontSize: 13, color: "var(--ink-muted)", marginTop: 20 }}>Creating your connection…</p>
      )}

      {status === "error" && (
        <div style={{ marginTop: 20 }}>
          <p style={{ fontSize: 13, color: "var(--danger)", marginBottom: 10 }}>{error}</p>
          <button style={btnPrimary} onClick={() => setReload((k) => k + 1)}>Retry</button>
        </div>
      )}

      {status === "ready" && result && (
        <>
          {/* Tool selector chips */}
          <div style={chipRow}>
            {CLIENTS.map((c) => (
              <button
                key={c.id}
                style={activeId === c.id ? chipOn : chipOff}
                onClick={() => { setActiveId(c.id); setCopied(false); }}
              >
                {c.name}
              </button>
            ))}
          </div>

          {/* Content card */}
          <div style={card}>
            {/* Card header: logo + tool name + email */}
            <div style={cardHead}>
              <Logo client={active} size={32} />
              <div style={{ flex: 1 }}>
                <p style={toolName}>{active.name}</p>
                <p style={toolLabel}>{active.label}</p>
              </div>
              <span style={emailBadge}>{result.email}</span>
            </div>

            <div style={divider} />

            {/* Steps */}
            {active.steps.map((text, i) => (
              <div key={i} style={stepRow}>
                <span style={stepNum}>{i + 1}</span>
                <div style={{ flex: 1 }}>
                  <p style={stepText}>{text}</p>
                  {i === codeStepIndex && (
                    <div style={codeWrap}>
                      <div style={codeBar}>
                        <span style={codeTag}>{active.label}</span>
                        <button style={copyBtn} onClick={copy}>
                          {copied ? "✓ Copied" : "Copy"}
                        </button>
                      </div>
                      <pre style={pre}>{snippet}</pre>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Features */}
          <div style={featBox}>
            <p style={featTitle}>What ZYND gives your AI</p>
            <div style={featGrid}>
              {FEATURES.map((f) => (
                <div key={f} style={featItem}>
                  <span style={check}>✓</span>
                  {f}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ── Styles ── */
const page: CSSProperties = { maxWidth: 600, padding: "28px 0 48px" };
const h1: CSSProperties = { fontSize: 18, fontWeight: 600, color: "var(--ink)", margin: "0 0 4px" };
const sub: CSSProperties = { fontSize: 13, color: "var(--ink-muted)", margin: "0 0 20px" };

const chipRow: CSSProperties = { display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 };
const chipBase: CSSProperties = {
  padding: "5px 12px",
  borderRadius: 99,
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
  border: "none",
  lineHeight: 1.4,
  transition: "background 120ms, color 120ms",
};
const chipOff: CSSProperties = { ...chipBase, background: "var(--surface-raised)", color: "var(--ink-secondary)" };
const chipOn: CSSProperties = { ...chipBase, background: "var(--accent)", color: "#fff" };

const card: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-lg)",
  padding: "16px 18px",
  boxShadow: "var(--shadow-card)",
  marginBottom: 12,
};

const cardHead: CSSProperties = { display: "flex", alignItems: "center", gap: 12, marginBottom: 14 };
const toolName: CSSProperties = { fontSize: 14, fontWeight: 600, color: "var(--ink)", margin: 0 };
const toolLabel: CSSProperties = { fontSize: 11, color: "var(--ink-muted)", margin: "1px 0 0", fontFamily: "var(--font-geist-mono), ui-monospace, monospace" };
const emailBadge: CSSProperties = {
  fontSize: 11,
  color: "var(--ink-muted)",
  background: "var(--surface-raised)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-sm)",
  padding: "2px 8px",
  whiteSpace: "nowrap",
};

const divider: CSSProperties = { height: 1, background: "var(--border-subtle)", margin: "0 0 16px" };

const stepRow: CSSProperties = { display: "flex", gap: 12, paddingBottom: 16 };
const stepNum: CSSProperties = {
  width: 22,
  height: 22,
  borderRadius: "50%",
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 11,
  fontWeight: 600,
  color: "var(--ink-muted)",
  flexShrink: 0,
  marginTop: 1,
};
const stepText: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", margin: 0, lineHeight: 1.55 };

const codeWrap: CSSProperties = {
  marginTop: 10,
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-md)",
  overflow: "hidden",
};
const codeBar: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "5px 12px",
  background: "var(--surface-raised)",
  borderBottom: "1px solid var(--border-default)",
};
const codeTag: CSSProperties = {
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
  fontSize: 10,
  color: "var(--ink-muted)",
};
const copyBtn: CSSProperties = {
  background: "none",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-xs)",
  cursor: "pointer",
  padding: "2px 8px",
  color: "var(--ink-muted)",
  fontSize: 11,
  fontWeight: 500,
};
const pre: CSSProperties = {
  margin: 0,
  padding: "12px 14px",
  background: "var(--surface)",
  fontFamily: "var(--font-geist-mono), ui-monospace, monospace",
  fontSize: 12,
  color: "var(--ink)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  lineHeight: 1.65,
};

const featBox: CSSProperties = {
  padding: "14px 16px",
  background: "var(--surface-raised)",
  borderRadius: "var(--r-md)",
  border: "1px solid var(--border-subtle)",
};
const featTitle: CSSProperties = {
  fontSize: 10,
  fontWeight: 600,
  color: "var(--ink-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
  margin: "0 0 10px",
};
const featGrid: CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px 16px" };
const featItem: CSSProperties = { fontSize: 12.5, color: "var(--ink-secondary)", display: "flex", alignItems: "center", gap: 6 };
const check: CSSProperties = { color: "var(--accent)", fontWeight: 700, fontSize: 12 };

const btnPrimary: CSSProperties = {
  background: "var(--accent)",
  color: "#fff",
  border: 0,
  borderRadius: "var(--r-md)",
  padding: "7px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};
