"use client";

import { useRef, useState } from "react";
import { Check, FileUp, Link2, Pencil, Plus, RotateCw, TriangleAlert, X } from "lucide-react";

import { PersonAvatar } from "@/components/discover/person-avatar";
import { imgProxyUrl } from "@/lib/avatar";
import type { SourceStatus } from "@/lib/cards";
import { KIND_LABEL, KIND_READING, KindIcon } from "./kind-icon";
import { QUICK_ADD, detectKind, isBarePrefix, shortenUrl, statusLine } from "./model";
import type { BuildState } from "./use-build";

type Row = Pick<SourceStatus, "state" | "preview"> | { state: "queued"; preview: SourceStatus["preview"] };

/** One pasted link and what has been read from it so far. */
function SourceRow({ url, row, warning, stale, onRemove, onFix }: {
  url: string;
  row: Row;
  warning?: string;
  /** A queued row is waiting for the person to rebuild, not for a build already starting. */
  stale: boolean;
  onRemove: () => void;
  onFix: (raw: string) => string | null;
}) {
  const kind = detectKind(url);
  const [fixing, setFixing] = useState(false);
  const [draft, setDraft] = useState(url);
  const [error, setError] = useState<string | null>(null);
  const { preview } = row;
  const photo = row.state === "done" ? imgProxyUrl(preview.avatar) : undefined;

  const submitFix = () => {
    const problem = onFix(draft);
    if (problem) setError(problem);
    else { setFixing(false); setError(null); }
  };

  return (
    <li className="cr-source cr-in" data-state={row.state} data-kind={kind}>
      <span className="cr-source-icon">
        {photo ? <PersonAvatar name={preview.name || KIND_LABEL[kind]} src={photo} size={40} /> : <KindIcon kind={kind} size={28} />}
      </span>

      <div className="cr-source-main">
        <div className="cr-source-url">
          {photo && <KindIcon kind={kind} size={16} />}
          <span title={url}>{shortenUrl(url)}</span>
        </div>

        {row.state === "reading" && <div className="cr-source-line"><span className="cr-spinner" aria-hidden="true" /> {KIND_READING[kind]}</div>}
        {row.state === "queued" && <div className="cr-source-line">{stale ? "Not in your draft yet. Rebuild to read it." : "Waiting to start…"}</div>}
        {row.state === "skipped" && <div className="cr-source-line">Only one {KIND_LABEL[kind]} profile is read, so this one is skipped.</div>}
        {row.state === "failed" && (
          <div className="cr-source-line">
            <TriangleAlert size={14} className="is-bad" aria-hidden="true" />
            <span className="is-bad">{warning || "This profile could not be read. Check that it is public."}</span>
          </div>
        )}
        {row.state === "done" && (
          <>
            <div className="cr-source-line">
              <Check size={14} aria-hidden="true" style={{ color: "#14663A" }} />
              {preview.name ? <strong>{preview.name}</strong> : <span>Read</span>}
              {preview.headline && <span className="cr-clip" style={{ maxWidth: "100%" }}>{preview.headline}</span>}
            </div>
            {(preview.facts?.length ?? 0) > 0 && (
              <div className="cr-source-facts">
                {preview.facts!.map((f) => <span key={f} className="dc-chip dc-chip-plain">{f}</span>)}
              </div>
            )}
            {(preview.images?.length ?? 0) > 0 && (
              <div className="cr-thumbs" aria-hidden="true">
                {/* eslint-disable-next-line @next/next/no-img-element -- remote project covers, proxied */}
                {preview.images!.map((src) => <img key={src} src={imgProxyUrl(src)} alt="" loading="lazy" />)}
              </div>
            )}
          </>
        )}

        {fixing && (
          <div className="cr-fix">
            <input
              className="cr-input is-mono" value={draft} autoFocus aria-label={`Correct ${shortenUrl(url)}`}
              onChange={(e) => { setDraft(e.target.value); setError(null); }}
              onKeyDown={(e) => {
                if (e.key === "Enter") { e.preventDefault(); submitFix(); }
                if (e.key === "Escape") setFixing(false);
              }}
            />
            <button type="button" className="dc-btn dc-btn-ghost" onClick={submitFix}>Re-read</button>
          </div>
        )}
        {error && <div className="cr-source-line"><span className="is-bad">{error}</span></div>}
      </div>

      <div className="cr-source-tools">
        {row.state === "failed" && !fixing && (
          <button type="button" className="cr-mini is-accent" onClick={() => { setDraft(url); setFixing(true); }}>
            <Pencil size={13} aria-hidden="true" /> Fix link
          </button>
        )}
        <button type="button" className="cr-mini" onClick={onRemove} aria-label={`Remove ${shortenUrl(url)}`}>
          <X size={15} aria-hidden="true" />
        </button>
      </div>
    </li>
  );
}

/**
 * Step one and the live read-out in one place: paste links or drop a résumé,
 * and each source shows what was found as soon as it finishes.
 */
