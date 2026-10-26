"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, BadgeCheck, Briefcase, CircleCheck, MapPin, RotateCcw, SearchX, Sparkles } from "lucide-react";
import { matchLabel } from "@/lib/match-reason";
import { PersonAvatar } from "./person-avatar";
import { LIMIT_CHOICES } from "./search-terms";

export interface RankedRow {
  key: string;
  /** Position in the API's ranking; it stays put when the list is filtered or re-sorted. */
  rank: number;
  href: string;
  name: string;
  headline: string;
  location: string;
  availability: string;
  years: number | null;
  skills: string[];
  reasons: string[];
  verified: string[];
  claimed: boolean | undefined;
  score: number;
  avatar?: string;
}

type SortKey = "match" | "experience";

const SKILLS_SHOWN = 5;

/**
 * The ranked matches of a search. The API has already ranked and limited them;
 * the toggles and sort here only narrow or reorder what came back, while the
 * limit asks the API for more or fewer.
 */
export function RankedResults({
  rows,
  query,
  limit,
  onLimit,
  onBack,
}: {
  rows: RankedRow[];
  query: string;
  limit: number;
  onLimit: (limit: number) => void;
  onBack: () => void;
}) {
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [availableOnly, setAvailableOnly] = useState(false);
  const [claimedOnly, setClaimedOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("match");

  const filtered = verifiedOnly || availableOnly || claimedOnly;
  const visible = useMemo(() => {
    const kept = rows.filter((row) =>
      (!verifiedOnly || row.verified.length > 0) &&
      (!availableOnly || row.availability !== "") &&
      (!claimedOnly || row.claimed !== false));
    if (sort === "match") return kept;
    return [...kept].sort((a, b) => (b.years ?? -1) - (a.years ?? -1) || a.rank - b.rank);
  }, [rows, verifiedOnly, availableOnly, claimedOnly, sort]);

  const reset = () => {
    setVerifiedOnly(false);
    setAvailableOnly(false);
    setClaimedOnly(false);
  };

  const limits = [...new Set([...LIMIT_CHOICES, limit])].sort((a, b) => a - b);

  return (
    <>
      <div className="dc-results-bar">
        <div className="dc-results-count" aria-live="polite">
          <span>{filtered ? visible.length : rows.length}</span>
          {filtered ? ` of ${rows.length}` : ""} result{rows.length === 1 ? "" : "s"} for &ldquo;{query}&rdquo;
        </div>
        <div className="dc-results-actions">
          <button type="button" className="dc-linkbtn" onClick={onBack}>
            <ArrowLeft size={14} aria-hidden="true" /> All people
          </button>
        </div>
      </div>

      <div className="dc-toolbar" role="group" aria-label="Narrow these matches">
        {rows.length > 1 && (
          <>
            <button type="button" className="dc-toggle" aria-pressed={verifiedOnly} onClick={() => setVerifiedOnly((on) => !on)}>
              <BadgeCheck size={14} aria-hidden="true" /> Verified
            </button>
            <button type="button" className="dc-toggle" aria-pressed={availableOnly} onClick={() => setAvailableOnly((on) => !on)}>
              <CircleCheck size={14} aria-hidden="true" /> Has availability
            </button>
            <button type="button" className="dc-toggle" aria-pressed={claimedOnly} onClick={() => setClaimedOnly((on) => !on)}>
              Claimed
            </button>
          </>
        )}
        <div className="dc-toolbar-end">
          {rows.length > 1 && (
            <>
              <label htmlFor="dc-sort" className="dc-sr">Sort matches</label>
              <select id="dc-sort" className="dc-select" value={sort} onChange={(event) => setSort(event.target.value as SortKey)}>
                <option value="match">Best match</option>
                <option value="experience">Most experience</option>
              </select>
            </>
          )}
          <label htmlFor="dc-limit" className="dc-sr">Matches to show</label>
          <select id="dc-limit" className="dc-select" value={limit} onChange={(event) => onLimit(Number(event.target.value))}>
            {limits.map((choice) => <option key={choice} value={choice}>Top {choice}</option>)}
          </select>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="dc-empty">
          <span className="dc-empty-icon"><SearchX size={24} aria-hidden="true" /></span>
          <div className="dc-empty-title">Nobody here fits those filters</div>
          <p className="dc-empty-text">The search found people, but none with all of the options switched on.</p>
          <div className="dc-empty-actions">
            <button type="button" className="dc-btn dc-btn-ghost" onClick={reset}>
              <RotateCcw size={14} aria-hidden="true" /> Clear filters
            </button>
          </div>
        </div>
      ) : (
        <ol className="dc-list" role="list">
          {visible.map((row) => {
            const label = matchLabel(row.score);
            return (
              <li key={row.key} className="dc-result">
                <PersonAvatar name={row.name} src={row.avatar} size={60} />

                <div className="dc-result-main">
                  <div className="dc-result-name">
                    <span className="dc-rank">#{row.rank}</span>
                    <Link href={row.href} className="dc-result-link">{row.name}</Link>
                    {row.claimed === false && <span className="dc-pill-warn">UNCLAIMED</span>}
                    {row.verified.map((label) => (
                      <span key={label} className="dc-pill-ok" title={`The owner proved this ${label} identity`}>
                        <BadgeCheck size={12} aria-hidden="true" /> {label}
                      </span>
                    ))}
                  </div>
                  {row.headline && <p className="dc-result-headline">{row.headline}</p>}

                  <div className="dc-chips">
                    {row.location && (
                      <span className="dc-chip dc-chip-plain"><MapPin size={13} aria-hidden="true" />{row.location}</span>
                    )}
                    {row.availability && (
                      <span className="dc-chip dc-chip-ok"><CircleCheck size={13} aria-hidden="true" />{row.availability}</span>
                    )}
                    {row.years != null && (
                      <span className="dc-chip dc-chip-plain">
                        <Briefcase size={13} aria-hidden="true" />{row.years} {row.years === 1 ? "yr" : "yrs"} experience
                      </span>
                    )}
                    {row.skills.slice(0, SKILLS_SHOWN).map((skill) => (
                      <span key={skill} className="dc-chip">{skill}</span>
                    ))}
                    {row.skills.length > SKILLS_SHOWN && <span className="dc-chip-more">+{row.skills.length - SKILLS_SHOWN}</span>}
                  </div>

                  <div className="dc-result-foot">
                    {row.reasons.length > 0 ? (
                      <div className="dc-reasons">
                        <span className="dc-reasons-label">Why it matched</span>
                        <ul>
                          {row.reasons.map((reason) => (
                            <li key={reason}><Sparkles size={13} aria-hidden="true" />{reason}</li>
                          ))}
                        </ul>
                      </div>
                    ) : <span />}
                    <Link href={row.href} className="dc-btn dc-btn-ghost">
                      View profile <ArrowUpRight size={15} aria-hidden="true" />
                    </Link>
                  </div>
                </div>

                {label && (
                  <div className="dc-score-wrap">
                    <span className={`dc-match dc-match-${label.tone}`}>
                      {label.text.split(" ")[0]}<span className="dc-match-word"> match</span>
                    </span>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
