"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { getSupabase } from "@/lib/supabase";

const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

type Exchange = { token: string; mcp_url: string; email: string };
type Status = "loading" | "ready" | "error";
type ClientId = "claudecode" | "claudedesktop" | "opencode" | "openclaw" | "cursor" | "windsurf" | "cline" | "hermes";

interface Client {
  id: ClientId;
  name: string;
  label: string;
  steps: string[];
  snippet: (token: string, url: string) => string;
}

const mcpRemoteBlock = (token: string, url: string) =>
  JSON.stringify(
    {
      mcpServers: {
        zynd: {
          command: "npx",
          args: ["-y", "mcp-remote", url, "--header", `Authorization: Bearer ${token}`],
        },
      },
    },
    null,
    2,
  );

const CLIENTS: Client[] = [
  {
    id: "claudecode",
    name: "Claude Code",
    label: "terminal",
    steps: ["Run this in your terminal — your token is pre-filled.", "Verify: type /mcp — ZYND should appear."],
    snippet: (token, url) =>
      `claude mcp add --scope user --transport http zynd ${url} --header "Authorization: Bearer ${token}"`,
  },
  {
    id: "claudedesktop",
    name: "Claude Desktop",
    label: "url",
    steps: [
      "Open Settings → Connectors.",
      "Click Add custom connector and paste this URL.",
      "A browser window will open — sign in to authorize.",
    ],
    snippet: (_token, url) => url,
  },
  {
    id: "opencode",
    name: "OpenCode",
    label: "prompt",
    steps: ["Paste this prompt into OpenCode. The AI configures itself — no file editing needed."],
    snippet: (token, url) =>
      `Add a new MCP server called "zynd" with transport type HTTP.\nUse the URL ${url} and add the header\n"Authorization: Bearer ${token}".`,
  },
  {
    id: "openclaw",
    name: "OpenClaw",
    label: "prompt",
    steps: ["Paste this prompt into OpenClaw. The AI configures itself — no file editing needed."],
    snippet: (token, url) =>
      `Add a new MCP server called "zynd" with transport type HTTP.\nUse the URL ${url} and add the header\n"Authorization: Bearer ${token}".`,
  },
  {
    id: "hermes",
    name: "Hermes",
    label: "url",
    steps: [
      "Open Hermes settings → Integrations.",
      "Add a new MCP server and paste this URL.",
      "A browser window will open — sign in to authorize.",
    ],
    snippet: (_token, url) => url,
  },
  {
    id: "cursor",
    name: "Cursor",
    label: "~/.cursor/mcp.json",
    steps: ["Open Settings → MCP → Add new global MCP server.", "Paste this into the config file that opens.", "Restart Cursor."],
    snippet: mcpRemoteBlock,
  },
  {
    id: "windsurf",
    name: "Windsurf",
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
    label: "cline_mcp_settings.json",
    steps: ["In Cline, click the MCP icon in the sidebar → Edit MCP Settings.", 'Merge this into the "mcpServers" object.', "Restart your editor."],
    snippet: mcpRemoteBlock,
  },
];

