"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  MCP_SCOPES,
  connectMcp,
  listMcpClients,
  revokeAllMcpClients,
  revokeMcpClient,
  type McpClientRow,
  type McpConnectResult,
} from "@/lib/mcp-connector";

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

export function McpConnectPanel({
  tone = "light",
  onConnected,
}: {
  tone?: "light" | "dark";
  onConnected?: (connected: boolean) => void;
} = {}) {
  const light = tone === "light";
  const [result, setResult] = useState<McpConnectResult | null>(null);
  const [clients, setClients] = useState<McpClientRow[]>([]);
  const [scopes, setScopes] = useState<string[]>(["memory:write"]);
  const [label, setLabel] = useState("Claude");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [copied, setCopied] = useState(false);

  const ink = light ? "#0B0B0B" : "#f8fafc";
  const muted = light ? "#6E6E68" : "#94a3b8";
  const border = light ? "#DEDED8" : "rgba(255,255,255,0.12)";
  const fieldBg = light ? "#F7F7F4" : "rgba(15,23,42,0.8)";
  const accent = "#7B72E9";

  const token = useCallback(async () => {
    const { data } = await createClient().auth.getSession();
    const t = data.session?.access_token;
    if (!t) throw new Error("Sign in first so coding agents can feed your card.");
    return t;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const t = await token();
      const rows = await listMcpClients(t);
      setClients(rows);
      onConnected?.(rows.length > 0);
    } catch {
      setClients([]);
    }
  }, [onConnected, token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function toggleScope(id: string, locked: boolean) {
    if (locked) return;
    setScopes((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]));
  }

  async function generate() {
    setError("");
    setBusy("connect");
    try {
      const t = await token();
      const created = await connectMcp(t, { label, scopes });
      setResult(created);
      setShowConfig(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect");
    } finally {
      setBusy(null);
    }
  }

  async function revokeOne(id: string) {
    setError("");
    setBusy(id);
    try {
      const t = await token();
      await revokeMcpClient(t, id);
      if (result?.client_id === id) setResult(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect that assistant");
    } finally {
      setBusy(null);
    }
  }

  async function revokeAll() {
    setError("");
    setBusy("all");
    try {
      const t = await token();
      await revokeAllMcpClients(t);
      setResult(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect");
    } finally {
      setBusy(null);
    }
  }

  async function copyText(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Clipboard blocked — select and copy the text manually.");
    }
  }

  const button = (primary: boolean): CSSProperties => ({
    background: primary ? accent : "transparent",
    color: primary ? "#fff" : ink,
    border: primary ? "none" : `1px solid ${border}`,
    borderRadius: 12,
    padding: "12px 16px",
    font: `600 14px/1 ${DISPLAY}`,
    cursor: busy ? "default" : "pointer",
    opacity: busy ? 0.7 : 1,
    textDecoration: "none",
    display: "inline-flex",
    alignItems: "center",
  });

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={{ font: `700 22px/1.15 ${DISPLAY}`, color: ink, letterSpacing: "-0.03em" }}>
          Connect an assistant
        </div>
        <p style={{ margin: "6px 0 0", font: `400 14px/1.55 ${SANS}`, color: muted, maxWidth: 480 }}>
          One click adds Cursor or copies a Claude Code command. Each assistant has its own
          token. Disconnecting one leaves the others signed in.
        </p>
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{ font: `500 12px/1 ${SANS}`, color: muted }}>Assistant name</span>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          style={{
            border: `1px solid ${border}`,
            borderRadius: 10,
            padding: "10px 12px",
            font: `400 14px/1 ${SANS}`,
            color: ink,
            background: fieldBg,
          }}
        />
      </label>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {MCP_SCOPES.map((scope) => (
          <label key={scope.id} style={{ display: "flex", gap: 8, alignItems: "center", font: `400 13px/1.4 ${SANS}`, color: ink }}>
            <input
              type="checkbox"
              checked={scopes.includes(scope.id)}
              disabled={scope.locked}
              onChange={() => toggleScope(scope.id, scope.locked)}
            />
            {scope.label}
            {scope.id === "cards:approve" || scope.id === "people:message" ? (
              <span style={{ color: muted }}> · off by default</span>
            ) : null}
          </label>
        ))}
      </div>

      <button type="button" onClick={generate} disabled={busy !== null} style={{ ...button(true), alignSelf: "flex-start" }}>
        {busy === "connect" ? "Connecting…" : "Connect assistant"}
      </button>

      {result && (
        <div style={{ border: `1px solid ${border}`, borderRadius: 14, padding: "14px 16px", background: fieldBg, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ font: `600 14px/1.3 ${DISPLAY}`, color: ink }}>{result.label || "Assistant"} connected</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {result.cursor && (
              <a href={result.cursor} style={button(true)}>Add to Cursor</a>
            )}
            {result.claude_code && (
              <button type="button" onClick={() => copyText(result.claude_code || "")} style={button(false)}>
                {copied ? "Copied" : "Copy Claude Code command"}
              </button>
            )}
            {result.server_url && (
              <button type="button" onClick={() => copyText(result.server_url || "")} style={button(false)}>
                Copy server URL
              </button>
            )}
          </div>
          <p style={{ margin: 0, font: `400 12px/1.5 ${SANS}`, color: muted }}>
            Claude and ChatGPT use the server URL as a custom connector. No JSON.
          </p>
          <button type="button" onClick={() => setShowConfig((v) => !v)} style={{ ...button(false), alignSelf: "flex-start", padding: "8px 12px" }}>
            {showConfig ? "Hide config file" : "Use a config file"}
          </button>
          {showConfig && (
            <pre style={{ margin: 0, padding: "12px 14px", borderRadius: 10, background: light ? "#fff" : "rgba(2,6,23,0.6)", border: `1px solid ${border}`, font: `400 12px/1.5 ${MONO}`, color: ink, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {result.config_json}
            </pre>
          )}
        </div>
      )}

      {clients.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ font: `600 14px/1 ${DISPLAY}`, color: ink }}>Connected assistants</div>
          {clients.map((client) => (
            <div key={client.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", border: `1px solid ${border}`, borderRadius: 12, padding: "10px 12px" }}>
              <div>
                <div style={{ font: `600 13px/1.3 ${SANS}`, color: ink }}>{client.label}</div>
                <div style={{ font: `400 12px/1.4 ${SANS}`, color: muted }}>
                  {client.last_used_at ? `Last used ${new Date(client.last_used_at).toLocaleString()}` : "No report yet"}
                  {" · "}
                  {client.scopes.join(", ")}
                </div>
              </div>
              <button type="button" onClick={() => revokeOne(client.id)} disabled={busy !== null} style={button(false)}>
                {busy === client.id ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          ))}
          <button type="button" onClick={revokeAll} disabled={busy !== null} style={{ ...button(false), alignSelf: "flex-start" }}>
            {busy === "all" ? "Disconnecting…" : "Disconnect all"}
          </button>
        </div>
      )}

      {error && (
        <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: light ? "#C2401F" : "#fbbf24" }}>{error}</p>
      )}
    </div>
  );
}
