"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

const MCP_URL = (process.env.NEXT_PUBLIC_MCP_URL || `${(process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/+$/, "")}/mcp`).replace(/\/+$/, "");

type Client = {
  name: string;
  setup: string;
  steps: string[];
  config?: (url: string) => string;
};

const CLIENTS: Client[] = [
  {
    name: "Claude Desktop", setup: "Native connector; live Zynd OAuth login and refresh unverified.",
    steps: ["Open Settings → Connectors → Add custom connector.", "Paste the URL, connect, then sign in to Zynd and approve full access in your browser."],
    config: (url) => url,
  },
  {
    name: "Claude Code", setup: "Native HTTP OAuth; live Zynd OAuth login and refresh unverified.",
    steps: ["Run the command below in your terminal.", "In Claude Code, run /mcp, select zynd, then sign in to Zynd and approve access in the browser."],
    config: (url) => `claude mcp add --scope user --transport http zynd ${url}`,
  },
  {
    name: "ChatGPT", setup: "Native connector; live Zynd OAuth login and refresh unverified. Availability varies by plan/workspace.",
    steps: ["In ChatGPT web, open Plugins → Add custom MCP server (if available in your workspace).", "Paste the URL, connect, then sign in to Zynd and approve access in the browser."],
    config: (url) => url,
  },
  {
    name: "Codex", setup: "Native CLI OAuth; live Zynd OAuth login and refresh unverified.",
    steps: ["Run the command below in your terminal.", "Run codex mcp login zynd, then sign in to Zynd and approve access in the browser."],
    config: (url) => `codex mcp add zynd --url ${url}`,
  },
  {
    name: "Kilo CLI", setup: "Native remote OAuth; live Zynd OAuth login and refresh unverified.",
    steps: ["Merge this entry into your Kilo MCP settings without removing existing servers.", "Run kilo mcp auth zynd, then sign in to Zynd and approve access in the browser."],
    config: (url) => JSON.stringify({ mcp: { zynd: { type: "remote", url } } }, null, 2),
  },
  {
    name: "OpenCode v2", setup: "Native remote OAuth; live Zynd OAuth login and refresh unverified.",
    steps: ["For OpenCode v2, merge this entry into opencode.json without removing existing servers. OpenCode v1 instead uses mcp.zynd.", "Run opencode mcp auth zynd, then sign in to Zynd and approve access in the browser."],
    config: (url) => JSON.stringify({ mcp: { servers: { zynd: { type: "remote", url } } } }, null, 2),
  },
  {
    name: "Cursor", setup: "Native remote OAuth; live Zynd OAuth login and refresh unverified.",
    steps: ["Open Settings → MCP → Add new global MCP server, and merge this into mcp.json.", "Connect and sign in to Zynd in your browser. Cursor CLI users can run agent mcp login zynd where supported."],
    config: (url) => JSON.stringify({ mcpServers: { zynd: { url } } }, null, 2),
  },
  ...["Windsurf", "Cline", "Antigravity", "OpenClaw", "Hermes"].map((name): Client => ({
    name,
    setup: "Unverified: OAuth callback, credential persistence, and refresh have not been confirmed. Setup is not yet supported.",
    steps: ["Do not paste a bearer credential or install an untested OAuth bridge. Check back after real-client validation."],
  })),
];

const FEATURES = [
  { title: "Persistent memory", desc: "Remembers what you tell it across tools." },
  { title: "Google Calendar & Gmail", desc: "Checks your calendar, books meetings, sends email." },
  { title: "LinkedIn search & profiles", desc: "Looks people up on LinkedIn by role or topic." },
  { title: "Notion read & write", desc: "Reads and edits your connected Notion pages." },
  { title: "Publish live web pages", desc: "Turns a chat into a shareable web page." },
  { title: "ZYND network", desc: "Finds people on ZYND." },
];

