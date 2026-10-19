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

// Styled by the card editor's edit.css (pe-* classes).

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
  onChanged,
  onCount,
}: {
  onChanged?: (snapshot: MemorySnapshot) => void | Promise<void>;
  /** How many facts are still waiting, whenever that changes. */
  onCount?: (count: number) => void;
} = {}) {
  const [facts, setFacts] = useState<SuggestedFact[] | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState("");
  const [retype, setRetype] = useState<Record<string, string>>({});
  const [openNoise, setOpenNoise] = useState(false);

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

  useEffect(() => {
    if (facts) onCount?.(facts.length);
  }, [facts, onCount]);

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
    async (fact: SuggestedFact): Promise<boolean> => {
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
        await onChanged?.(snapshot);
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not publish that fact");
        return false;
      } finally {
        setPending(null);
      }
    },
    [chosenPredicate, onChanged, removeLocal],
  );

  const dismissOne = useCallback(
    async (fact: SuggestedFact): Promise<boolean> => {
      setPending({ predicate: fact.predicate, object: fact.object, action: "dismiss" });
      setError("");
      try {
        const t = await sessionToken();
        await dismissSuggestedFact(t, fact.predicate, fact.object);
        removeLocal(fact);
        return true;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not dismiss that fact");
        return false;
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
    return <p className="pe-note">Loading…</p>;
  }

  const renderRow = (fact: SuggestedFact) => {
    const asPred = chosenPredicate(fact);
    const label = factLabel(fact);
    const shown = showsAs(fact, asPred);
    return (
      <li key={factKey(fact)} className="pe-review-row">
        <div className="pe-review-text">
          <div className="pe-review-label" title={fact.predicate}>{label}</div>
          {shown !== label && <div className="pe-review-shows">Shows as: {shown}</div>}
        </div>
        <div className="pe-review-actions">
          <select
            aria-label="Retype before publish"
            className="pe-select pe-select-sm"
            value={asPred}
            disabled={pending !== null}
            onChange={(e) =>
              setRetype((prev) => ({ ...prev, [factKey(fact)]: e.target.value }))
            }
            style={{ maxWidth: 170 }}
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
            className="pe-btn pe-btn-primary pe-btn-sm"
            onClick={() => void approve(fact)}
            disabled={pending !== null}
          >
            {isPending(fact, "publish") ? "Publishing…" : "Publish"}
          </button>
          <button
            type="button"
            className="pe-btn pe-btn-danger pe-btn-sm"
            onClick={() => void dismissOne(fact)}
            disabled={pending !== null}
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
      <section key={key} className="pe-review-group">
        <div className="pe-review-group-head">
          <div>
            <h3 className="pe-review-group-title">
              {meta.title} <span className="pe-count">{items.length}</span>
            </h3>
            <p className="pe-note">{meta.hint}</p>
          </div>
          <div className="pe-row">
            {key === "noise" && (
              <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={() => setOpenNoise((v) => !v)}>
                {openNoise ? "Collapse" : "Expand"}
              </button>
            )}
            <button
              type="button"
              className="pe-btn pe-btn-secondary pe-btn-sm"
              disabled={pending !== null}
              onClick={() => {
                void (async () => {
                  const failed: string[] = [];
                  for (const fact of items) {
                    if (!(await dismissOne(fact))) failed.push(factLabel(fact));
                  }
                  if (failed.length) {
                    setError(
                      `Dismissed ${items.length - failed.length} of ${items.length}. ` +
                        `Could not dismiss: ${failed.join(", ")}`,
                    );
                  }
                })();
              }}
            >
              Dismiss all
            </button>
          </div>
        </div>
        {!collapsed && <ul className="pe-mem-items">{items.map(renderRow)}</ul>}
      </section>
    );
  };

  return (
    <div className="pe-review">
      {facts.length === 0 ? (
        <p className="pe-empty">
          Nothing to review. When a connected assistant learns something lasting about you, it shows up here.
        </p>
      ) : (
        <>
          {renderGroup("right")}
          {renderGroup("look")}
          {renderGroup("noise")}
        </>
      )}

      {error && <p role="alert" className="pe-error">{error}</p>}
    </div>
  );
}
