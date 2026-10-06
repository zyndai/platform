"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  approveSuggestedFact,
  fetchSuggestedFacts,
  revokeSuggestedFact,
  type SuggestedFact,
} from "@/lib/mcp-connector";
import { factLabel } from "@/lib/memory-facts";

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

type Pending = { predicate: string; object: string } | null;

async function sessionToken(): Promise<string> {
  const { data } = await createClient().auth.getSession();
  const t = data.session?.access_token;
  if (!t) throw new Error("Sign in to review your facts.");
  return t;
}

export function SuggestedFactsReview({
  tone = "light",
  onChanged,
}: {
  tone?: "light" | "dark";
  onChanged?: (anyApproved: boolean) => void;
} = {}) {
  const light = tone === "light";
  const [facts, setFacts] = useState<SuggestedFact[] | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const ink = light ? "#0B0B0B" : "#f8fafc";
  const muted = light ? "#6E6E68" : "#94a3b8";
  const border = light ? "#DEDED8" : "rgba(255,255,255,0.12)";
  const fieldBg = light ? "#F7F7F4" : "rgba(15,23,42,0.8)";
  const accent = "#7B72E9";

  // Initial + manual-reload fetch. setState only runs after awaits (async
  // callbacks), which keeps the set-state-in-effect lint rule happy.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const t = await sessionToken();
        const fetched = await fetchSuggestedFacts(t);
        if (!cancelled) setFacts(fetched);
      } catch (err) {
        if (!cancelled) {
          setFacts([]);
          setError(err instanceof Error ? err.message : "Could not load suggested facts");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const reload = useCallback(() => {
    setError("");
    setReloadKey((k) => k + 1);
  }, []);

  const approve = useCallback(async (fact: SuggestedFact) => {
    setPending({ predicate: fact.predicate, object: fact.object });
    setError("");
    try {
      const t = await sessionToken();
      await approveSuggestedFact(t, fact.predicate, fact.object);
      setFacts((prev) =>
        (prev ?? []).filter(
          (f) => !(f.predicate === fact.predicate && f.object === fact.object),
        ),
      );
      onChanged?.(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not publish that fact");
    } finally {
      setPending(null);
    }
  }, [onChanged]);

  const revoke = useCallback(async (fact: SuggestedFact) => {
    setPending({ predicate: fact.predicate, object: fact.object });
    setError("");
    try {
      const t = await sessionToken();
      await revokeSuggestedFact(t, fact.predicate, fact.object);
      onChanged?.(false);
    } catch {
      // "no matching public fact" just means it was never public — refresh.
      reload();
    } finally {
      setPending(null);
    }
  }, [onChanged, reload]);

  const isPending = (fact: SuggestedFact) =>
    pending?.predicate === fact.predicate && pending?.object === fact.object;

  if (facts === null) {
    return <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: muted }}>Loading…</p>;
  }

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ font: `700 22px/1.15 ${DISPLAY}`, color: ink, letterSpacing: "-0.03em" }}>
          Facts waiting for review
        </div>
        <p style={{ margin: "6px 0 0", font: `400 14px/1.55 ${SANS}`, color: muted, maxWidth: 460 }}>
          Your coding agents reported these. Approve to show one on your public card;
          it stays private until you do.
        </p>
      </div>

      {facts.length === 0 ? (
        <div
          style={{
            border: `1px solid ${border}`,
            borderRadius: 14,
            padding: "16px 18px",
            background: fieldBg,
            font: `400 13px/1.5 ${SANS}`,
            color: muted,
          }}
        >
          Nothing to review right now. Connect a coding agent and as it learns durable
          facts about you, they&apos;ll show up here.
        </div>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
          {facts.map((fact) => (
            <li
              key={`${fact.predicate}|${fact.object}`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                border: `1px solid ${border}`,
                borderRadius: 14,
                padding: "12px 16px",
                background: fieldBg,
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ font: `500 14px/1.3 ${SANS}`, color: ink }}>
                  {factLabel(fact)}
                </div>
                <div style={{ font: `400 11px/1.2 ${MONO}`, color: muted, marginTop: 4 }}>
                  {fact.predicate}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button
                  type="button"
                  onClick={() => void approve(fact)}
                  disabled={pending !== null}
                  style={{
                    background: accent,
                    color: "#fff",
                    border: "none",
                    borderRadius: 10,
                    padding: "8px 14px",
                    font: `600 13px/1 ${SANS}`,
                    cursor: pending ? "default" : "pointer",
                    opacity: isPending(fact) ? 0.6 : 1,
                  }}
                >
                  {isPending(fact) ? "Publishing…" : "Show on card"}
                </button>
                <button
                  type="button"
                  onClick={() => void revoke(fact)}
                  disabled={pending !== null}
                  style={{
                    background: "transparent",
                    color: muted,
                    border: `1px solid ${border}`,
                    borderRadius: 10,
                    padding: "8px 14px",
                    font: `500 13px/1 ${SANS}`,
                    cursor: pending ? "default" : "pointer",
                    opacity: isPending(fact) ? 0.6 : 1,
                  }}
                  title="Keep it private and hide it from suggestions later"
                >
                  Keep private
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: light ? "#C2401F" : "#fbbf24" }}>
          {error}
        </p>
      )}
    </div>
  );
}