export default function ConnectPage() {
  const [selected, setSelected] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const client = CLIENTS[selected];
  const config = client.config?.(MCP_URL);

  async function copy() {
    if (!config) return;
    try {
      await navigator.clipboard.writeText(config);
      setCopyError("");
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyError("Clipboard unavailable. Select and copy the setup text manually.");
    }
  }

  return (
    <div style={{ padding: "32px clamp(16px, 4vw, 40px) 56px", maxWidth: 1080, margin: "0 auto" }}>
      <p style={{ fontSize: 14, color: "var(--ink-secondary)" }}>Choose your client. Your agent starts browser authorization; this page never creates a credential.</p>
      <div role="tablist" aria-label="MCP clients" style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: 8, margin: "20px 0 28px", background: "var(--surface-raised)", border: "1px solid var(--border-default)", borderRadius: "var(--r-md)" }}>
        {CLIENTS.map((c, i) => (
          <button key={c.name} role="tab" aria-selected={selected === i} type="button" onClick={() => { setSelected(i); setCopied(false); }}
            style={{ padding: "8px 12px", borderRadius: "var(--r-sm)", border: "none", cursor: "pointer", background: selected === i ? "var(--surface)" : "transparent", color: selected === i ? "var(--ink)" : "var(--ink-secondary)", fontWeight: selected === i ? 700 : 500, whiteSpace: "nowrap" }}>
            {c.name}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 32 }}>
        <main style={{ flex: "1 1 340px", minWidth: 0 }}>
          <h2 style={{ fontSize: 20, color: "var(--ink)", margin: "0 0 12px" }}>{client.name}</h2>
          <p style={{ fontSize: 13, color: "var(--ink-secondary)", lineHeight: 1.6 }}>{client.setup}</p>
           <p style={{ fontSize: 13, color: "var(--ink-secondary)", lineHeight: 1.6 }}>Authorization grants full access to your Zynd memory, card, and connected integrations. An existing Zynd account is required. You can disconnect individual connections in the <a href="https://cards.zynd.ai/home" style={{ color: "var(--accent)" }}>Cards owner area</a> under Edit profile → Coding agents.</p>
          {client.steps.map((step, i) => <div key={step} style={{ display: "flex", gap: 14, marginTop: 24 }}>
            <span style={{ width: 30, height: 30, flexShrink: 0, borderRadius: "50%", background: "var(--surface-raised)", border: "1px solid var(--border-default)", display: "grid", placeItems: "center", color: "var(--ink-secondary)" }}>{i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: 14, color: "var(--ink)", margin: "5px 0 12px" }}>{step}</p>
              {i === 0 && config && <div style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: 14, background: "var(--surface-raised)", border: "1px solid var(--border-default)", borderRadius: "var(--r-md)" }}>
                <pre style={{ flex: 1, minWidth: 0, margin: 0, fontSize: 12, color: "var(--ink)", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{config}</pre>
                 <button type="button" onClick={() => void copy()} aria-label={copied ? "Copied setup" : "Copy setup"} title={copied ? "Copied setup" : "Copy setup"} style={{ border: 0, cursor: "pointer", background: "transparent", color: "var(--accent)", display: "inline-flex", gap: 6, alignItems: "center" }}>{copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? "Copied" : "Copy"}</button>
               </div>}
            </div>
           </div>)}
          {copyError && <p role="alert" style={{ fontSize: 13, color: "var(--danger)" }}>{copyError}</p>}
        </main>
        <aside style={{ flex: "1 1 260px", maxWidth: 320, padding: 24, background: "var(--surface-raised)", border: "1px solid var(--border-subtle)", borderRadius: "var(--r-lg)" }}>
          <h3 style={{ fontSize: 13, color: "var(--ink-muted)", margin: "0 0 18px" }}>What ZYND gives your AI</h3>
          {FEATURES.map((f) => <div key={f.title} style={{ marginBottom: 18 }}><strong style={{ fontSize: 14, color: "var(--ink)" }}>{f.title}</strong><p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--ink-secondary)", lineHeight: 1.5 }}>{f.desc}</p></div>)}
        </aside>
      </div>
    </div>
  );
}
