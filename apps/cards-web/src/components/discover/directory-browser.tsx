"use client";

import { useEffect, useMemo, useRef, useState, useTransition, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, MapPin, Search, SearchX, TriangleAlert, X } from "lucide-react";
import { PersonAvatar } from "./person-avatar";
import { RankedResults, type RankedRow } from "./ranked-results";
import { DEFAULT_LIMIT, REFINEMENTS, hasTerm, matchHref, toggleTerm } from "./search-terms";

export interface DirectoryPerson {
  id: string;
  href: string;
  name: string;
  headline: string;
  location: string;
  avatar?: string;
  claimed: boolean;
  skills: { name: string; href: string }[];
  moreSkills: number;
}

/** A ranked search, answered by the server (?match=1). */
export interface RankedSearch {
  query: string;
  limit: number;
  /** null when the search service could not be reached. */
  rows: RankedRow[] | null;
}

/** Lower-case and strip accents, so "jose" finds "José". */
const fold = (value: string) => value.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** The name with the searched words marked. */
function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const folded = fold(text);
  // Folding can change the length in some scripts; skip the marks rather than misplace them.
  if (!terms.length || folded.length !== text.length) return <>{text}</>;
  const hit = new Array<boolean>(text.length).fill(false);
  for (const term of terms) {
    for (let at = folded.indexOf(term); at !== -1; at = folded.indexOf(term, at + term.length)) {
      hit.fill(true, at, at + term.length);
    }
  }
  const parts: ReactNode[] = [];
  for (let start = 0, end = 0; start < text.length; start = end) {
    end = start;
    while (end < text.length && hit[end] === hit[start]) end++;
    const piece = text.slice(start, end);
    parts.push(hit[start] ? <mark className="dc-mark" key={start}>{piece}</mark> : piece);
  }
  return <>{parts}</>;
}

/**
 * The directory: one search box with two ways to use it.
 *
 * Typing filters the people already on the page by name, instantly; the form
 * still works as a plain GET (?q=) before the script loads, and the query stays
 * in the address bar. The refine chips and "Search by skills, location or
 * availability" instead ask the server to rank people (?match=1), and that
 * answer replaces the grid with matches, scores and reasons.
 */
