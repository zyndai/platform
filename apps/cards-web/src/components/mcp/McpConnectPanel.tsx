"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  connectMcp,
  disconnectMcp,
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
  const [busy, setBusy] = useState<"connect" | "disconnect" | null>(null);
  const [error, setError] = useState("");
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

  async function generate() {
    setError("");
    setBusy("connect");
    try {
      const t = await token();
      setResult(await connectMcp(t));
      onConnected?.(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the connection");
    } finally {
      setBusy(null);
    }
  }

  async function disconnect() {
    setError("");
    setBusy("disconnect");
    try {
      const t = await token();
      await disconnectMcp(t);
      setResult(null);
      onConnected?.(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect");
    } finally {
      setBusy(null);
    }
  }

  async function copyConfig() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.config_json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Clipboard blocked — select and copy the JSON manually.");
    }
  }

  useEffect(() => {
    if (!result) return;
    const onHash = () => setCopied(false);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [result]);

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14 }}>
      <div>
        <div style={{ font: `700 22px/1.15 ${DISPLAY}`, color: ink, letterSpacing: "-0.03em" }}>
          Get your MCP config
        </div>
        <p style={{ margin: "6px 0 0", font: `400 14px/1.55 ${SANS}`, color: muted, maxWidth: 460 }}>
          Generate a private key + URL, copy the JSON, and paste it into Claude Code,
          Cursor, Cline, or VS Code. Your agent then reports skills, languages, and
          projects into this card — you approve what goes public.
        </p>
      </div>

      {result ? (
        <>
          <div
            style={{
              border: `1px solid ${border}`,
              borderRadius: 14,
              padding: "14px 16px",
              background: fieldBg,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <span style={{ font: `500 11px/1 ${MONO}`, letterSpacing: "0.12em", textTransform: "uppercase", color: accent }}>
                Your MCP config
              </span>
              <button
                type="button"
                onClick={copyConfig}
                style={{
                  background: "transparent",
                  border: `1px solid ${border}`,
                  borderRadius: 8,
                  padding: "5px 10px",
                  font: `500 12px/1 ${SANS}`,
                  color: ink,
                  cursor: "pointer",
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <pre
              style={{
                margin: 0,
                padding: "12px 14px",
                borderRadius: 10,
                background: light ? "#FFFFFF" : "rgba(2,6,23,0.6)",
                border: `1px solid ${border}`,
                font: `400 12px/1.5 ${MONO}`,
                color: ink,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                overflowX: "auto",
                maxHeight: 220,
              }}
            >
              {result.config_json}
            </pre>
            <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {result.instructions.map((line) => (
                <li key={line} style={{ font: `400 12px/1.5 ${SANS}`, color: muted }}>
                  {line}
                </li>
              ))}
            </ul>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              type="button"
              onClick={generate}
              disabled={busy !== null}
              style={{
                background: accent,
                color: "#fff",
                border: "none",
                borderRadius: 12,
                padding: "12px 16px",
                font: `600 14px/1 ${DISPLAY}`,
                cursor: busy ? "default" : "pointer",
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === "connect" ? "Generating…" : "Regenerate"}
            </button>
            <button
              type="button"
              onClick={disconnect}
              disabled={busy !== null}
              style={{
                background: "transparent",
                color: ink,
                border: `1px solid ${border}`,
                borderRadius: 12,
                padding: "12px 16px",
                font: `600 14px/1 ${DISPLAY}`,
                cursor: busy ? "default" : "pointer",
                opacity: busy ? 0.7 : 1,
              }}
            >
              {busy === "disconnect" ? "Disconnecting…" : "Disconnect"}
            </button>
          </div>
          <p style={{ margin: 0, font: `400 12px/1.5 ${SANS}`, color: muted }}>
            Treat the token like a password. Disconnect revokes every ZYND token for
            your account — every connected agent signs out.
          </p>
        </>
      ) : (
        <button
          type="button"
          onClick={generate}
          disabled={busy !== null}
          style={{
            background: accent,
            color: "#fff",
            border: "none",
            borderRadius: 12,
            padding: "13px 18px",
            font: `600 14px/1 ${DISPLAY}`,
            letterSpacing: "-0.01em",
            cursor: busy ? "default" : "pointer",
            opacity: busy ? 0.7 : 1,
            alignSelf: "flex-start",
          }}
        >
          {busy === "connect" ? "Generating…" : "Generate MCP config + key"}
        </button>
      )}

      {error && (
        <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: light ? "#C2401F" : "#fbbf24" }}>
          {error}
        </p>
      )}
    </div>
  );
}
