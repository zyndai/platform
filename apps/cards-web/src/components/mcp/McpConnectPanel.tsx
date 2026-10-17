"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { MCP_URL, listMcpClients, revokeAllMcpClients, revokeMcpClient, type McpClientRow } from "@/lib/mcp-connector";

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

const CLIENTS = [
  { name: "Claude Code", status: "Docs-based native OAuth; Zynd login and refresh not yet verified.", instructions: "Run this command, then type /mcp in Claude Code and authorize zynd in your browser.", config: (url: string) => `claude mcp add --scope user --transport http zynd ${url}` },
  { name: "Claude Desktop", status: "Docs-based native OAuth; Zynd login and refresh not yet verified.", instructions: "Open Settings → Connectors → Add custom connector. Paste this URL and authorize in your browser.", config: (url: string) => url },
  { name: "ChatGPT", status: "Docs-based native OAuth; Zynd login and refresh not yet verified. Availability varies by workspace.", instructions: "In ChatGPT web, use Plugins → Add custom MCP server if available. Paste this URL and authorize in your browser.", config: (url: string) => url },
  { name: "Codex", status: "Docs-based native OAuth; Zynd login and refresh not yet verified.", instructions: "Run this command, then codex mcp login zynd to authorize in your browser.", config: (url: string) => `codex mcp add zynd --url ${url}` },
  { name: "Kilo CLI", status: "Docs-based native OAuth; Zynd login and refresh not yet verified.", instructions: "Merge this into your Kilo MCP settings, then run kilo mcp auth zynd.", config: (url: string) => JSON.stringify({ mcp: { zynd: { type: "remote", url } } }, null, 2) },
  { name: "OpenCode v2", status: "Docs-based native OAuth; Zynd login and refresh not yet verified. v1 instead uses mcp.zynd.", instructions: "Merge this into opencode.json, then run opencode mcp auth zynd.", config: (url: string) => JSON.stringify({ mcp: { servers: { zynd: { type: "remote", url } } } }, null, 2) },
  { name: "Cursor", status: "Docs-based native OAuth; Zynd login and refresh not yet verified.", instructions: "Merge this into ~/.cursor/mcp.json using Settings → MCP, then authorize in your browser. Cursor CLI can run agent mcp login zynd where supported.", config: (url: string) => JSON.stringify({ mcpServers: { zynd: { url } } }, null, 2) },
  ...["Windsurf", "Cline", "Antigravity", "OpenClaw", "Hermes"].map(name => ({ name, status: "Unverified OAuth callback and refresh; setup not yet supported.", instructions: "Do not paste a bearer credential or install an untested OAuth bridge.", config: undefined as ((url: string) => string) | undefined })),
];

