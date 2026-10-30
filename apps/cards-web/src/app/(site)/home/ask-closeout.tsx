"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ownerRequest } from "@/lib/owner-home";
import { PersonAvatar } from "@/components/discover/person-avatar";
import "./ask-closeout.css";

interface Offer {
  card_id: string;
  handle: string;
  name: string;
  headline: string;
  avatar_url: string | null;
  offered_at: string;
}

interface OwnAsk {
  id: string;
  text: string;
  status: "active" | "ended";
  offers: Offer[];
}

interface Credit {
  offer_id: string;
  asker_handle: string;
  asker_name: string;
  ask: string;
}

type Outcome = "helped" | "solved_elsewhere" | "still_looking";

/**
 * "Did your ask get answered?" (services/asks.py). Lists the owner's live ask once someone has
 * offered, and asks that ended in the last two weeks without an answer. The owner ticks who helped
 * (only people who offered can be credited, the API enforces it), or says it was solved another way
 * or is still open. Also lists the "Helped" credits on their own card so any can be hidden.
 * Renders nothing when there is nothing to answer, or while the asks tables are not set up.
 */
export function AskCloseout({ token, profile }: { token: string; profile: string }) {
  const [asks, setAsks] = useState<OwnAsk[]>([]);
  const [credits, setCredits] = useState<Credit[]>([]);
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Record<string, Outcome>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [mine, helped] = await Promise.all([
          ownerRequest<{ asks: OwnAsk[] }>("mine/asks", token),
          ownerRequest<{ credits: Credit[] }>("mine/credits", token),
        ]);
        if (cancelled) return;
        setAsks(mine.asks);
        setCredits(helped.credits);
      } catch {
        /* An asks outage must not hide the rest of owner home. */
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  const answerable = asks.filter((a) => a.status === "ended" || a.offers.length > 0);
  if (answerable.length === 0 && credits.length === 0) return null;

  function toggle(askId: string, cardId: string) {
    setPicked((current) => {
      const now = current[askId] ?? [];
      return { ...current, [askId]: now.includes(cardId) ? now.filter((id) => id !== cardId) : [...now, cardId] };
    });
  }

  async function answer(ask: OwnAsk, outcome: Outcome) {
    setBusy(ask.id);
    setError("");
    try {
      await ownerRequest(`mine/asks/${encodeURIComponent(ask.id)}/outcome`, token, "POST", {
        outcome,
        helper_card_ids: outcome === "helped" ? picked[ask.id] ?? [] : [],
      });
      setDone((current) => ({ ...current, [ask.id]: outcome }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  async function hide(credit: Credit) {
    setBusy(credit.offer_id);
    setError("");
    try {
      await ownerRequest(`mine/credits/${encodeURIComponent(credit.offer_id)}/hide`, token, "POST");
      setCredits((current) => current.filter((c) => c.offer_id !== credit.offer_id));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not hide this. Please try again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="oh-intro-section" id="ask-closeout">
      <div className="ac-wrap">
        {answerable.length > 0 && (
          <section className="ac-panel" aria-labelledby="ac-heading">
            <h2 id="ac-heading">Did your ask get answered?</h2>
            {answerable.map((ask) => {
              const result = done[ask.id];
              return (
                <div key={ask.id} className="ac-ask">
                  <p className="ac-text">&ldquo;{ask.text}&rdquo;</p>
                  {result ? (
                    <p className="ac-done" role="status">
                      {result === "helped" && "Thanks. The people you picked now have a Helped credit on their card."}
                      {result === "solved_elsewhere" && "Glad it got sorted."}
                      {result === "still_looking" && (
                        <>Okay. <Link href={`${profile}/edit#interests`}>Post it again</Link> to reach people.</>
                      )}
                    </p>
                  ) : (
                    <>
                      {ask.offers.length > 0 ? (
                        <fieldset className="ac-offers">
                          <legend>Who offered to help? Tick the people who did.</legend>
                          {ask.offers.map((offer) => (
                            <label key={offer.card_id} className="ac-offer">
                              <input
                                type="checkbox"
                                checked={(picked[ask.id] ?? []).includes(offer.card_id)}
                                onChange={() => toggle(ask.id, offer.card_id)}
                              />
                              <PersonAvatar name={offer.name} src={offer.avatar_url ?? undefined} size={32} />
                              <span className="ac-who">
                                <Link href={`/p/${encodeURIComponent(offer.handle)}`}>{offer.name}</Link>
                                {offer.headline && <span>{offer.headline}</span>}
                              </span>
                            </label>
                          ))}
                        </fieldset>
                      ) : (
                        <p className="ac-muted">Nobody offered help through Zynd.</p>
                      )}
                      <div className="ac-actions">
                        {ask.offers.length > 0 && (
                          <button
                            type="button"
                            className="oh-button"
                            disabled={busy === ask.id || (picked[ask.id] ?? []).length === 0}
                            onClick={() => void answer(ask, "helped")}
                          >
                            {ask.status === "active" ? "Mark as solved" : "These people helped"}
                          </button>
                        )}
                        <button type="button" className="oh-button oh-outline" disabled={busy === ask.id} onClick={() => void answer(ask, "solved_elsewhere")}>
                          Solved another way
                        </button>
                        <button type="button" className="oh-button oh-outline" disabled={busy === ask.id} onClick={() => void answer(ask, "still_looking")}>
                          Still looking
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </section>
        )}

        {credits.length > 0 && (
          <section className="ac-panel" aria-labelledby="ac-credits-heading">
            <h2 id="ac-credits-heading">Helped credits on your card</h2>
            <p className="ac-muted">People you helped chose to credit you. Hide any you would rather not show.</p>
            <ul className="ac-credits">
              {credits.map((credit) => (
                <li key={credit.offer_id}>
                  <span>
                    Helped <Link href={`/p/${encodeURIComponent(credit.asker_handle)}`}>{credit.asker_name}</Link> with &ldquo;{credit.ask}&rdquo;
                  </span>
                  <button
                    type="button"
                    className="oh-button oh-outline"
                    disabled={busy === credit.offer_id}
                    aria-label={`Hide the credit for helping ${credit.asker_name}`}
                    onClick={() => void hide(credit)}
                  >
                    Hide
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="ac-error" role="alert">{error}</p>
      </div>
    </div>
  );
}
