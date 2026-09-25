"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, EmptyState } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost, invalidate } from "@/lib/api";

interface Assertion {
  statement: string;
  predicate: string;
  object: string;
  object_type: string;
  confidence: number;
  relevance: number;
  /** Provenance tag set by the declaring system (twitter/linkedin/github/
   *  mcp/chat/…) — empty for older facts recorded before tagging. */
  source_system?: string;
  /** When the fact was recorded (ISO). */
  observed_at?: string | null;
}

interface MemoryResponse {
  enabled: boolean;
  count: number;
  assertions: Assertion[];
}

// Mirrors backend/agent/memory_context.py's _predicate_label — kept in
// sync by hand since it's just display copy, not logic. Unknown
// predicates fall back to the raw value so nothing is ever hidden.
const PREDICATE_LABEL: Record<string, string> = {
  is_working_on: "Working on",
  is_interested_in: "Interested in",
  is_learning: "Learning",
  has_goal: "Goal",
  has_skill: "Skill",
  uses_tool: "Uses",
  is_affiliated_with: "Affiliated with",
  works_at: "Works at",
  is_studying_at: "Studying at",
  lives_in: "Lives in",
  has_role: "Role",
  prefers: "Prefers",
  dislikes: "Dislikes",
  is_reading: "Reading",
  built: "Built",
  knows: "Knows",
};

function predicateLabel(predicate: string): string {
  return PREDICATE_LABEL[predicate] || predicate;
}

// Provenance labels for the source tag shown on each fact. Unknown or
// missing tags fall back to the raw value / "Learned from chat".
const SOURCE_LABEL: Record<string, string> = {
  twitter: "Twitter",
  linkedin: "LinkedIn",
  github: "GitHub",
  mcp: "MCP",
  user_confirmed: "You",
  "agent-persona": "Chat",
  chatgpt: "Chat",
};

function sourceLabel(source: string | undefined): string {
  if (!source) return "Learned from chat";
  return SOURCE_LABEL[source] || source;
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  if (ms < 0) return "just now";
  const m = Math.floor(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d} day${d === 1 ? "" : "s"} ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo} month${mo === 1 ? "" : "s"} ago`;
  const y = Math.floor(mo / 12);
  return `${y} year${y === 1 ? "" : "s"} ago`;
}

function factKey(a: Assertion): string {
  return `${a.predicate}::${a.object}`;
}

export default function MemoryPage() {
  const { user } = useDashboard();
  const [data, setData] = useState<MemoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await apiGet<MemoryResponse>("/api/memory/", { noCache: true });
        if (!cancelled) setData(r);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Couldn't load your memory.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const handleForget = useCallback(
    async (a: Assertion) => {
      const key = factKey(a);
      setBusyKey(key);
      const prev = data;
      setData((cur) =>
        cur ? { ...cur, assertions: cur.assertions.filter((x) => factKey(x) !== key) } : cur,
      );
      try {
        await apiPost("/api/memory/forget", { predicate: a.predicate, object: a.object });
        invalidate("/api/memory/");
      } catch (e) {
        setData(prev);
        setError(e instanceof Error ? e.message : "Couldn't forget that — try again.");
      } finally {
        setBusyKey(null);
      }
    },
    [data],
  );

  const handleConfirm = useCallback(
    async (a: Assertion) => {
      const key = factKey(a);
      setBusyKey(key);
      const prev = data;
      setData((cur) =>
        cur
          ? {
              ...cur,
              assertions: cur.assertions.map((x) =>
                factKey(x) === key ? { ...x, confidence: 0.97 } : x,
              ),
            }
          : cur,
      );
      try {
        await apiPost("/api/memory/confirm", { predicate: a.predicate, object: a.object });
        invalidate("/api/memory/");
      } catch (e) {
        setData(prev);
        setError(e instanceof Error ? e.message : "Couldn't confirm that — try again.");
      } finally {
        setBusyKey(null);
      }
    },
    [data],
  );

  const grouped = data
    ? data.assertions.reduce<Map<string, Assertion[]>>((map, a) => {
        const list = map.get(a.predicate) || [];
        list.push(a);
        map.set(a.predicate, list);
        return map;
      }, new Map())
    : null;

  return (
    <div className="settings-main">
      <div className="settings-header">
        <h1 className="display-s">Memory</h1>
        <p className="body secondary">
          Facts your persona has picked up from conversation and uses to personalize its
          replies, nudges, and briefs. Confirm the ones that are right so it holds onto them
          with more confidence, or forget anything that&rsquo;s wrong or out of date.
        </p>
      </div>

      {error && <div className="group-composer-error" style={{ margin: "8px 0" }}>{error}</div>}

      {loading ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</p>
      ) : data && !data.enabled ? (
        <EmptyState
          title="Memory isn't turned on yet"
          body="Ask your admin to configure the memory layer — once it's on, facts you mention in chat will start showing up here."
        />
      ) : !grouped || grouped.size === 0 ? (
        <EmptyState
          title="Nothing learned yet"
          body="Chat naturally and I'll start remembering things that matter — what you're working on, your goals, what you're interested in. They'll show up here as we go."
        />
      ) : (
        <ul className="memory-list">
          {Array.from(grouped.entries()).map(([predicate, assertions]) => (
            <li key={predicate} className="memory-section">
              <h4 className="memory-kind">{predicateLabel(predicate)}</h4>
              <ul className="memory-sublist">
                {assertions.map((a) => {
                  const key = factKey(a);
                  const busy = busyKey === key;
                  return (
                    <li key={key} className="memory-row">
                      <div className="memory-row-main">
                        <span className="memory-text">{a.statement || a.object}</span>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                            fontSize: 11,
                            color: "var(--text-muted)",
                          }}
                        >
                          <span
                            style={{
                              padding: "1px 6px",
                              borderRadius: 999,
                              border: "1px solid var(--border)",
                              fontSize: 10,
                              textTransform: "uppercase",
                              letterSpacing: "0.04em",
                            }}
                          >
                            {sourceLabel(a.source_system)}
                          </span>
                          {timeAgo(a.observed_at) && <span>{timeAgo(a.observed_at)}</span>}
                        </div>
                        <div className="memory-confidence" title={`${Math.round(a.confidence * 100)}% confidence`}>
                          <div
                            className="memory-confidence-fill"
                            style={{ width: `${Math.round(a.confidence * 100)}%` }}
                          />
                        </div>
                      </div>
                      <div className="memory-row-actions">
                        <Button
                          size="sm"
                          variant="tertiary"
                          disabled={busy}
                          onClick={() => void handleConfirm(a)}
                        >
                          Confirm
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={busy}
                          onClick={() => void handleForget(a)}
                        >
                          Forget
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