export function McpConnectPanel({ tone = "light", onConnected }: { tone?: "light" | "dark"; onConnected?: (connected: boolean) => void } = {}) {
  const light = tone === "light";
  const [clients, setClients] = useState<McpClientRow[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const requestId = useRef(0);
  const ink = light ? "#0B0B0B" : "#f8fafc";
  const muted = light ? "#6E6E68" : "#94a3b8";
  const border = light ? "#DEDED8" : "rgba(255,255,255,0.12)";
  const fieldBg = light ? "#F7F7F4" : "rgba(15,23,42,0.8)";
  const client = CLIENTS[selected];
  const config = client.config?.(MCP_URL);

  async function sessionToken() {
    const { data } = await createClient().auth.getSession();
    if (!data.session?.access_token) throw new Error("Sign in first to manage your connections.");
    return data.session.access_token;
  }

  const refresh = useCallback(async () => {
    const current = ++requestId.current;
    try {
      const { data } = await createClient().auth.getSession();
      if (!data.session?.access_token) throw new Error("Sign in first to manage your connections.");
      const rows = await listMcpClients(data.session.access_token);
      if (current !== requestId.current) return;
      setClients(rows);
      setError("");
      onConnected?.(rows.length > 0);
    } catch (err) {
      if (current === requestId.current) setError(err instanceof Error ? err.message : "Could not load connected assistants.");
    } finally {
      if (current === requestId.current) setLoading(false);
    }
  }, [onConnected]);

  useEffect(() => {
    let active = true;
    const request = requestId;
    Promise.resolve().then(() => { if (active) void refresh(); });
    const onFocus = () => { setLoading(true); void refresh(); };
    window.addEventListener("focus", onFocus);
    return () => { active = false; request.current++; window.removeEventListener("focus", onFocus); };
  }, [refresh]);

  function refreshInventory() {
    setLoading(true);
    void refresh();
  }

  async function disconnect(id?: string) {
    setBusy(id || "all");
    setError("");
    try {
      const token = await sessionToken();
      if (id) await revokeMcpClient(token, id);
      else await revokeAllMcpClients(token);
      setLoading(true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect");
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    if (!config) return;
    try {
      await navigator.clipboard.writeText(config);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { setError("Clipboard blocked; select and copy the text manually."); }
  }

  const button = (primary = false): CSSProperties => ({
    background: primary ? "#7B72E9" : "transparent", color: primary ? "#fff" : ink,
    border: primary ? "none" : `1px solid ${border}`, borderRadius: 12, padding: "10px 14px",
    font: `600 13px/1.2 ${DISPLAY}`, cursor: busy ? "default" : "pointer",
  });

  return <div style={{ display: "flex", flexDirection: "column", gap: 16, width: "100%" }}>
    <div>
      <h3 style={{ font: `700 22px/1.15 ${DISPLAY}`, color: ink, margin: 0 }}>Connect an assistant</h3>
      <p style={{ font: `400 14px/1.55 ${SANS}`, color: muted, maxWidth: 500 }}>
         Add the server URL in your client, then sign in and grant the scopes you want in your browser. The authenticated Cards MCP can find Cards, manage connection requests, DM accepted connections, and create groups with invitation acceptance. An existing Zynd account is required; each assistant connection can be disconnected separately.
      </p>
    </div>
    <label style={{ display: "flex", flexDirection: "column", gap: 6, font: `500 13px ${SANS}`, color: ink }}>
      Client
      <select value={selected} onChange={e => { setSelected(Number(e.target.value)); setCopied(false); }} style={{ padding: "10px 12px", border: `1px solid ${border}`, borderRadius: 10, background: fieldBg, color: ink, font: `400 14px ${SANS}`, maxWidth: 350 }}>
        {CLIENTS.map((c, i) => <option key={c.name} value={i}>{c.name}</option>)}
      </select>
    </label>
    <div style={{ border: `1px solid ${border}`, background: fieldBg, padding: "16px", borderRadius: 14, minWidth: 0 }}>
      <strong style={{ font: `600 14px ${DISPLAY}`, color: ink }}>{client.name}</strong>
      <p style={{ font: `400 13px/1.5 ${SANS}`, color: muted }}>{client.status}</p>
      <p style={{ font: `400 13px/1.5 ${SANS}`, color: ink }}>{client.instructions}</p>
      {config && <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 10 }}>
        <pre style={{ flex: "1 1 230px", minWidth: 0, padding: "12px 14px", margin: 0, border: `1px solid ${border}`, borderRadius: 10, font: `400 12px/1.5 ${MONO}`, color: ink, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{config}</pre>
        <button type="button" onClick={() => void copy()} aria-label={copied ? "Copied setup" : "Copy setup"} title={copied ? "Copied setup" : "Copy setup"} style={{ ...button(true), display: "inline-flex", alignItems: "center", gap: 8 }}>
          {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? "Copied" : "Copy setup"}
        </button>
      </div>}
    </div>
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <strong style={{ font: `600 14px ${DISPLAY}`, color: ink }}>Connected assistants</strong>
        <button type="button" onClick={refreshInventory} title="Refresh connected assistants" aria-label="Refresh connected assistants" disabled={loading || busy !== null}
          style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", padding: 6, border: `1px solid ${border}`, borderRadius: 8, background: "transparent", color: muted, cursor: loading || busy ? "default" : "pointer" }}>
          <RefreshCw size={15} aria-hidden="true" />
        </button>
      </div>
      {loading && <p role="status" style={{ margin: 0, font: `400 13px ${SANS}`, color: muted }}>Loading connections…</p>}
      {!loading && !error && clients.length === 0 && <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: muted }}>No assistants connected yet. After authorizing in your client, return here and refresh to see the connection.</p>}
      {clients.map(row => <div key={row.id} style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 12, border: `1px solid ${border}`, borderRadius: 12, padding: "10px 12px" }}>
        <div style={{ minWidth: 0 }}>
          <strong style={{ font: `600 13px ${SANS}`, color: ink }}>{row.label}</strong>
          <div style={{ font: `400 12px/1.5 ${SANS}`, color: muted, overflowWrap: "anywhere" }}>
            {row.last_used_at ? `Last used ${new Date(row.last_used_at).toLocaleString()}` : "No report yet"} · {row.scopes.includes("user") ? "Full access (memory, card, integrations)" : row.scopes.join(", ") || "Legacy permissions not reported"}
          </div>
        </div>
        <button type="button" onClick={() => void disconnect(row.id)} disabled={busy !== null} style={button()}>{busy === row.id ? "Disconnecting…" : "Disconnect"}</button>
      </div>)}
      {clients.length > 0 && <button type="button" onClick={() => void disconnect()} disabled={busy !== null} style={{ ...button(), alignSelf: "flex-start" }}>{busy === "all" ? "Disconnecting…" : "Disconnect all"}</button>}
    </div>
    {error && <p role="alert" style={{ color: light ? "#C2401F" : "#fbbf24", font: `400 13px ${SANS}` }}>{error}</p>}
  </div>;
}
