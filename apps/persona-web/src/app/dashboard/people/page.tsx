"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Users, Search as SearchIcon, X, ArrowUpRight } from "lucide-react";
import { Avatar, Button, EmptyState } from "@/components/ui";
import IntroPreviewModal from "@/components/chat/IntroPreviewModal";
import { useDashboard } from "@/contexts/DashboardContext";
import { getSupabase } from "@/lib/supabase";
import type { PersonaHit } from "@/components/chat/types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SearchResponse {
  status?: string;
  count?: number;
  results?: PersonaHit[];
  error?: string;
}

const PRESET_FILTERS: { label: string; query: string }[] = [
  { label: "Founders",    query: "founder" },
  { label: "Engineers",   query: "engineer" },
  { label: "Designers",   query: "designer" },
  { label: "Investors",   query: "investor" },
  { label: "Researchers", query: "research" },
];

export default function PeoplePage() {
  const { user } = useDashboard();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [results, setResults] = useState<PersonaHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [introTarget, setIntroTarget] = useState<PersonaHit | null>(null);
  const [myAgentId, setMyAgentId] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve the current user's agent_id so we can flag "(you)" on the
  // own card and link to its public view instead of starting a thread
  // with yourself. Cached for the page lifetime.
  useEffect(() => {
    if (!user?.id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/persona/${user.id}/status`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (data?.agent_id && !cancelled) setMyAgentId(data.agent_id);
      } catch {
        /* ignore — at worst the user's own row just won't be flagged */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  const runSearch = useCallback(async (q: string) => {
    setLoading(true);
    setError(null);
    setActiveQuery(q);
    // Hard-cap the wait. The backend proxies the Zynd registry which can
    // be slow or unavailable — without a timeout the UI would sit on
    // "Searching the network…" forever. 8s is enough for the happy path
    // and short enough to surface a useful error.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const url = `${API}/api/persona/search?query=${encodeURIComponent(q || "persona")}&limit=20`;
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(await res.text());
      const data: SearchResponse = await res.json();
      if (data.error) {
        setError(data.error);
        setResults([]);
      } else {
        setResults((data.results || []).filter((p) => !!p.agent_id));
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setError(
          "The network registry didn't respond in time. Try again in a moment.",
        );
      } else {
        setError(e instanceof Error ? e.message : "Search failed.");
      }
      setResults([]);
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }, []);

  // Debounced keystroke handler — empty input falls back to a default
  // "persona" query so the page never renders a blank surface.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = query.trim();
    const delay = q.length === 0 ? 0 : 300;
    debounceRef.current = setTimeout(() => void runSearch(q), delay);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, runSearch]);

  const myName = useMemo(
    () =>
      user?.user_metadata?.full_name ||
      user?.user_metadata?.name ||
      user?.email?.split("@")[0] ||
      "I",
    [user],
  );

  const sendIntro = useCallback(
    async (message: string): Promise<string> => {
      if (!user || !introTarget) throw new Error("Not signed in.");
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const jwt = session?.access_token;
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (jwt) headers["Authorization"] = `Bearer ${jwt}`;

      const tRes = await fetch(`${API}/api/persona/${user.id}/threads`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          target_agent_id: introTarget.agent_id,
          target_name: introTarget.name || "Network Agent",
          mode: "agent",
        }),
      });
      if (!tRes.ok) throw new Error(await tRes.text());
      const tid = (await tRes.json())?.thread?.id as string | undefined;
      if (!tid) throw new Error("Couldn't open the thread.");

      const sRes = await fetch(`${API}/api/persona/${user.id}/agent-send`, {
        method: "POST",
        headers,
        body: JSON.stringify({ thread_id: tid, content: message }),
      });
      if (!sRes.ok) throw new Error(await sRes.text());
      return tid;
    },
    [user, introTarget],
  );

  const onIntroSent = useCallback(
    (threadId: string) => {
      setIntroTarget(null);
      router.push(`/dashboard/messages?thread=${threadId}`);
    },
    [router],
  );

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "40px 32px 56px", width: "100%" }}>
      <h1 className="display-m" style={{ margin: "0 0 8px" }}>People on the network</h1>
      <p style={{ margin: "0 0 24px", color: "var(--text-secondary)", fontSize: 15, lineHeight: 1.55 }}>
        Search Zynd&apos;s open registry for agents you might want to meet. Your agent talks to
        theirs first — no cold DMs.
      </p>

      <div className="people-search">
        <SearchIcon size={16} strokeWidth={1.7} />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, keyword, role, or topic"
          aria-label="Search the Zynd network"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="people-search-clear"
          >
            <X size={14} strokeWidth={1.8} />
          </button>
        )}
      </div>

      <div className="people-presets">
        {PRESET_FILTERS.map((f) => {
          const active = query.trim().toLowerCase() === f.query.toLowerCase();
          return (
            <button
              key={f.label}
              type="button"
              onClick={() => setQuery(f.query)}
              className={`people-preset ${active ? "active" : ""}`}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {error && (
        <div
          style={{
            padding: "10px 14px",
            marginBottom: 16,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-sm)",
            color: "var(--text-secondary)",
            fontSize: 13,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void runSearch(query.trim())}
            style={{ fontSize: 12, padding: "4px 12px", whiteSpace: "nowrap" }}
          >
            Retry
          </button>
        </div>
      )}

      {loading && results.length === 0 ? (
        <ul className="people-list" aria-busy="true">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i} className="people-card people-card-skeleton">
              <span className="people-card-avatar-skel" />
              <div className="people-card-body">
                <span className="people-card-skel-line people-card-skel-name" />
                <span className="people-card-skel-line people-card-skel-desc" />
              </div>
            </li>
          ))}
        </ul>
      ) : results.length === 0 ? (
        <EmptyState
          illustration={<Users />}
          title={activeQuery ? "Nobody matched that search." : "Quiet on the network today."}
          body={
            activeQuery
              ? "Try a different keyword, or check back later — new agents join all the time."
              : "Your agent will message you when someone good shows up. In the meantime, share your card so people can find you."
          }
          action={
            !activeQuery && user?.id ? (
              <Link href={`/p/${user.id}`} target="_blank" rel="noopener noreferrer">
                <Button variant="secondary">Open my public card →</Button>
              </Link>
            ) : null
          }
        />
      ) : (
        <>
          <p className="people-count">
            {results.length} {results.length === 1 ? "agent" : "agents"}
            {activeQuery && activeQuery !== "persona" && (
              <span style={{ color: "var(--text-muted)" }}>
                {" "}· matching <em>{activeQuery}</em>
              </span>
            )}
          </p>
          <ul className="people-list" aria-busy={loading}>
            {results.map((p) => {
              const isMe = p.agent_id === myAgentId;
              return (
                <li key={p.agent_id} className="people-card">
                  <Avatar
                    size="md"
                    name={p.name || "?"}
                    src={p.avatar_url || undefined}
                    variant="accent"
                  />
                  <div className="people-card-body">
                    <div className="people-card-name">
                      {p.name || "Someone on the network"}
                      {isMe && <span className="people-card-you">you</span>}
                    </div>
                    {p.description ? (
                      <p className="people-card-desc">{p.description}</p>
                    ) : (
                      <p className="people-card-desc people-card-desc-empty">
                        No bio yet.
                      </p>
                    )}
                  </div>
                  <div className="people-card-actions">
                    {isMe ? (
                      <Link
                        href={`/p/${user?.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-secondary btn-sm"
                        style={{
                          textDecoration: "none",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        View card
                        <ArrowUpRight size={13} strokeWidth={1.8} />
                      </Link>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => setIntroTarget(p)}
                        disabled={!user?.id}
                      >
                        Say hi →
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {introTarget && (
        <IntroPreviewModal
          target={introTarget}
          myName={myName}
          onClose={() => setIntroTarget(null)}
          onSent={onIntroSent}
          send={sendIntro}
        />
      )}
    </div>
  );
}
