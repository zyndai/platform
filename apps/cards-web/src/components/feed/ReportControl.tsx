"use client";

import { useId, useState } from "react";
import { REPORT_REASONS, reportCard, type ReportReason } from "@/lib/feed";

/**
 * A small "Report" link for another person's post. It opens a reason picker and sends the report through
 * the existing report-a-card API (nothing happens to the card automatically; a person reviews it). Rendered
 * inside the item's flex row of actions: the link sits at the end, the picker takes a row of its own.
 * Where reporting is switched off the API says so and the picker tells the person plainly.
 */
export function ReportControl({ token, handle, name }: { token: string; handle: string; name: string }) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<ReportReason | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  if (done) {
    return <span className="fd-status fd-report-open" role="status">Thanks, we&apos;ll take a look.</span>;
  }

  async function send() {
    if (!reason) {
      setError("Pick a reason first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await reportCard(token, handle, reason);
      setDone(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not send your report. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="fd-linkbutton fd-report-open"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={`Report ${name}'s post`}
        onClick={() => { setOpen((v) => !v); setError(""); }}
      >
        Report
      </button>
      {open && (
        <fieldset
          id={panelId}
          className="fd-report"
          onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
        >
          <legend>Why are you reporting this?</legend>
          {REPORT_REASONS.map((r) => (
            <label key={r.id}>
              <input
                type="radio"
                name={`report-${panelId}`}
                value={r.id}
                checked={reason === r.id}
                onChange={() => { setReason(r.id); setError(""); }}
              />
              {r.label}
            </label>
          ))}
          <div className="fd-composer-actions">
            <button type="button" className="fd-button" disabled={busy} onClick={() => void send()}>
              {busy ? "Sending…" : "Send report"}
            </button>
            <button type="button" className="fd-button is-ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
          {error && <p className="fd-error" role="alert">{error}</p>}
        </fieldset>
      )}
    </>
  );
}
