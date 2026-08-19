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

function Logo({ client }: { client: Client }) {
  const [err, setErr] = useState(false);
  if (!client.logoUrl || err) {
    return <span style={{ ...logoFallback, background: client.color }}>{client.initial}</span>;
  }
  return (
    <img
      src={client.logoUrl}
      alt=""
      width={24}
      height={24}
      style={logoImg}
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
    name: "Cline / Continue",
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

  // 3-step clients: code block in middle step (index 1). 1–2 step: first step (index 0).
  const codeStepIndex = active.steps.length === 3 ? 1 : 0;

  const codeBlock = (
    <div style={codeWrap}>
      <div style={codeBar}>
        <span style={codeTag}>{active.label}</span>
        <button style={copyBtn} onClick={copy}>{copied ? "✓ Copied" : "Copy"}</button>
      </div>
      <pre style={pre}>{snippet}</pre>
    </div>
  );

  return (
    <div style={page}>
      <div style={pageHead}>
        <h1 style={h1}>Connect your AI tool</h1>
        <p style={sub}>Pick your tool. Your token is pre-filled.</p>
      </div>

      {status === "loading" && (
        <div style={stateCard}>
          <span style={{ color: "var(--ink-muted)", fontSize: 13 }}>Creating your connection…</span>
        </div>
      )}

      {status === "error" && (
        <div style={stateCard}>
          <p style={{ color: "var(--danger)", fontSize: 13, marginBottom: 12 }}>{error}</p>
          <button style={btnPrimary} onClick={() => setReload((k) => k + 1)}>Retry</button>
        </div>
      )}

      {status === "ready" && result && (
        <div style={split}>
          {/* Tool list */}
          <nav style={sidebar}>
            {CLIENTS.map((c) => (
              <button
                key={c.id}
                style={activeId === c.id ? sideItemOn : sideItemOff}
                onClick={() => { setActiveId(c.id); setCopied(false); }}
              >
                <Logo client={c} />
                <span style={sideLabel}>{c.name}</span>
              </button>
            ))}
          </nav>

          {/* Steps panel */}
          <div style={panel}>
            <div style={emailRow}>
              <span style={emailBadge}>{result.email}</span>
            </div>

            <div style={stepsCol}>
              {active.steps.map((text, i) => (
                <div key={i} style={stepRow}>
                  <div style={stepNum}>{i + 1}</div>
                  <div style={{ flex: 1 }}>
                    <p style={stepText}>{text}</p>
                    {i === codeStepIndex && codeBlock}
                  </div>
                </div>
              ))}
            </div>

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
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Styles ── */
const page: CSSProperties = { maxWidth: 860, margin: "0 auto", padding: "28px 20px 48px" };
const pageHead: CSSProperties = { marginBottom: 24 };
const h1: CSSProperties = { fontSize: 20, fontWeight: 600, color: "var(--ink)", margin: "0 0 4px" };
const sub: CSSProperties = { fontSize: 13, color: "var(--ink-muted)", margin: 0 };

const stateCard: CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-lg)",
  padding: 20,
};

const split: CSSProperties = { display: "flex", gap: 16, alignItems: "flex-start" };

const sidebar: CSSProperties = {
  width: 188,
  flexShrink: 0,
  display: "flex",
  flexDirection: "column",
  gap: 1,
};

const sideBase: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "8px 10px",
  borderRadius: "var(--r-md)",
  border: "1px solid transparent",
  cursor: "pointer",
  textAlign: "left",
  width: "100%",
  background: "transparent",
  transition: "background 120ms",
};
const sideItemOff: CSSProperties = { ...sideBase };
const sideItemOn: CSSProperties = {
  ...sideBase,
  background: "var(--accent-soft-bg)",
  borderColor: "var(--border-strong)",
};

const sideLabel: CSSProperties = { fontSize: 13, fontWeight: 500, color: "var(--ink)", lineHeight: 1.3 };

const logoFallback: CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: 6,
  display: "flex" as const,
  alignItems: "center",
  justifyContent: "center",
  color: "#fff",
  fontSize: 11,
  fontWeight: 700,
  flexShrink: 0,
};
const logoImg: CSSProperties = { width: 24, height: 24, borderRadius: 6, objectFit: "contain", flexShrink: 0 };

const panel: CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: "var(--surface)",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-lg)",
  padding: 20,
  boxShadow: "var(--shadow-card)",
};

const emailRow: CSSProperties = { display: "flex", justifyContent: "flex-end", marginBottom: 18 };
const emailBadge: CSSProperties = {
  fontSize: 11,
  color: "var(--ink-muted)",
  background: "var(--surface-raised)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--r-sm)",
  padding: "2px 8px",
};

const stepsCol: CSSProperties = { display: "flex", flexDirection: "column" };
const stepRow: CSSProperties = { display: "flex", gap: 14, paddingBottom: 20 };
const stepNum: CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: "50%",
  border: "1px solid var(--border-default)",
  background: "var(--surface-raised)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 11,
  fontWeight: 600,
  color: "var(--ink-muted)",
  flexShrink: 0,
  marginTop: 1,
};
const stepText: CSSProperties = { fontSize: 13.5, color: "var(--ink-secondary)", margin: 0, lineHeight: 1.55 };

const codeWrap: CSSProperties = {
  marginTop: 10,
  borderRadius: "var(--r-md)",
  overflow: "hidden",
  border: "1px solid var(--border-default)",
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
  letterSpacing: "0.03em",
};
const copyBtn: CSSProperties = {
  background: "none",
  border: "1px solid var(--border-default)",
  borderRadius: "var(--r-sm)",
  cursor: "pointer",
  padding: "2px 9px",
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
  marginTop: 8,
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
const featGrid: CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px 20px" };
const featItem: CSSProperties = { fontSize: 12.5, color: "var(--ink-secondary)", display: "flex", alignItems: "center", gap: 6 };
const check: CSSProperties = { color: "var(--accent)", fontSize: 12, fontWeight: 700 };

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
