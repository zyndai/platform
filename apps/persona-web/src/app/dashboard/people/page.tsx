"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  Compass,
  FlaskConical,
  Globe2,
  Handshake,
  Lightbulb,
  MessageCircle,
  Palette,
  RefreshCw,
  Search as SearchIcon,
  Users,
  X,
} from "lucide-react";
import { Avatar, Button, EmptyState } from "@/components/ui";
import IntroPreviewModal from "@/components/chat/IntroPreviewModal";
import { useDashboard } from "@/contexts/DashboardContext";
import {
  discoverPeople,
  getPeopleMe,
  sendPeopleIntroduction,
  type PeopleDiscoverResponse,
} from "@/lib/people-api";
import type { PersonaHit } from "@/components/chat/types";

const PRESET_FILTERS = [
  { label: "Founders",    query: "founder",  icon: BriefcaseBusiness },
  { label: "Engineers",   query: "engineer", icon: Lightbulb },
  { label: "Designers",   query: "designer", icon: Palette },
  { label: "Investors",   query: "investor", icon: Handshake },
  { label: "Researchers", query: "research", icon: FlaskConical },
];

const QUICK_STARTS = [
  { label: "Find a cofounder", detail: "builders and operators", query: "founder", icon: BriefcaseBusiness },
  { label: "Talk to investors", detail: "fundraising context", query: "investor", icon: Handshake },
  { label: "Review an idea", detail: "product feedback", query: "product", icon: Lightbulb },
  { label: "Meet designers", detail: "brand and UX people", query: "designer", icon: Palette },
  { label: "Explore research", detail: "papers and labs", query: "research", icon: FlaskConical },
  { label: "Practice outreach", detail: "sales and partnerships", query: "sales", icon: MessageCircle },
];

type PeopleSectionModel = {
  key: string;
  title: string;
  items: PersonaHit[];
  variant?: "compact" | "featured";
};

function buildPeopleSections(results: PersonaHit[]): PeopleSectionModel[] {
  const sections: PeopleSectionModel[] = [
    { key: "for-you", title: "For you", items: results.slice(0, 4), variant: "featured" },
    { key: "featured", title: "Featured", items: results.slice(4, 8) },
    { key: "popular", title: "Popular", items: results.slice(8, 12) },
    { key: "more", title: "More to meet", items: results.slice(12, 24) },
  ];
  return sections.filter((section) => section.items.length > 0);
}

function sourceLabel(meta: PeopleDiscoverResponse | null): string {
  if (!meta?.source) return "Network";
  if (meta.source === "registry") return "Live registry";
  if (meta.source === "local_db") return "Local fallback";
  return "Network";
}