export function SourcesCard({ urls, resume, build, stale, onAdd, onRemove, onReplace, onResume, onRetry }: {
  urls: string[];
  resume: File | null;
  build: BuildState;
  /** The sources changed since the draft was built; `onRetry` rebuilds it. */
  stale: boolean;
  /** Returns what is wrong with the link, or null when it was added. */
  onAdd: (raw: string) => string | null;
  onRemove: (url: string) => void;
  onReplace: (url: string, raw: string) => string | null;
  onResume: (file: File | null) => void;
  onRetry: () => void;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const byUrl = new Map(build.sources.map((s) => [s.url, s]));
  const rowFor = (url: string): Row => byUrl.get(url) ?? { state: "queued", preview: {} };
  const warningFor = (url: string) => build.warnings.find((w) => w.url === url)?.message;

  const add = (raw: string) => {
    const problem = onAdd(raw);
    setError(problem);
    if (!problem) setValue("");
  };

  const resumeRead = !!build.jobId && build.inputs.resume === resume;
  const busy = build.status === "running";
  const headline = build.status === "error" ? "Something went wrong"
    : build.status === "ready" && !busy ? "Draft ready"
    : build.status === "running" ? statusLine(build.sources, build.stage)
    : urls.length || resume ? "Starting…" : "";

  return (
    <section className="cr-card" aria-labelledby="cr-sources-h">
      <div className="cr-step-head">
        <span className="cr-step-n" aria-hidden="true">1</span>
        <div className="cr-head-title">
          <div id="cr-sources-h" className="cr-h">Add your links</div>
          <div className="cr-sub">Any public profile, newsletter or portfolio. We read it and write your card.</div>
        </div>
      </div>
      {headline && (
        <span className="cr-state" data-tone={build.status === "error" ? "bad" : build.status === "ready" ? "ok" : undefined} role="status">
          {busy && <span className="cr-spinner" aria-hidden="true" />}
          {build.status === "ready" && <Check size={14} aria-hidden="true" />}
          {headline}
        </span>
      )}

      <form
        className="dc-search"
        onSubmit={(e) => { e.preventDefault(); add(value); }}
      >
        <Link2 className="dc-search-icon" size={20} aria-hidden="true" />
        <label htmlFor="cr-link" className="dc-sr">Link to a profile</label>
        <input
          id="cr-link" ref={inputRef} className="dc-search-input" type="text" inputMode="url" autoFocus
          value={value} autoComplete="off" autoCapitalize="off" spellCheck={false}
          placeholder={urls.length ? "Add another link" : "Paste a profile link"}
          onChange={(e) => { setValue(e.target.value); setError(null); }}
          onKeyDown={(e) => { if (e.key === " " && value.trim()) { e.preventDefault(); add(value); } }}
          onPaste={(e) => {
            // Into an empty box a paste is a whole link (or several): add it now, no Enter.
            // Into a half-typed one (after a quick-add prefix) it belongs in place.
            const pasted = e.clipboardData.getData("text").trim();
            if (!pasted || value.trim()) return;
            e.preventDefault();
            pasted.split(/\s+/).forEach(add);
          }}
          // Leaving a box that holds only a tapped quick-add prefix is not a finished link.
          onBlur={() => { if (value.trim() && !isBarePrefix(value)) add(value); }}
        />
        <button type="submit" className="dc-btn dc-btn-primary dc-search-submit" disabled={!value.trim()}>
          <Plus size={16} aria-hidden="true" /> Add
        </button>
      </form>
      {error && <div className="cr-alert" role="alert"><TriangleAlert size={16} aria-hidden="true" /> {error}</div>}

      <div className="cr-quick">
        {QUICK_ADD.map(({ kind, prefix }) => (
          <button
            key={kind} type="button" className="dc-toggle" aria-pressed="false"
            onClick={() => { setValue(prefix); inputRef.current?.focus(); }}
          >
            <KindIcon kind={kind} size={18} /> {KIND_LABEL[kind]}
          </button>
        ))}
        <button type="button" className="cr-resume" onClick={() => fileRef.current?.click()}>
          <FileUp size={15} aria-hidden="true" /> {resume ? "Replace résumé" : "Add a résumé"}
        </button>
        <input
          ref={fileRef} type="file" accept=".pdf,.docx,application/pdf" hidden aria-label="Résumé (PDF or DOCX)"
          onChange={(e) => { onResume(e.target.files?.[0] ?? null); e.target.value = ""; }}
        />
      </div>

      {(urls.length > 0 || resume) && (
        <ul className="cr-sources" aria-label="Sources">
          {urls.map((url) => (
            <SourceRow
              key={url} url={url} row={rowFor(url)} warning={warningFor(url)} stale={stale}
              onRemove={() => onRemove(url)} onFix={(raw) => onReplace(url, raw)}
            />
          ))}
          {resume && (
            <li className="cr-source cr-in" data-state={resumeRead ? "done" : stale ? "queued" : "reading"}>
              <span className="cr-source-icon"><FileUp size={22} aria-hidden="true" style={{ color: "var(--dc-accent)" }} /></span>
              <div className="cr-source-main">
                <div className="cr-source-url"><span>{resume.name}</span></div>
                <div className="cr-source-line">
                  {resumeRead ? <><Check size={14} aria-hidden="true" style={{ color: "#14663A" }} /> Included in your card.</>
                    : stale ? "Not in your draft yet. Rebuild to read it."
                    : <><span className="cr-spinner" aria-hidden="true" /> Uploading…</>}
                </div>
              </div>
              <div className="cr-source-tools">
                <button type="button" className="cr-mini" onClick={() => onResume(null)} aria-label="Remove résumé"><X size={15} aria-hidden="true" /></button>
              </div>
            </li>
          )}
        </ul>
      )}

      {stale && (
        <div className="cr-banner-row" role="status">
          <span className="cr-note">Your sources changed since this draft.</span>
          <button type="button" className="cr-mini is-accent" onClick={onRetry}>
            <RotateCw size={13} aria-hidden="true" /> Rebuild with new sources
          </button>
        </div>
      )}

      {build.status === "error" && (
        <div className="cr-alert" role="alert">
          <TriangleAlert size={16} aria-hidden="true" />
          <span>{build.error}</span>
          <button type="button" className="cr-mini" onClick={onRetry}><RotateCw size={13} aria-hidden="true" /> Retry</button>
        </div>
      )}
    </section>
  );
}
