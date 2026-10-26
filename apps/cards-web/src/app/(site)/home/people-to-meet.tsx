"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight, ArrowUpRight, UsersRound } from "lucide-react";
import {
  ownerRequest,
  type OutsidePerson,
  type SuggestedPerson,
  type SuggestionFeedback,
} from "@/lib/owner-home";
import "./people-to-meet.css";

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";

/** People to meet: who fits what the owner wants, from their card. Hide and Not relevant take a
 *  person out for good (and teach search, when network controls are on). */
export function PeopleToMeet({
  people,
  outside,
  token,
  profile,
}: {
  people: SuggestedPerson[];
  outside: OutsidePerson[];
  token: string;
  profile: string;
}) {
  const [gone, setGone] = useState<string[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState("");
  const shown = people.filter((p) => !gone.includes(p.handle));

  async function feedback(handle: string, action: SuggestionFeedback) {
    setPending(handle);
    setError("");
    setGone((current) => [...current, handle]);
    try {
      await ownerRequest(`mine/suggestions/${encodeURIComponent(handle)}/feedback`, token, "POST", { action });
    } catch (failure) {
      setGone((current) => current.filter((h) => h !== handle));
      setError(failure instanceof Error ? failure.message : "Please try again.");
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="oh-panel oh-wide oh-people" aria-labelledby="people-heading">
      <p className="oh-eyebrow">PEOPLE TO MEET</p>
      <h2 id="people-heading" className="oh-heading-icon">
        <UsersRound size={20} aria-hidden="true" />
        Who fits what you&apos;re looking for
      </h2>
      {!shown.length && !outside.length ? (
        <p>
          No suggestions yet. Say who you want to meet on your card and we&apos;ll look every day.{" "}
          <Link className="oh-text-link" href={`${profile}/edit`}>Edit your card →</Link>
        </p>
      ) : (
        <ul className="oh-people-list">
          {shown.map((p) => (
            <li key={p.handle} className="oh-person">
              {p.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img className="oh-person-avatar" src={p.avatar_url} alt="" width={40} height={40} />
              ) : (
                <span className="oh-person-avatar" aria-hidden="true">{initials(p.name || p.handle)}</span>
              )}
              <div className="oh-person-body">
                <Link className="oh-person-name" href={`/p/${encodeURIComponent(p.handle)}`}>
                  {p.name || p.handle}
                </Link>
                {(p.headline || p.location) && (
                  <span className="oh-person-sub">{[p.headline, p.location].filter(Boolean).join(" · ")}</span>
                )}
                {p.two_way && (
                  <span className="oh-person-chip">
                    <ArrowLeftRight size={12} aria-hidden="true" /> Wants to meet you too
                  </span>
                )}
                {!!p.why.length && (
                  <span className="oh-person-why">
                    {p.why.filter((w) => !(p.two_way && w.startsWith("Wants to meet"))).slice(0, 2).join(" · ")}
                  </span>
                )}
              </div>
              <div className="oh-person-actions">
                <Link className="oh-button oh-outline" href={`/p/${encodeURIComponent(p.handle)}`}>
                  View <ArrowUpRight size={14} aria-hidden="true" />
                </Link>
                <button
                  type="button"
                  disabled={pending === p.handle}
                  onClick={() => void feedback(p.handle, "not_relevant")}
                  aria-label={`Not relevant: ${p.name || p.handle}`}
                >
                  Not relevant
                </button>
                <button
                  type="button"
                  disabled={pending === p.handle}
                  onClick={() => void feedback(p.handle, "hide")}
                  aria-label={`Hide ${p.name || p.handle}`}
                >
                  Hide
                </button>
              </div>
            </li>
          ))}
          {outside.map((p) => (
            <li key={p.linkedin_url || p.name} className="oh-person is-outside">
              <span className="oh-person-avatar" aria-hidden="true">{initials(p.name)}</span>
              <div className="oh-person-body">
                <span className="oh-person-name">{p.name}</span>
                <span className="oh-person-sub">
                  {[p.title, p.company].filter(Boolean).join(" at ")}
                </span>
                <span className="oh-person-why">
                  Not on Zynd yet{p.invitable ? " · ask your assistant to invite them" : ""}
                </span>
              </div>
              {p.linkedin_url && (
                <div className="oh-person-actions">
                  <a className="oh-button oh-outline" href={p.linkedin_url} target="_blank" rel="noopener noreferrer">
                    LinkedIn <ArrowUpRight size={14} aria-hidden="true" />
                  </a>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <p role="status" aria-live="polite" className="oh-people-error">{error}</p>
    </section>
  );
}
