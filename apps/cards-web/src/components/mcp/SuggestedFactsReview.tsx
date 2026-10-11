"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import {
  approveSuggestedFact,
  dismissSuggestedFact,
  fetchSuggestedFacts,
  type MemorySnapshot,
  type SuggestedFact,
  type SuggestionGroup,
} from "@/lib/mcp-connector";
import { factLabel, MEMORY_GROUPS } from "@/lib/memory-facts";

const SANS = "var(--zc-sans), system-ui, -apple-system, sans-serif";
const DISPLAY = "var(--zc-display), system-ui, sans-serif";
const MONO = "var(--zc-mono), ui-monospace, monospace";

const GROUP_META: Record<SuggestionGroup, { title: string; hint: string }> = {
  right: { title: "Looks right", hint: "Ready to publish as shown." },
  look: { title: "Needs a look", hint: "Retype or confirm before publishing." },
  noise: {
    title: "Probably noise",
    hint: "Repo paths, jargon, or junk — dismiss unless you disagree.",
  },
};

const RETYPE_OPTIONS = [
  "has_expertise_in",
  "is_building",
  "is_learning",
  "is_affiliated_with",
  "is_located_in",
  "is_seeking",
  "open_to",
] as const;

type Pending = { predicate: string; object: string; action: "publish" | "dismiss" } | null;

async function sessionToken(): Promise<string> {
  const { data } = await createClient().auth.getSession();
  const t = data.session?.access_token;
  if (!t) throw new Error("Sign in to review your facts.");
  return t;
}

function groupOf(fact: SuggestedFact): SuggestionGroup {
  return fact.group === "look" || fact.group === "noise" ? fact.group : "right";
}

function showsAs(fact: SuggestedFact, asPredicate: string): string {
  if (
    fact.public_label &&
    asPredicate === (fact.suggested_predicate || fact.predicate)
  ) {
    return fact.public_label;
  }
  return factLabel({ predicate: asPredicate, object: fact.object });
}

