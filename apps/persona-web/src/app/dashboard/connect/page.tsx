"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { getSupabase } from "@/lib/supabase";

// Memory service. It validates the persona Supabase session token (same project),
// so the signed-in user can mint their MCP token straight from here.
const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

type Exchange = { token: string; mcp_url: string; email: string };
type Status = "loading" | "ready" | "error";

const CLIENTS: { name: string; loc: string }[] = [
  { name: "Claude Desktop", loc: "Settings → Developer → Edit Config" },
  { name: "Claude Code", loc: "run `claude mcp add`, or edit .mcp.json" },
  { name: "Cursor", loc: "Settings → MCP → Add new server" },
  { name: "Windsurf", loc: "~/.codeium/windsurf/mcp_config.json" },
  { name: "Cline / Continue", loc: "mcpServers in the client config" },
  { name: "ChatGPT", loc: "use the ZYND GPT — no config needed" },
];

export default function ConnectPage() {
  const [status, setStatus] = useState<Status>("loading");
  const [result, setResult] = useState<Exchange | null>(null);
  const [error, setError] = useState("");
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
        if (!token) throw new Error("You're not signed in — reload the page.");
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

  const config = result
    ? JSON.stringify(
        {
          mcpServers: {
            zynd: {
              command: "npx",
              args: ["-y", "mcp-remote", result.mcp_url, "--header", `Authorization: Bearer ${result.token}`],
            },
          },
        },
        null,
        2,
      )
    : "";

  const copy = () => {
    navigator.clipboard.writeText(config);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: "28px 20px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, color: "var(--ink)", margin: "0 0 6px" }}>Connect any AI</h1>
      <p style={{ color: "var(--ink-secondary)", margin: "0 0 24px", fontSize: 14, lineHeight: 1.6 }}>
        Give Claude, Cursor, or any MCP client access to your ZYND memory — recall your
        context, find people, and connect.
      </p>

      {status === "loading" && <div style={card}>Creating your secure connection…</div>}

      {status === "error" && (
        <div style={card}>
          <p style={{ color: "var(--danger)", margin: "0 0 12px", fontSize: 14 }}>{error}</p>
          <button style={btn} onClick={() => setReload((k) => k + 1)}>Retry</button>
        </div>
      )}

      {status === "ready" && result && (
        <>
          <div style={card}>
            <div style={{ fontSize: 13, color: "var(--ink-secondary)", marginBottom: 14 }}>
              Connected as <strong style={{ color: "var(--ink)" }}>{result.email}</strong>
            </div>
            <h2 style={h2}>1 · Copy your connection config</h2>
            <p style={sub}>This block holds your private token — treat it like a password.</p>
            <div style={{ position: "relative" }}>
              <pre style={pre}>{config}</pre>
              <button style={{ ...btn, position: "absolute", top: 10, right: 10 }} onClick={copy}>
                {copied ? "✓ Copied" : "Copy"}
              </button>
            </div>
          </div>

          <div style={{ ...card, marginTop: 16 }}>
            <h2 style={h2}>2 · Add it to your AI client</h2>
            <p style={sub}>Most clients use the same mcpServers block — paste it, then restart the app.</p>
            <div style={{ display: "grid", gap: 0 }}>
              {CLIENTS.map((c) => (
                <div key={c.name} style={row}>
                  <span style={{ color: "var(--ink)", fontWeight: 500 }}>{c.name}</span>
                  <span style={{ color: "var(--ink-muted)" }}>{c.loc}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const card: CSSProperties = {
  background: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: 14,
  padding: 22,
};
const h2: CSSProperties = { fontSize: 15, fontWeight: 600, color: "var(--ink)", margin: "0 0 4px" };
const sub: CSSProperties = { fontSize: 13, color: "var(--ink-secondary)", margin: "0 0 14px" };
const pre: CSSProperties = {
  margin: 0,
  padding: "16px 56px 16px 16px",
  background: "var(--bg-void)",
  border: "1px solid var(--border-subtle)",
  borderRadius: 10,
  fontFamily: "ui-monospace, Menlo, monospace",
  fontSize: 12,
  color: "var(--ink)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  wordBreak: "break-all",
  lineHeight: 1.6,
};
const btn: CSSProperties = {
  background: "var(--accent)",
  color: "#fff",
  border: 0,
  borderRadius: 8,
  padding: "8px 14px",
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};
const row: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  fontSize: 13,
  padding: "9px 0",
  borderBottom: "1px solid var(--border-subtle)",
};
