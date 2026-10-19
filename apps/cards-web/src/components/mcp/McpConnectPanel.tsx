"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy, RefreshCw } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { MCP_URL, listMcpClients, revokeAllMcpClients, revokeMcpClient, type McpClientRow } from "@/lib/mcp-connector";

// Styled by the card editor's edit.css (pe-* classes).

// Setup for each client follows its own docs; Zynd login and token refresh
// haven't been verified end to end in all of them yet (said under the list).
const CLIENTS: { name: string; steps: string; config: (url: string) => string; note?: string }[] = [
  { name: "Claude Code", steps: "Run this, then type /mcp in Claude Code and authorize zynd in your browser.", config: (url) => `claude mcp add --scope user --transport http zynd ${url}` },
  { name: "Claude Desktop", steps: "Open Settings → Connectors → Add custom connector. Paste this URL and authorize in your browser.", config: (url) => url },
  { name: "ChatGPT", steps: "In ChatGPT web, use Plugins → Add custom MCP server. Paste this URL and authorize in your browser.", config: (url) => url, note: "Availability varies by workspace." },
  { name: "Codex", steps: "Run this, then codex mcp login zynd to authorize in your browser.", config: (url) => `codex mcp add zynd --url ${url}` },
  { name: "Cursor", steps: "Merge this into ~/.cursor/mcp.json using Settings → MCP, then authorize in your browser.", config: (url) => JSON.stringify({ mcpServers: { zynd: { url } } }, null, 2), note: "Cursor CLI can run agent mcp login zynd where supported." },
  { name: "Kilo CLI", steps: "Merge this into your Kilo MCP settings, then run kilo mcp auth zynd.", config: (url) => JSON.stringify({ mcp: { zynd: { type: "remote", url } } }, null, 2) },
  { name: "OpenCode v2", steps: "Merge this into opencode.json, then run opencode mcp auth zynd.", config: (url) => JSON.stringify({ mcp: { servers: { zynd: { type: "remote", url } } } }, null, 2), note: "OpenCode v1 uses mcp.zynd instead." },
];
// Unverified OAuth callback and refresh: no setup offered.
const UNSUPPORTED = ["Windsurf", "Cline", "Antigravity", "OpenClaw", "Hermes"];

export function McpConnectPanel({ onConnected }: { onConnected?: (connected: boolean) => void } = {}) {
  const [clients, setClients] = useState<McpClientRow[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const requestId = useRef(0);
  const client = CLIENTS[selected];
  const config = client.config(MCP_URL);

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
    try {
      await navigator.clipboard.writeText(config);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { setError("Clipboard blocked; select and copy the text manually."); }
  }

  return <div className="pe-mcp">
    <div className="pe-clients" role="group" aria-label="Client">
      {CLIENTS.map((c, i) => (
        <button key={c.name} type="button" className="pe-client" aria-pressed={i === selected}
          onClick={() => { setSelected(i); setCopied(false); }}>
          {c.name}
        </button>
      ))}
    </div>

    <div className="pe-setup">
      <p className="pe-setup-steps">{client.steps}</p>
      <div className="pe-code">
        <pre>{config}</pre>
        <button type="button" className="pe-btn pe-btn-primary" onClick={() => void copy()}
          aria-label={copied ? "Copied setup" : "Copy setup"} title={copied ? "Copied setup" : "Copy setup"}>
          {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? "Copied" : "Copy"}
        </button>
      </div>
      {client.note && <p className="pe-note">{client.note}</p>}
    </div>
    <p className="pe-note">
      Zynd sign-in isn&apos;t verified in every client yet. Not supported: {UNSUPPORTED.join(", ")} — don&apos;t paste a
      bearer token into them or install an untested OAuth bridge.
    </p>

    <div className="pe-connected">
      <div className="pe-connected-head">
        <h3 className="pe-connected-title">Connected assistants</h3>
        <button type="button" className="pe-icon-btn" onClick={refreshInventory} disabled={loading || busy !== null}
          title="Refresh connected assistants" aria-label="Refresh connected assistants">
          <RefreshCw size={15} aria-hidden="true" className={loading ? "pe-spin" : undefined} />
        </button>
      </div>
      {loading && <p role="status" className="pe-note">Loading connections…</p>}
      {!loading && !error && clients.length === 0 && (
        <p className="pe-empty">No assistants connected yet. After you authorize one, come back here and refresh.</p>
      )}
      {clients.map(row => <div key={row.id} className="pe-conn">
        <div className="pe-conn-main">
          <div className="pe-conn-name">{row.label}</div>
          <div className="pe-conn-meta">
            {row.last_used_at ? `Last used ${new Date(row.last_used_at).toLocaleString()}` : "No report yet"} · {row.scopes.includes("user") ? "Full access (memory, card, integrations)" : row.scopes.join(", ") || "Legacy permissions not reported"}
          </div>
        </div>
        <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={() => void disconnect(row.id)} disabled={busy !== null}>
          {busy === row.id ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>)}
      {clients.length > 1 && (
        <button type="button" className="pe-btn pe-btn-danger pe-btn-sm" style={{ alignSelf: "flex-start" }} onClick={() => void disconnect()} disabled={busy !== null}>
          {busy === "all" ? "Disconnecting…" : "Disconnect all"}
        </button>
      )}
    </div>
    {error && <p role="alert" className="pe-error">{error}</p>}
  </div>;
}
