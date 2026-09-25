"use client";

import { useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  declareMemoryFacts,
  exchangeZyndToken,
  previewProviderMemory,
  refreshCardMemory,
} from "@/lib/memory";
import type { MemoryFact } from "@/lib/memory-facts";
import { MemoryTilePreview } from "./MemoryTilePreview";

type Step = "form" | "preview";

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

function factKey(fact: MemoryFact): string {
  return `${fact.predicate}|${fact.object.trim().toLowerCase()}`;
}

export function MemoryProviderOnboard({
  firstName,
  handle,
  tone = "light",
  compact = false,
  onSkip,
  onImported,
}: {
  firstName: string;
  handle: string;
  tone?: "light" | "dark";
  compact?: boolean;
  onSkip: () => void;
  onImported: (facts: MemoryFact[]) => void;
}) {
  const light = tone === "light";
  const [apiKey, setApiKey] = useState("");
  const [userId, setUserId] = useState("");
  const [showUserId, setShowUserId] = useState(false);
  const [detected, setDetected] = useState("");
  const [step, setStep] = useState<Step>("form");
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [error, setError] = useState("");

  const ink = light ? "#0B0B0B" : "#f8fafc";
  const muted = light ? "#6E6E68" : "#94a3b8";
  const faint = light ? "#A8A8A2" : "#64748b";
  const border = light ? "#DEDED8" : "rgba(255,255,255,0.12)";
  const fieldBg = light ? "#F7F7F4" : "rgba(15,23,42,0.8)";
  const accent = "#7B72E9";

  const chosen = useMemo(
    () => facts.filter((fact) => selected.has(factKey(fact))),
    [facts, selected],
  );

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function withZyndToken(): Promise<{ supabaseToken: string; zyndToken: string }> {
    const { data } = await createClient().auth.getSession();
    const supabaseToken = data.session?.access_token;
    if (!supabaseToken) {
      throw new Error("Sign in first so we can attach memory to your profile.");
    }
    const zyndToken = await exchangeZyndToken(supabaseToken);
    return { supabaseToken, zyndToken };
  }

  async function preview() {
    setError("");
    const key = apiKey.trim();
    if (key.length < 8) {
      setError("Paste the full API key.");
      return;
    }
    setBusy("preview");
    try {
      const { zyndToken } = await withZyndToken();
      const result = await previewProviderMemory({
        zyndToken,
        apiKey: key,
        userId,
      });
      setDetected(result.provider);
      setFacts(result.facts);
      setSelected(new Set(result.facts.map(factKey)));
      setStep("preview");
      if (result.facts.length === 0) {
        setError(
          result.provider
            ? `Found ${result.provider}, but nothing we can show as public key points.`
            : "We found that account, but nothing we can show as public key points.",
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function approve() {
    setError("");
    if (chosen.length === 0) {
      setError("Keep at least one key point, or skip.");
      return;
    }
    setBusy("save");
    try {
      const { supabaseToken, zyndToken } = await withZyndToken();
      const result = await declareMemoryFacts({ zyndToken, facts: chosen });
      if (result.declared === 0) {
        throw new Error("None of those facts could be saved. Try different ones, or skip.");
      }
      let snap: MemoryFact[] | null = null;
      try {
        snap = await refreshCardMemory({ supabaseToken, handle });
      } catch (err) {
        setError(
          err instanceof Error
            ? `${err.message} Facts are saved — they may take a few hours to appear.`
            : "Saved, but the profile tile may take a few hours to update.",
        );
      }
      setApiKey("");
      onImported(snap && snap.length > 0 ? snap : chosen);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save to your profile");
    } finally {
      setBusy(null);
    }
  }

  const inputStyle: React.CSSProperties = {
    display: "block",
    width: "100%",
    marginTop: 8,
    boxSizing: "border-box",
    padding: compact ? "12px 14px" : "16px 18px",
    borderRadius: compact ? 12 : 16,
    border: `1px solid ${border}`,
    background: fieldBg,
    color: ink,
    font: `400 ${compact ? 14 : 15}px/1.4 ${SANS}`,
    outline: "none",
  };

  const primaryStyle: React.CSSProperties = {
    background: accent,
    color: "#fff",
    border: "none",
    borderRadius: compact ? 14 : 18,
    padding: compact ? "12px 16px" : "18px 22px",
    font: `600 ${compact ? 14 : 15}px/1 ${DISPLAY}`,
    letterSpacing: "-0.01em",
    cursor: busy ? "default" : "pointer",
    opacity: busy ? 0.7 : 1,
    width: "100%",
  };

  const skipStyle: React.CSSProperties = {
    background: fieldBg,
    color: ink,
    border: `1px solid ${border}`,
    borderRadius: compact ? 14 : 18,
    padding: compact ? "12px 16px" : "16px 22px",
    font: `600 ${compact ? 14 : 15}px/1 ${DISPLAY}`,
    letterSpacing: "-0.01em",
    cursor: busy ? "default" : "pointer",
    width: "100%",
  };

  const titleStyle: React.CSSProperties = {
    font: `700 ${compact ? 22 : 34}px/1.15 ${DISPLAY}`,
    color: ink,
    letterSpacing: "-0.03em",
  };

  return (
    <div style={{ width: "100%", height: compact ? "auto" : "100%", display: "flex", flexDirection: "column", minHeight: 0, flex: compact ? "none" : 1, gap: compact ? 14 : 0 }}>
      {step === "form" && (
        <>
          <div>
            <div className="zc-question" style={titleStyle}>
              Got a memory key?
            </div>
            <p style={{ margin: compact ? "6px 0 0" : "10px 0 0", font: `400 ${compact ? 13 : 15}px/1.55 ${SANS}`, color: muted, maxWidth: 440 }}>
              Optional. Paste it and we&apos;ll preview the tile on your card.
            </p>
            {!compact && (
              <p style={{ margin: "6px 0 0", font: `400 13px/1.5 ${SANS}`, color: faint }}>
                We accept mem0, Zep, Letta, and supermemory.
              </p>
            )}
          </div>
          <div style={{ flex: compact ? "none" : 1, display: "flex", flexDirection: "column", justifyContent: compact ? "flex-start" : "center", minHeight: compact ? 0 : 24 }}>
            <input
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste API key"
              style={{ ...inputStyle, marginTop: 0 }}
            />
            {showUserId ? (
              <input
                type="text"
                autoComplete="off"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder="User ID (optional)"
                style={{ ...inputStyle, marginTop: 10 }}
              />
            ) : (
              <button
                type="button"
                onClick={() => setShowUserId(true)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  marginTop: 10,
                  font: `400 13px/1 ${SANS}`,
                  color: faint,
                  cursor: "pointer",
                  textAlign: "left",
                  alignSelf: "flex-start",
                }}
              >
                Need a user ID? →
              </button>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, flexShrink: 0 }}>
            <button type="button" onClick={preview} disabled={busy !== null} style={primaryStyle}>
              {busy === "preview" ? "Detecting…" : "Preview tile"}
            </button>
            <button
              type="button"
              onClick={() => {
                setApiKey("");
                onSkip();
              }}
              disabled={busy !== null}
              style={skipStyle}
            >
              Skip for now
            </button>
          </div>
        </>
      )}

      {step === "preview" && (
        <>
          <div>
            <div className="zc-question" style={titleStyle}>
              Looks like this
            </div>
            {detected && (
              <p style={{ margin: "10px 0 0", font: `500 11px/1 ${MONO}`, letterSpacing: "0.12em", textTransform: "uppercase", color: accent }}>
                Detected {detected}
              </p>
            )}
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", justifyContent: compact ? "flex-start" : "center", padding: compact ? "10px 0" : "16px 0" }}>
            <MemoryTilePreview
              firstName={firstName}
              facts={facts}
              selectedKeys={selected}
              onToggle={facts.length > 0 ? toggle : undefined}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, flexShrink: 0 }}>
            {facts.length > 0 && (
              <button type="button" onClick={approve} disabled={busy !== null} style={primaryStyle}>
                {busy === "save" ? "Publishing…" : "Show this on my profile"}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setStep("form");
                setError("");
              }}
              disabled={busy !== null}
              style={{
                background: "transparent",
                color: ink,
                border: `1px solid ${border}`,
                borderRadius: compact ? 14 : 18,
                padding: compact ? "12px 16px" : "16px 22px",
                font: `500 ${compact ? 14 : 15}px/1 ${SANS}`,
                cursor: "pointer",
                width: "100%",
              }}
            >
              Try a different key
            </button>
            <button
              type="button"
              onClick={() => {
                setApiKey("");
                onSkip();
              }}
              disabled={busy !== null}
              style={skipStyle}
            >
              Skip for now
            </button>
          </div>
        </>
      )}

      {error && (
        <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: light ? "#C2401F" : "#fbbf24" }}>
          {error}
        </p>
      )}
    </div>
  );
}
