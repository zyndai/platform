"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { getSupabase } from "@/lib/supabase";

const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

type Exchange = { token: string; mcp_url: string; email: string };
type Status = "loading" | "ready" | "error";
type ClientId = "claudecode" | "claudedesktop" | "opencode" | "cursor" | "windsurf" | "cline";

interface Client {
  id: ClientId;
  name: string;
  kind: "command" | "json";
  instruction: string;
  snippet: (token: string, url: string) => string;
}

const CLIENTS: Client[] = [
  {
    id: "claudecode",
    name: "Claude Code",
    kind: "command",
    instruction: "Run this in your terminal — one command, done.",
    snippet: (token, url) =>
      `claude mcp add --scope user --transport http zynd ${url} --header "Authorization: Bearer ${token}"`,
  },
  {
    id: "claudedesktop",
    name: "Claude Desktop",
    kind: "json",
    instruction: 'Open Settings → Developer → Edit Config and merge this into the "mcpServers" object.',
    snippet: (token, url) =>
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
      ),
  },
  {
    id: "opencode",
    name: "OpenCode",
    kind: "json",
    instruction: 'Merge this into your ~/.config/opencode/opencode.jsonc under the top-level "mcp" key.',
    snippet: (token, url) =>
      JSON.stringify(
        {
          mcp: {
            zynd: {
              command: "npx",
              args: ["-y", "mcp-remote", url, "--header", `Authorization: Bearer ${token}`],
            },
          },
        },
        null,
        2,
      ),
  },
  {
    id: "cursor",
    name: "Cursor",
    kind: "json",
    instruction: "Open Settings → MCP → Add new global MCP server and paste this.",
    snippet: (token, url) =>
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
      ),
  },
  {
    id: "windsurf",
    name: "Windsurf",
    kind: "json",
    instruction: "Merge this into ~/.codeium/windsurf/mcp_config.json under the mcpServers key.",
    snippet: (token, url) =>
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
      ),
  },
  {
    id: "cline",
    name: "Cline / Continue",
    kind: "json",
    instruction: "Add this to the mcpServers block in your Cline or Continue settings file.",
    snippet: (token, url) =>
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
      ),
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

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 20px" }}>
      <h1 style={h1}>Connect your AI tool</h1>
      <p style={subtitle}>
        Pick your tool below. Your personal token is pre-filled — one copy, one paste.
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

          {/* Snippet card */}
          <div style={card}>
            <div style={metaRow}>
              <span style={label}>{active.kind === "command" ? "Terminal command" : "Config snippet"}</span>
              <span style={emailBadge}>{result.email}</span>
            </div>

            <p style={instruction}>{active.instruction}</p>

            <div style={{ position: "relative" }}>
              <pre style={pre}>{snippet}</pre>
              <button style={{ ...btnPrimary, position: "absolute", top: 10, right: 10 }} onClick={copy}>
                {copied ? "✓ Copied" : "Copy"}
              </button>
            </div>

            {active.kind === "command" && (
              <p style={hint}>
                Then type <code style={code}>/mcp</code> in Claude Code to confirm ZYND appears.
              </p>
            )}
            {active.kind === "json" && (
              <p style={hint}>Restart the app after saving. Your token never expires.</p>
            )}
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

const tabBar: CSSProperties = {
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
  marginBottom: 12,
};
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
const tabActive: CSSProperties = {
  ...tabBase,
  background: "var(--accent)",
  color: "#fff",
  border: "1px solid var(--accent)",
};

const card: CSSProperties = {
  background: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: 14,
  padding: 20,
};
const metaRow: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 10,
};
const label: CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.06em",
  textTransform: "uppercase",
  color: "var(--ink-muted)",
};
const emailBadge: CSSProperties = {
  fontSize: 12,
  color: "var(--ink-secondary)",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 6,
  padding: "2px 8px",
};
const instruction: CSSProperties = {
  fontSize: 13,
  color: "var(--ink-secondary)",
  margin: "0 0 12px",
  lineHeight: 1.6,
};
const pre: CSSProperties = {
  margin: 0,
  padding: "14px 56px 14px 16px",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 10,
  fontFamily: "ui-monospace, Menlo, monospace",
  fontSize: 12,
  color: "var(--ink)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  lineHeight: 1.7,
};
const hint: CSSProperties = {
  margin: "10px 0 0",
  fontSize: 12,
  color: "var(--ink-muted)",
  lineHeight: 1.6,
};
const code: CSSProperties = {
  fontFamily: "ui-monospace, Menlo, monospace",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 4,
  padding: "1px 5px",
  fontSize: 11,
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
const featureGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "1fr 1fr",
  gap: "6px 16px",
};
const featureItem: CSSProperties = {
  fontSize: 13,
  color: "var(--ink-secondary)",
  display: "flex",
  alignItems: "center",
};