export function DirectoryBrowser({
  people,
  initialQuery,
  ranked,
  intro,
}: {
  people: DirectoryPerson[];
  initialQuery: string;
  ranked: RankedSearch | null;
  intro: ReactNode;
}) {
  const router = useRouter();
  const [busy, startTransition] = useTransition();
  const [query, setQuery] = useState(initialQuery);
  const inputRef = useRef<HTMLInputElement>(null);

  // A navigation (back button, a chip) brings a new query from the server; show it.
  const [seenQuery, setSeenQuery] = useState(initialQuery);
  if (seenQuery !== initialQuery) {
    setSeenQuery(initialQuery);
    setQuery(initialQuery);
  }

  const terms = useMemo(() => fold(query).split(/\s+/).filter(Boolean), [query]);
  const indexed = useMemo(() => people.map((person) => ({ person, haystack: fold(person.name) })), [people]);
  const visible = useMemo(
    () => (terms.length
      ? indexed.filter(({ haystack }) => terms.every((term) => haystack.includes(term))).map(({ person }) => person)
      : people),
    [indexed, people, terms],
  );

  // Keep a name search in the address bar so a filtered view can be shared.
  // A ranked search is already in it, and one that is loading must not be overwritten.
  useEffect(() => {
    if (ranked || busy) return;
    const url = new URL(window.location.href);
    const next = query.trim();
    if ((url.searchParams.get("q") ?? "") === next) return;
    if (next) url.searchParams.set("q", next);
    else url.searchParams.delete("q");
    window.history.replaceState(null, "", url);
  }, [query, ranked, busy]);

  // "/" jumps to the search from anywhere that is not already a text field.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      event.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const trimmed = query.trim();

  const browse = () => {
    setQuery("");
    startTransition(() => router.push("/directory"));
  };
  const runMatch = (text: string, limit: number = ranked?.limit ?? DEFAULT_LIMIT) => {
    const next = text.trim();
    if (!next) return browse();
    setQuery(next);
    startTransition(() => router.push(matchHref(next, limit)));
  };
  /** Add the chip's word to the search, or take it out again once the matches are showing. */
  const matchTyped = () => (trimmed ? runMatch(query) : inputRef.current?.focus());
  const refine = (term: string) => runMatch(ranked || !hasTerm(query, term) ? toggleTerm(query, term) : query);
  const clear = () => {
    if (ranked) browse();
    else setQuery("");
    inputRef.current?.focus();
  };

  return (
    <>
      <section className="dc-hero">
        <div className="dc-hero-copy">{intro}</div>
        <div className="dc-hero-tools">
          <form
            className="dc-search"
            role="search"
            method="get"
            action="/directory"
            onSubmit={(event) => {
              event.preventDefault();
              if (ranked) runMatch(query);
            }}
          >
            <Search className="dc-search-icon" size={20} aria-hidden="true" />
            <label htmlFor="dc-name-search" className="dc-sr">Search people by name</label>
            <input
              id="dc-name-search"
              ref={inputRef}
              className="dc-search-input"
              type="search"
              name="q"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape" && (query || ranked)) {
                  event.preventDefault();
                  clear();
                }
              }}
              placeholder="Search people by name"
              autoComplete="off"
              spellCheck={false}
            />
            {query || ranked ? (
              <button type="button" className="dc-icon-btn" aria-label="Clear search" onClick={clear}>
                <X size={16} aria-hidden="true" />
              </button>
            ) : (
              <kbd className="dc-kbd" aria-hidden="true">/</kbd>
            )}
            <button type="submit" className="dc-btn dc-btn-primary dc-search-submit">
              <Search size={16} aria-hidden="true" />
              Search
            </button>
          </form>

          <div className="dc-refine" role="group" aria-label="Refine the search">
            <span className="dc-label">Refine</span>
            {REFINEMENTS.map(({ label, term }) => {
              const on = Boolean(ranked) && hasTerm(query, term);
              return (
                <button key={term} type="button" className="dc-toggle" aria-pressed={on} onClick={() => refine(term)}>
                  {label}
                </button>
              );
            })}
          </div>

          {!ranked && (
            <div className="dc-status" aria-live="polite">
              <span>
                {terms.length
                  ? `${visible.length} of ${people.length} match`
                  : `${people.length} ${people.length === 1 ? "person" : "people"}`}
              </span>
              <button type="button" className="dc-linkbtn" onClick={matchTyped}>
                Search by skills, location or availability →
              </button>
            </div>
          )}
        </div>
      </section>

      <div className={busy ? "dc-busy" : undefined} aria-busy={busy}>
        {ranked ? (
          ranked.rows === null ? (
            <div className="dc-empty dc-error" role="alert">
              <span className="dc-empty-icon"><TriangleAlert size={24} aria-hidden="true" /></span>
              <div className="dc-empty-title">Search unavailable</div>
              <p className="dc-empty-text">Try again shortly.</p>
              <div className="dc-empty-actions">
                <button type="button" className="dc-btn dc-btn-ghost" onClick={() => runMatch(ranked.query, ranked.limit)}>Try again</button>
              </div>
            </div>
          ) : (
            <div className="dc-find">
              <div>
                {ranked.rows.length === 0 ? (
                  <div className="dc-empty">
                    <span className="dc-empty-icon"><SearchX size={24} aria-hidden="true" /></span>
                    <div className="dc-empty-title">No one matches that search</div>
                    <p className="dc-empty-text">
                      <Link href="/create">Create your card</Link> so people can find you.
                    </p>
                    <div className="dc-empty-actions">
                      <button type="button" className="dc-btn dc-btn-ghost" onClick={browse}>All people</button>
                    </div>
                  </div>
                ) : (
                  <RankedResults
                    key={`${ranked.query}|${ranked.limit}`}
                    rows={ranked.rows}
                    query={ranked.query}
                    limit={ranked.limit}
                    onLimit={(limit) => runMatch(ranked.query, limit)}
                    onBack={browse}
                  />
                )}
              </div>

              <aside className="dc-aside" aria-label="About this search">
                <div className="dc-card">
                  <div className="dc-card-title"><Search size={15} aria-hidden="true" />Search dimensions</div>
                  <p className="dc-tips">
                    Results improve significantly when the query includes: role, location, skills, availability
                    (fulltime / freelance / open to work), industry, or experience level.
                  </p>
                </div>
              </aside>
            </div>
          )
        ) : people.length === 0 ? (
          <div className="dc-empty">
            <span className="dc-empty-icon"><Search size={24} aria-hidden="true" /></span>
            <div className="dc-empty-title">No profiles published yet</div>
            <p className="dc-empty-text">
              <Link href="/create">Be the first — create your profile.</Link>
            </p>
          </div>
        ) : visible.length === 0 ? (
          <div className="dc-empty">
            <span className="dc-empty-icon"><SearchX size={24} aria-hidden="true" /></span>
            <div className="dc-empty-title">No one named “{trimmed}”</div>
            <p className="dc-empty-text">Check the spelling, or look people up by role, skill or location instead.</p>
            <div className="dc-empty-actions">
              <button type="button" className="dc-btn dc-btn-ghost" onClick={clear}>Clear search</button>
              <button type="button" className="dc-btn dc-btn-primary" onClick={() => runMatch(query)}>Try advanced search</button>
            </div>
          </div>
        ) : (
          <ul className="dc-grid" role="list">
            {visible.map((person) => (
              <li key={person.id} className="dc-person">
                <div className="dc-person-top">
                  <PersonAvatar name={person.name} src={person.avatar} size={56} />
                  <div className="dc-person-id">
                    <div className="dc-person-name">
                      <Link href={person.href} className="dc-person-link">
                        <Highlight text={person.name} terms={terms} />
                      </Link>
                      {!person.claimed && <span className="dc-pill-warn">UNCLAIMED</span>}
                    </div>
                    {person.location && (
                      <div className="dc-person-meta">
                        <MapPin size={13} aria-hidden="true" />
                        <span>{person.location}</span>
                      </div>
                    )}
                  </div>
                  <ArrowUpRight className="dc-person-go" size={18} aria-hidden="true" />
                </div>
                {person.headline && <p className="dc-person-headline">{person.headline}</p>}
                {person.skills.length > 0 && (
                  <div className="dc-chips">
                    {person.skills.map((skill) => (
                      <Link key={skill.name} href={skill.href} className="dc-chip">{skill.name}</Link>
                    ))}
                    {person.moreSkills > 0 && <span className="dc-chip-more">+{person.moreSkills}</span>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {!ranked && people.length > 0 && (
        <div className="dc-foot">
          {people.length} {people.length === 1 ? "profile" : "profiles"} published
        </div>
      )}
    </>
  );
}