export default function ConnectPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState<Exchange | null>(null);
  const [error, setError] = useState("");
  const [activeId, setActiveId] = useState<ClientId>("claudecode");
  const [copied, setCopied] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setStatus("loading");
      setError("");
      try {
        const {
          data: { session },
        } = await getSupabase().auth.getSession();
        const token = session?.access_token;
        if (!token) throw new Error("Not signed in — reload the page.");
        const res = await fetch(`${MEMORY_API}/token/exchange`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`Couldn't create your token (${res.status}). Try again.`);
        const data = (await res.json()) as Exchange;
        if (!cancelled) {
          setResult(data);
          setStatus("ready");
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Something went wrong.");
          setStatus("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const active = CLIENTS.find((c) => c.id === activeId)!;
  const snippet = result ? active.snippet(result.token, result.mcp_url) : "";

  const copy = () => {
    navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // 3-step clients (Desktop/Cursor/Windsurf/Cline): code block goes in middle step (index 1).
  // 1- or 2-step clients (OpenCode/Claude Code): code block goes in first step (index 0).
  const codeStepIndex = active.steps.length === 3 ? 1 : 0;

  const codeBlock = (
    <div style={{ marginTop: 10 }}>
      <div style={codeHeader}>
        <span style={codeLabel}>{active.label}</span>
        <button style={copyBtn} onClick={copy}>
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre style={pre}>{snippet}</pre>
    </div>
  );

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", padding: "32px 20px" }}>
      <h1 style={h1}>Connect your AI tool</h1>
      <p style={subtitle}>
        Pick your tool. Your token is pre-filled.
      </p>

      {status === "loading" && (
        <div style={card}>
          <span style={{ color: "var(--ink-secondary)", fontSize: 14 }}>Creating your connection…</span>
        </div>
      )}

      {status === "error" && (
        <div style={card}>
          <p style={{ color: "var(--danger)", margin: "0 0 12px", fontSize: 14 }}>{error}</p>
          <button style={btnPrimary} onClick={() => setReload((k) => k + 1)}>
            Retry
          </button>
        </div>
      )}

      {status === "ready" && result && (
        <>
          {/* Client tabs */}
          <div style={tabBar}>
            {CLIENTS.map((c) => (
              <button
                key={c.id}
                style={activeId === c.id ? tabActive : tab}
                onClick={() => {
                  setActiveId(c.id);
                  setCopied(false);
                }}
              >
                {c.name}
              </button>
            ))}
          </div>

          {/* Steps */}
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
              <span style={emailBadge}>{result.email}</span>
            </div>
            <div style={stepsContainer}>
              {active.steps.map((text, i) => (
                <div key={i} style={stepRow}>
                  <div style={stepNum}>{i + 1}</div>
                  <div style={{ flex: 1 }}>
                    <p style={stepText_}>{text}</p>
                    {i === codeStepIndex && codeBlock}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* What you get */}
          <div style={{ ...card, marginTop: 12 }}>
            <p style={sectionLabel}>What ZYND gives your AI</p>
            <div style={featureGrid}>
              {[
                "Persistent memory across all your tools",
                "Google Calendar & Gmail",
                "LinkedIn search & profile",
                "Notion read & write",
                "Publish live web pages",
                "ZYND network — find & connect people",
              ].map((f) => (
                <div key={f} style={featureItem}>
                  <span style={{ color: "var(--accent)", marginRight: 6 }}>✓</span>
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

/* ── styles ── */
const h1: CSSProperties = { fontSize: 22, fontWeight: 700, color: "var(--ink)", margin: "0 0 6px" };
const subtitle: CSSProperties = { fontSize: 14, color: "var(--ink-secondary)", margin: "0 0 24px", lineHeight: 1.6 };

const tabBar: CSSProperties = { display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 };
const tabBase: CSSProperties = {
  padding: "7px 14px",
  borderRadius: 8,
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  border: "1px solid var(--border-default)",
  background: "transparent",
  color: "var(--ink-secondary)",
  transition: "all 0.1s",
};
const tab: CSSProperties = { ...tabBase };
const tabActive: CSSProperties = { ...tabBase, background: "var(--accent)", color: "#fff", border: "1px solid var(--accent)" };

const card: CSSProperties = {
  background: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: 14,
  padding: 20,
};

const emailBadge: CSSProperties = {
  fontSize: 12,
  color: "var(--ink-secondary)",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "2px 8px",
};

const stepsContainer: CSSProperties = { display: "flex", flexDirection: "column", gap: 0 };
const stepRow: CSSProperties = { display: "flex", gap: 14, paddingBottom: 20 };
const stepNum: CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: "50%",
  border: "1px solid var(--border-default)",
  background: "var(--bg-void)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 12,
  fontWeight: 600,
  color: "var(--ink-secondary)",
  flexShrink: 0,
  marginTop: 1,
};
const stepText_: CSSProperties = { fontSize: 14, color: "var(--ink-secondary)", margin: 0, lineHeight: 1.6 };

const codeHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "6px 12px",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderBottom: "none",
  borderRadius: "8px 8px 0 0",
};
const codeLabel: CSSProperties = {
  fontFamily: "ui-monospace, Menlo, monospace",
  fontSize: 11,
  color: "var(--ink-muted)",
};
const copyBtn: CSSProperties = {
  background: "none",
  border: "1px solid var(--border-default)",
  borderRadius: 6,
  cursor: "pointer",
  padding: "3px 10px",
  color: "var(--ink-muted)",
  fontSize: 12,
};
const pre: CSSProperties = {
  margin: 0,
  padding: "14px 16px",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "0 0 8px 8px",
  fontFamily: "ui-monospace, Menlo, monospace",
  fontSize: 12,
  color: "var(--ink)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  lineHeight: 1.7,
};

const btnPrimary: CSSProperties = {
  background: "var(--accent)",
  color: "#fff",
  border: 0,
  borderRadius: 8,
  padding: "7px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};
const sectionLabel: CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: "var(--ink-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  margin: "0 0 12px",
};
const featureGrid: CSSProperties = { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px" };
const featureItem: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", display: "flex", alignItems: "center" };
