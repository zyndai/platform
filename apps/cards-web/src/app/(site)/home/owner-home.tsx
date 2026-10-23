"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bell,
  Check,
  Inbox,
  Link2,
  Globe2,
  LockKeyhole,
  ShieldCheck,
  Layers3,
} from "lucide-react";
import { ownerRequest, type OwnerStatus } from "@/lib/owner-home";
import { VisitorPrivacy } from "@/components/VisitorPrivacy";
import { DiscoveryAnalytics } from "./discovery-analytics";
import { CompletionRing } from "./completion-ring";

export function OwnerHome({
  initial,
  token,
}: {
  initial: OwnerStatus;
  token: string;
}) {
  const [data, setData] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [mergeId, setMergeId] = useState<string | null>(null);
  const [canonical, setCanonical] = useState(initial.card_id);
  const [preview, setPreview] = useState<string | null>(null);
  const profile = `/p/${encodeURIComponent(data.handle)}`;
  const modalOpen = Boolean(mergeId || preview);

  useEffect(() => {
    if (!modalOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const modal = document.querySelector<HTMLElement>(".oh-modal");
    modal?.querySelector<HTMLElement>("button,select")?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        setMergeId(null);
        setPreview(null);
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        modal?.querySelectorAll<HTMLElement>(
          "button:not(:disabled),select:not(:disabled),a[href],iframe",
        ) || [],
      );
      const first = controls[0],
        last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [modalOpen, busy]);

  useEffect(() => {
    // The morning digest lands at 07:00 in this zone. Report the browser's zone when it
    // differs from the stored one (first visit, or the owner moved). Best effort: on failure
    // the digest keeps its default hour.
    let zone = "";
    try {
      zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch {
      return;
    }
    if (!zone || zone === initial.timezone) return;
    ownerRequest("mine/timezone", token, "PATCH", { timezone: zone })
      .then(() => setData((current) => ({ ...current, timezone: zone })))
      .catch(() => {});
  }, [token, initial.timezone]);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      if (busy || document.visibilityState !== "visible") return;
      try {
        const next = await ownerRequest<OwnerStatus>("mine/status", token);
        if (active && next) setData(next);
      } catch { /* Keep the last successful dashboard when refresh is unavailable. */ }
    };
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, 60_000);
    return () => { active = false; window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, [token, busy]);

  async function change(work: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await work();
      setNotice("Saved");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function preference(
    key: "weekly_digest" | "email_nudges",
    checked: boolean,
  ) {
    const previous = data.notification_prefs;
    const prefs = { ...previous, [key]: checked };
    setData((current) => ({ ...current, notification_prefs: prefs }));
    await change(async () => {
      try {
        await ownerRequest("mine/notification-prefs", token, "PATCH", prefs);
      } catch (failure) {
        setData((current) => ({ ...current, notification_prefs: previous }));
        throw failure;
      }
    });
  }

  async function visibility(checked: boolean) {
    const previous = data.visibility;
    setData((current) => ({
      ...current,
      visibility: checked ? "public" : "private",
    }));
    await change(async () => {
      try {
        await ownerRequest("mine/visibility", token, "PATCH", {
          public: checked,
        });
      } catch (failure) {
        setData((current) => ({ ...current, visibility: previous }));
        throw failure;
      }
    });
  }

  return (
    <main className="oh">
      <div className="oh-shell">
        <header className="oh-header">
          <div>
            <div className="oh-header-context">
              <Link className="oh-workspace-mark" href="/directory" aria-label="Zynd directory">Z</Link>
              <p className="oh-eyebrow">YOUR CARD, AT A GLANCE</p>
              <span className="oh-handle">@{data.handle}</span>
            </div>
            <h1>
              Welcome back{data.name ? `, ${data.name.split(" ")[0]}` : ""}.
            </h1>
            <p>Keep your story current. See where it takes you.</p>
          </div>
          <div className="oh-header-actions">
            <span className={`oh-visibility-badge ${data.visibility === "public" ? "is-public" : ""}`}>
              {data.visibility === "public"
                ? <Globe2 size={13} aria-hidden="true" />
                : <LockKeyhole size={13} aria-hidden="true" />}
              {data.visibility === "public" ? "Public profile" : "Private profile"}
            </span>
            {data.visibility === "public" && (
              <Link className="oh-button oh-outline" href={profile}>
                View your card <ArrowUpRight size={16} aria-hidden="true" />
              </Link>
            )}
            <Link className="oh-button" href={`${profile}/edit`}>
              Edit your card <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </header>
        <div role="status" aria-live="polite" className="oh-notice">
          {notice}
        </div>
        <div className="oh-grid">
          <section className="oh-panel oh-completeness">
            <p className="oh-eyebrow">A LITTLE MORE YOU</p>
            <div className="oh-score-row">
              <CompletionRing score={data.completeness.score} />
              <div>
                <h2>Your card is taking shape</h2>
                <p>A few details help the right people find you.</p>
              </div>
            </div>
            <ul className="oh-checklist">
              {data.completeness.actions.map((action) => (
                <li key={action.section}>
                  <Link href={action.href}>
                    <span>{action.title}</span>
                    <ArrowUpRight size={16} />
                  </Link>
                </li>
              ))}
            </ul>
            {!data.completeness.actions.length && (
              <p>
                <Check size={16} /> Your profile is complete. Keep it current.
              </p>
            )}
          </section>
          <section className="oh-panel oh-inbox-panel">
            <p className="oh-eyebrow">YOUR INBOX</p>
            <Inbox className="oh-icon" />
            <h2>
              {data.inbox_count === null
                ? "Review queue unavailable"
                : `${data.inbox_count} facts to review`}
            </h2>
            <p>You choose what becomes public.</p>
            <Link className="oh-text-link" href={`${profile}/edit#inbox`}>
              Open review queue →
            </Link>
            <hr />
            <Link2 className="oh-icon" />
            <h3>
              {data.connection.memory_connected === true
                ? "Memory connected"
                : data.connection.memory_connected === false
                  ? "Connect your memory"
                  : "Connection status unavailable"}
            </h3>
            <p>Assistant connection details are not available yet.</p>
            <Link className="oh-text-link" href={`${profile}/edit#connect-mcp`}>
              Manage connections →
            </Link>
          </section>
          <DiscoveryAnalytics activity={data.activity} profile={profile} visitors={data.visitors} />
          <section className="oh-panel oh-attention">
            <p className="oh-eyebrow">NEEDS YOUR ATTENTION</p>
            <Bell className="oh-icon" />
            <h2>A small check-in</h2>
            {data.nudges.length ? (
              <ul className="oh-nudges">
                {data.nudges.map((n) => (
                  <li key={n.id}>
                    <Link href={n.href}>{n.title} →</Link>
                    <button
                      disabled={busy}
                      aria-label={`Dismiss: ${n.title}`}
                      onClick={() =>
                        void change(async () => {
                          await ownerRequest(
                            `mine/nudges/${n.id}/dismiss`,
                            token,
                            "POST",
                          );
                          setData((current) => ({
                            ...current,
                            nudges: current.nudges.filter(
                              (item) => item.id !== n.id,
                            ),
                          }));
                        })
                      }
                    >
                      Dismiss
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p>You&apos;re all caught up.</p>
            )}
            <h3>Your sources</h3>
            {data.sources.length ? (
              <ul className="oh-sources">
                {data.sources.map((s, i) => (
                  <li key={i}>
                    <span className="oh-source-name">{s.platform}</span>
                    <span className={`oh-source-state ${s.state === "fresh" ? "is-fresh" : ""}`}>
                      {s.state === "fresh"
                        ? "Up to date"
                        : "Refresh recommended"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>Add a source to keep your card current.</p>
            )}
            <Link className="oh-text-link" href={`${profile}/edit#identity`}>
              Review sources →
            </Link>
          </section>
          <section className="oh-panel oh-controls">
            <p className="oh-eyebrow">Setting</p>
            <h2 className="oh-heading-icon"><ShieldCheck size={20} aria-hidden="true" />Visibility &amp; emails</h2>
            <VisitorPrivacy />
            <label className="oh-toggle">
              <span>
                Public card<small>Visible to people and agents</small>
              </span>
              <input
                type="checkbox"
                checked={data.visibility === "public"}
                disabled={busy}
                onChange={(e) => void visibility(e.target.checked)}
              />
            </label>
            <label className="oh-toggle">
              <span>
                Weekly digest<small>How your card performed, once a week</small>
              </span>
              <input
                type="checkbox"
                checked={data.notification_prefs.weekly_digest}
                disabled={busy}
                onChange={(e) =>
                  void preference("weekly_digest", e.target.checked)
                }
              />
            </label>
            <label className="oh-toggle">
              <span>
                Email reminders
                <small>Timely updates when something needs attention</small>
              </span>
              <input
                type="checkbox"
                checked={data.notification_prefs.email_nudges}
                disabled={busy}
                onChange={(e) =>
                  void preference("email_nudges", e.target.checked)
                }
              />
            </label>
            <button
              className="oh-text-link oh-digest-preview"
              disabled={busy}
              onClick={() =>
                void change(async () => {
                  const result = await ownerRequest<{ html: string }>(
                    "mine/digest-preview",
                    token,
                  );
                  setPreview(result.html);
                })
              }
            >
              Preview weekly digest →
            </button>
            <p className="oh-caption">
              The public assistant saves questions for your review, with common
              contact details redacted. Visitor identities are not shown in
              your question history.
            </p>
            <div className="oh-preview-links">
              {data.visibility === "public" ? (
                <>
                  <Link href={`${profile}?preview=visitor`} target="_blank">
                    Preview as a visitor ↗
                  </Link>
                  <Link href={`${profile}/data.json`} target="_blank">
                    Preview for an agent ↗
                  </Link>
                </>
              ) : (
                <p>
                  Your card is private. Publish it to preview its public page.
                </p>
              )}
            </div>
          </section>
          {!!data.duplicates.length && (
            <section className="oh-panel oh-wide">
              <p className="oh-eyebrow">ONE STORY, ONE CARD</p>
              <h2 className="oh-heading-icon"><Layers3 size={20} aria-hidden="true" />You own more than one card</h2>
              <p>
                Choose the card to keep. Other cards are archived, and their
                links redirect to it. Their content remains in the archive.
              </p>
              {data.duplicates.map((d) => (
                <div className="oh-duplicate" key={d.id}>
                  <span>
                    {d.name || d.handle} <small>@{d.handle}</small>
                  </span>
                  <button
                    className="oh-button oh-outline"
                    disabled={busy}
                    onClick={() => {
                      setMergeId(d.id);
                      setCanonical(data.card_id);
                    }}
                  >
                    Merge cards
                  </button>
                </div>
              ))}
            </section>
          )}
          {!!data.possible_duplicates?.length && (
            <section className="oh-panel oh-wide">
              <h2>Another claimed card shares your social profile</h2>
              <p>Review these possible duplicates. Matching links do not establish ownership; contact support if they belong to a different account.</p>
              {data.possible_duplicates.map(d => (
                <p key={d.handle}><Link href={`/p/${encodeURIComponent(d.handle)}`}>{d.name || d.handle} · @{d.handle}</Link><br /><small>Shared links: {d.matched_socials.join(", ")}</small></p>
              ))}
            </section>
          )}
          {!!data.unclaimed_duplicates?.length && (
            <section className="oh-panel oh-wide">
              <h2>Another card shares your LinkedIn profile</h2>
              <p>Claim a matching card before merging it into your own.</p>
              {data.unclaimed_duplicates.map((d) => (
                <p key={d.handle}>
                  <Link href={`/p/${encodeURIComponent(d.handle)}`}>
                    {d.name || d.handle} · Review and claim →
                  </Link>
                </p>
              ))}
            </section>
          )}
        </div>
        {mergeId && (
          <div className="oh-modal-backdrop">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="merge-title"
              className="oh-modal"
            >
              <h2 id="merge-title">Choose your canonical card</h2>
              <p>
                The archived card keeps its content and redirects its old URLs.
                Nothing is deleted.
              </p>
              <label>
                Keep this card
                <select
                  value={canonical}
                  onChange={(e) => setCanonical(e.target.value)}
                >
                  <option value={data.card_id}>@{data.handle}</option>
                  {data.duplicates
                    .filter((d) => d.id === mergeId)
                    .map((d) => (
                      <option key={d.id} value={d.id}>
                        @{d.handle}
                      </option>
                    ))}
                </select>
              </label>
              <p role="status">{notice}</p>
              <div className="oh-modal-actions">
                <button disabled={busy} onClick={() => setMergeId(null)}>
                  Cancel
                </button>
                <button
                  className="oh-button"
                  disabled={busy}
                  onClick={() =>
                    void change(async () => {
                      await ownerRequest("merge", token, "POST", {
                        canonical_id: canonical,
                        source_ids: [
                          canonical === data.card_id ? mergeId : data.card_id,
                        ],
                      });
                      const next = await ownerRequest<OwnerStatus>(
                        "mine/status",
                        token,
                      );
                      setData(next);
                      setMergeId(null);
                    })
                  }
                >
                  {busy ? "Merging…" : "Merge and archive"}
                </button>
              </div>
            </section>
          </div>
        )}
        {preview && (
          <div className="oh-modal-backdrop">
            <section
              role="dialog"
              aria-modal="true"
              aria-label="Weekly digest preview"
              className="oh-modal oh-email"
            >
              <button
                className="oh-button oh-outline"
                onClick={() => setPreview(null)}
              >
                Close preview
              </button>
              <iframe
                title="Weekly digest preview"
                sandbox=""
                srcDoc={preview}
              />
            </section>
          </div>
        )}
      </div>
    </main>
  );
}