export function SuggestedFactsReview({
  tone = "light",
  onChanged,
}: {
  tone?: "light" | "dark";
  onChanged?: (snapshot: MemorySnapshot) => void;
} = {}) {
  const light = tone === "light";
  const [facts, setFacts] = useState<SuggestedFact[] | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState("");
  const [retype, setRetype] = useState<Record<string, string>>({});
  const [openNoise, setOpenNoise] = useState(false);

  const ink = light ? "#0B0B0B" : "#f8fafc";
  const muted = light ? "#6E6E68" : "#94a3b8";
  const border = light ? "#DEDED8" : "rgba(255,255,255,0.12)";
  const fieldBg = light ? "#F7F7F4" : "rgba(15,23,42,0.8)";
  const accent = "#7B72E9";

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
  }, []);

  const removeLocal = useCallback((fact: SuggestedFact) => {
    setFacts((prev) =>
      (prev ?? []).filter(
        (f) => !(f.predicate === fact.predicate && f.object === fact.object),
      ),
    );
  }, []);

  const factKey = (fact: SuggestedFact) => `${fact.predicate}|${fact.object}`;

  const chosenPredicate = useCallback(
    (fact: SuggestedFact) =>
      retype[`${fact.predicate}|${fact.object}`] ||
      fact.suggested_predicate ||
      fact.predicate,
    [retype],
  );

  const approve = useCallback(
    async (fact: SuggestedFact) => {
      setPending({ predicate: fact.predicate, object: fact.object, action: "publish" });
      setError("");
      try {
        const t = await sessionToken();
        const asPred = chosenPredicate(fact);
        const snapshot = await approveSuggestedFact(
          t,
          fact.predicate,
          fact.object,
          asPred !== fact.predicate ? asPred : undefined,
        );
        removeLocal(fact);
        onChanged?.(snapshot);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not publish that fact");
      } finally {
        setPending(null);
      }
    },
    [chosenPredicate, onChanged, removeLocal],
  );

  const dismissOne = useCallback(
    async (fact: SuggestedFact) => {
      setPending({ predicate: fact.predicate, object: fact.object, action: "dismiss" });
      setError("");
      try {
        const t = await sessionToken();
        await dismissSuggestedFact(t, fact.predicate, fact.object);
        removeLocal(fact);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not dismiss that fact");
      } finally {
        setPending(null);
      }
    },
    [removeLocal],
  );

  const grouped = useMemo(() => {
    const buckets: Record<SuggestionGroup, SuggestedFact[]> = {
      right: [],
      look: [],
      noise: [],
    };
    for (const fact of facts ?? []) buckets[groupOf(fact)].push(fact);
    return buckets;
  }, [facts]);

  const isPending = (fact: SuggestedFact, action?: "publish" | "dismiss") =>
    pending?.predicate === fact.predicate &&
    pending?.object === fact.object &&
    (action ? pending.action === action : true);

  if (facts === null) {
    return <p style={{ margin: 0, font: `400 13px/1.5 ${SANS}`, color: muted }}>Loading…</p>;
  }

  const renderRow = (fact: SuggestedFact) => {
    const asPred = chosenPredicate(fact);
    return (
      <li
        key={factKey(fact)}
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          border: `1px solid ${border}`,
          borderRadius: 14,
          padding: "12px 16px",
          background: fieldBg,
        }}
      >
        <div style={{ minWidth: 0, flex: "1 1 180px" }}>
          <div style={{ font: `500 14px/1.3 ${SANS}`, color: ink }}>{factLabel(fact)}</div>
          <div style={{ font: `400 12px/1.4 ${SANS}`, color: muted, marginTop: 4 }}>
            Shows as: <span style={{ color: ink }}>{showsAs(fact, asPred)}</span>
          </div>
          <div style={{ font: `400 11px/1.2 ${MONO}`, color: muted, marginTop: 4 }}>
            {fact.predicate}
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <select
            aria-label="Retype before publish"
            value={asPred}
            disabled={pending !== null}
            onChange={(e) =>
              setRetype((prev) => ({ ...prev, [factKey(fact)]: e.target.value }))
            }
            style={{
              border: `1px solid ${border}`,
              borderRadius: 10,
              padding: "8px 10px",
              font: `400 12px/1 ${SANS}`,
              background: light ? "#fff" : "rgba(15,23,42,0.9)",
              color: ink,
              maxWidth: 160,
            }}
          >
            {RETYPE_OPTIONS.map((pred) => (
              <option key={pred} value={pred}>
                {MEMORY_GROUPS[pred]?.label ?? pred}
              </option>
            ))}
            {!RETYPE_OPTIONS.includes(asPred as (typeof RETYPE_OPTIONS)[number]) && (
              <option value={asPred}>{asPred}</option>
            )}
          </select>
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
              opacity: isPending(fact, "publish") ? 0.6 : 1,
            }}
          >
            {isPending(fact, "publish") ? "Publishing…" : "Publish"}
          </button>
          <button
            type="button"
            onClick={() => void dismissOne(fact)}
            disabled={pending !== null}
            style={{
              background: "transparent",
              color: light ? "#C2401F" : "#fbbf24",
              border: `1px solid ${light ? "#E8B4A3" : "rgba(251,191,36,0.35)"}`,
              borderRadius: 10,
              padding: "8px 14px",
              font: `500 13px/1 ${SANS}`,
              cursor: pending ? "default" : "pointer",
              opacity: isPending(fact, "dismiss") ? 0.6 : 1,
            }}
            title="Keep private and hide from this inbox permanently"
          >
            {isPending(fact, "dismiss") ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      </li>
    );
  };

  const renderGroup = (key: SuggestionGroup) => {
    const items = grouped[key];
    if (items.length === 0) return null;
    const meta = GROUP_META[key];
    const collapsed = key === "noise" && !openNoise;
    return (
      <section key={key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <div>
            <div style={{ font: `600 15px/1.3 ${SANS}`, color: ink }}>
              {meta.title}
              <span style={{ font: `400 12px/1 ${SANS}`, color: muted, marginLeft: 8 }}>
                {items.length}
              </span>
            </div>
            <div style={{ font: `400 12px/1.4 ${SANS}`, color: muted }}>{meta.hint}</div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {key === "noise" && (
              <button
                type="button"
                onClick={() => setOpenNoise((v) => !v)}
                style={{
                  background: "transparent",
                  border: `1px solid ${border}`,
                  borderRadius: 10,
                  padding: "6px 10px",
                  font: `500 12px/1 ${SANS}`,
                  color: muted,
                  cursor: "pointer",
                }}
              >
                {openNoise ? "Collapse" : "Expand"}
              </button>
            )}
            {key !== "noise" && (
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => {
                  void (async () => {
                    for (const fact of items) await approve(fact);
                  })();
                }}
                style={{
                  background: accent,
                  color: "#fff",
                  border: "none",
                  borderRadius: 10,
                  padding: "6px 12px",
                  font: `600 12px/1 ${SANS}`,
                  cursor: pending ? "default" : "pointer",
                }}
              >
                Publish all
              </button>
            )}
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => {
                void (async () => {
                  for (const fact of items) await dismissOne(fact);
                })();
              }}
              style={{
                background: "transparent",
                border: `1px solid ${border}`,
                borderRadius: 10,
                padding: "6px 12px",
                font: `500 12px/1 ${SANS}`,
                color: muted,
                cursor: pending ? "default" : "pointer",
              }}
            >
              Dismiss all
            </button>
          </div>
        </div>
        {!collapsed && (
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {items.map(renderRow)}
          </ul>
        )}
      </section>
    );
  };

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div style={{ font: `700 22px/1.15 ${DISPLAY}`, color: ink, letterSpacing: "-0.03em" }}>
          Facts waiting for review
        </div>
        <p style={{ margin: "6px 0 0", font: `400 14px/1.55 ${SANS}`, color: muted, maxWidth: 520 }}>
          Your coding agents reported these. Publish to show one on your public card;
          Dismiss keeps it private and hides it from this inbox permanently.
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
          facts about you at milestones, they&apos;ll show up here — already triaged.
        </div>
      ) : (
        <>
          {renderGroup("right")}
          {renderGroup("look")}
          {renderGroup("noise")}
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