export default function PeoplePage() {
  const { user } = useDashboard();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [results, setResults] = useState<PersonaHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchMeta, setSearchMeta] = useState<PeopleDiscoverResponse | null>(null);
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
        const data = await getPeopleMe();
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
    if (!user?.id) return;
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
      const data = await discoverPeople(q || "persona", 24, controller.signal);
      setSearchMeta(data);
      if (data.error) {
        setError(data.error);
        setResults([]);
      } else {
        setResults((data.results || []).filter((p) => !!p.agent_id));
      }
    } catch (e) {
      setSearchMeta(null);
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
  }, [user?.id]);

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
  const firstName = useMemo(() => String(myName).split(/\s+/)[0] || "there", [myName]);
  const sections = useMemo(() => buildPeopleSections(results), [results]);

  const sendIntro = useCallback(
    async (message: string): Promise<string> => {
      if (!user || !introTarget) throw new Error("Not signed in.");
      const intro = await sendPeopleIntroduction({
        targetAgentId: introTarget.agent_id,
        targetName: introTarget.name || "Network Agent",
        message,
      });
      const tid = intro.thread_id || intro.thread?.id;
      if (!tid) throw new Error("Couldn't open the thread.");
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
    <div className="people-discover-shell">
      <header className="people-discover-header">
        <div className="people-welcome">
          <span>Welcome,</span>
          <strong>{firstName}</strong>
          <div className="people-header-meta">
            <span>
              <Compass size={13} strokeWidth={1.8} />
              People
            </span>
            <span>
              <Globe2 size={13} strokeWidth={1.8} />
              {sourceLabel(searchMeta)}
            </span>
          </div>
        </div>

        <div className="people-toolbar">
          <div className="people-search people-search-hero">
            <SearchIcon size={18} strokeWidth={1.8} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search roles, topics, companies, or names"
              aria-label="Search the Zynd network"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Clear search"
                className="people-search-clear"
              >
                <X size={15} strokeWidth={1.8} />
              </button>
            )}
          </div>
          <div className="people-toolbar-actions">
            <button
              type="button"
              onClick={() => void runSearch(query.trim())}
              className="people-toolbar-icon"
              disabled={loading}
              aria-label="Refresh people"
              title="Refresh people"
            >
              <RefreshCw className={loading ? "is-spinning" : ""} size={16} strokeWidth={1.8} />
            </button>
            {user?.id && (
              <Link
                href={`/p/${user.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="people-toolbar-link"
              >
                <ArrowUpRight size={14} strokeWidth={1.8} />
                My card
              </Link>
            )}
          </div>
        </div>
      </header>

      <div className="people-presets" aria-label="Suggested searches">
        {PRESET_FILTERS.map((f) => {
          const active = query.trim().toLowerCase() === f.query.toLowerCase();
          const Icon = f.icon;
          return (
            <button
              key={f.label}
              type="button"
              onClick={() => setQuery(f.query)}
              className={`people-preset ${active ? "active" : ""}`}
            >
              <Icon size={14} strokeWidth={1.8} />
              {f.label}
            </button>
          );
        })}
      </div>

      {error && (
        <div className="people-error">
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void runSearch(query.trim())}
          >
            Retry
          </button>
        </div>
      )}

      {loading && results.length === 0 ? (
        <section className="people-section" aria-busy="true">
          <h2>For you</h2>
          <ul className="people-row people-row-compact">
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
        </section>
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
          <div className="people-count">
            <span>{results.length} {results.length === 1 ? "agent" : "agents"}</span>
            {activeQuery && activeQuery !== "persona" && (
              <em>matching {activeQuery}</em>
            )}
            {searchMeta?.from_cache && <small>cached</small>}
          </div>

          {sections[0] && (
            <PeopleSection
              title={sections[0].title}
              items={sections[0].items}
              variant={sections[0].variant}
              myAgentId={myAgentId}
              userId={user?.id}
              onIntro={setIntroTarget}
            />
          )}

          <QuickStarts onPick={setQuery} />

          {sections.slice(1).map((section) => (
            <PeopleSection
              key={section.key}
              title={section.title}
              items={section.items}
              variant={section.variant}
              myAgentId={myAgentId}
              userId={user?.id}
              onIntro={setIntroTarget}
            />
          ))}
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

function PeopleSection({
  title,
  items,
  variant = "compact",
  myAgentId,
  userId,
  onIntro,
}: {
  title: string;
  items: PersonaHit[];
  variant?: "compact" | "featured";
  myAgentId: string | null;
  userId: string | undefined;
  onIntro: (hit: PersonaHit) => void;
}) {
  if (!items.length) return null;
  return (
    <section className="people-section">
      <div className="people-section-head">
        <h2>{title}</h2>
        <span>{items.length}</span>
      </div>
      <ul className={`people-row ${variant === "featured" ? "people-row-featured" : ""}`}>
        {items.map((p) => (
          <PeopleCard
            key={`${title}-${p.agent_id}`}
            hit={p}
            featured={variant === "featured"}
            isMe={p.agent_id === myAgentId}
            userId={userId}
            onIntro={onIntro}
          />
        ))}
      </ul>
    </section>
  );
}

function PeopleCard({
  hit,
  featured,
  isMe,
  userId,
  onIntro,
}: {
  hit: PersonaHit;
  featured: boolean;
  isMe: boolean;
  userId: string | undefined;
  onIntro: (hit: PersonaHit) => void;
}) {
  const name = hit.name || "Someone on the network";
  return (
    <li className={`people-card ${featured ? "people-card-featured" : ""}`}>
      <Avatar
        size="xl"
        name={name}
        src={hit.avatar_url || undefined}
        variant="accent"
      />
      <div className="people-card-body">
        <div className="people-card-name-row">
          <span className="people-card-name">{name}</span>
          {isMe && <span className="people-card-you">you</span>}
        </div>
        {hit.description ? (
          <p className="people-card-desc">{hit.description}</p>
        ) : (
          <p className="people-card-desc people-card-desc-empty">No bio yet.</p>
        )}
      </div>
      <div className="people-card-cta-wrap">
        {isMe && userId ? (
          <Link
            href={`/p/${userId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="people-card-cta"
          >
            <ArrowUpRight size={14} strokeWidth={1.8} />
            View card
          </Link>
        ) : !isMe ? (
          <button
            type="button"
            className="people-card-cta"
            onClick={() => onIntro(hit)}
            disabled={!userId}
          >
            <MessageCircle size={14} strokeWidth={1.8} />
            Say hi
          </button>
        ) : null}
      </div>
    </li>
  );
}

function QuickStarts({ onPick }: { onPick: (query: string) => void }) {
  return (
    <section className="people-section">
      <h2>Try these</h2>
      <ul className="people-quick-grid">
        {QUICK_STARTS.map((item) => {
          const Icon = item.icon;
          return (
            <li key={item.label}>
              <button type="button" onClick={() => onPick(item.query)} className="people-quick-card">
                <span className="people-quick-icon">
                  <Icon size={18} strokeWidth={1.8} />
                </span>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
