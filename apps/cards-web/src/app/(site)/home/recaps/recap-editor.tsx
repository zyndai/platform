"use client";

import Link from "next/link";
import { useState } from "react";
import { ownerRequest } from "@/lib/owner-home";
import { generatedCaption, highlightLabel, recapPath, type Recap, type RecapHome } from "@/lib/recaps";
import { RecapPreview } from "@/components/recaps/recap-preview";
import { RecapShare } from "@/components/recaps/recap-share";

export function RecapEditor({ initial, token, initialId }: { initial: RecapHome; token: string; initialId?: string }) {
  const [recaps, setRecaps] = useState(initial.recaps);
  const [recap, setRecap] = useState<Recap | null>(initial.recaps.find((r) => r.id === initialId) || initial.recaps[0] || null);
  const [period, setPeriod] = useState(initial.periods[0]);
  const [kind, setKind] = useState("shipped");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [day, setDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [dirty, setDirty] = useState(false);
  const published = Boolean(recap?.published_at);

  function accept(next: Recap) {
    setRecap(next);
    setDirty(false);
    setRecaps((items) => [next, ...items.filter((r) => r.id !== next.id)]);
  }

  async function work(action: () => Promise<void>) {
    setBusy(true); setNotice("");
    try { await action(); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Please try again."); }
    finally { setBusy(false); }
  }

  async function generate(refresh = false) {
    await work(async () => {
      const next = await ownerRequest<Recap>("mine/recaps", token, "POST", { period: refresh ? recap?.period : period, refresh: true });
      accept(next);
      setNotice(next.published_at ? "This recap is published. Unpublish it before making changes." : "Your private draft is ready.");
    });
  }

  async function save(publish: boolean) {
    if (!recap) return;
    await work(async () => {
      accept(await ownerRequest<Recap>(`mine/recaps/${recap.id}`, token, "PATCH", {
        selected_ids: recap.selected_ids || [], caption: recap.caption, publish,
      }));
      setNotice(publish ? "Your recap is public. Choose how to share it below." : "Private draft saved.");
    });
  }

  return <main className="recap-page"><div className="recap-shell">
    <div className="recap-top"><Link href="/home">← Your home</Link><span className="recap-eyebrow">ZYND / BUILDER RECAPS</span></div>
    <p className="recap-eyebrow">Your work deserves to be seen</p>
    <h1>A little less blank page.<br />A little more you.</h1>
    <p>Turn your new public repositories, GitHub contributions, and milestones into a story worth sharing. Review it, make it yours, then share.</p>
    <div role="status" aria-live="polite" className="recap-notice">{notice}</div>
    <div className="recap-layout"><div>
      <section className="recap-panel"><h2>Choose your chapter</h2>
        <div className="recap-controls"><label>Month or quarter<input aria-label="Recap period" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-10 or 2026-Q3" maxLength={7} /></label>
          <button disabled={busy || dirty} onClick={() => generate()}>{busy ? "Working…" : "Generate recap"}</button></div>
        <p className="recap-muted">Use YYYY-MM or YYYY-Q1. Completed months and quarters are prepared automatically. Current periods are labelled “so far.”</p>
        <p className="recap-muted">Generate pulls the latest facts into private drafts and resets their caption and highlight selection. Published recaps stay unchanged.</p>
      </section>
      {recap ? <section className="recap-panel" aria-label="Recap editor">
        <div className="recap-top"><h2>{recap.snapshot.label}</h2><span className="recap-badge">{published ? "Public" : "Private draft"}</span></div>
        <RecapPreview recap={recap} />
        <p className="recap-caption">{recap.caption}</p>
        <p className="recap-muted">Snapshot taken {new Date(recap.snapshot.generated_at).toLocaleDateString("en-GB", { timeZone: recap.snapshot.timezone })} · {recap.snapshot.timezone}</p>
        {!recap.snapshot.github_available && <p className="recap-preview-note recap-muted">GitHub contributions are unavailable for this snapshot. We left the count out.</p>}
        {recap.snapshot.github_activity?.repositories && <div className="recap-preview-note recap-muted">
          {recap.snapshot.github_activity.repositories === "not_connected" ? <p>Add your GitHub profile in your card&apos;s editor to import new public repositories.</p> : <>
            <p>New public repositories: {recap.snapshot.github_activity.repositories}.</p>
            {(recap.snapshot.github_activity.repositories !== "complete" || recap.snapshot.github_activity.truncated) && <p>Some activity may be missing because GitHub was unavailable or the scan reached a limit. Refresh facts to retry. We check repository creation dates, not recent edits or when an old repository became public.</p>}
          </>}
        </div>}
        <p className="recap-muted">{recap.snapshot.history_note} GitHub totals reflect contributions visible to Zynd. Learning milestones are self-reported.</p>
        <h2>Choose your highlights</h2>
        {!recap.snapshot.highlights.length && <p>No highlights found for this period. Connect GitHub and refresh, choose a different period, or add a dated milestone below.</p>}
        {recap.snapshot.highlights.map((h) => <label key={h.id} className="recap-check">
          <input type="checkbox" disabled={busy || published} checked={recap.selected_ids?.includes(h.id) ?? false} onChange={(e) => {
            const next = { ...recap, selected_ids: e.target.checked ? [...(recap.selected_ids || []), h.id] : recap.selected_ids?.filter((id) => id !== h.id) };
            if (recap.caption === generatedCaption(recap) || recap.caption === recap.snapshot._caption_draft?.caption) next.caption = generatedCaption(next);
            setRecap(next);
            setDirty(true);
          }} />
          <span>{highlightLabel(h)}
            <small className="recap-muted">{h.date ? `${h.date} · ` : ""}{h.source === "owner_confirmed" ? "Confirmed by you" : h.source === "github" ? "GitHub" : "From your card"}</small></span>
        </label>)}
        <label style={{ marginTop: 24 }}>Your caption<textarea disabled={busy || published} value={recap.caption} maxLength={2000} onChange={(e) => { setRecap({ ...recap, caption: e.target.value }); setDirty(true); }} /></label>
        <p className="recap-muted">AI writes a friendly social post from your selected highlights. Save after changing highlights to update generated copy. If you edit the caption yourself, review it after hiding a highlight.</p>
        {recap.snapshot._caption_draft?.source === "template" && recap.caption === recap.snapshot._caption_draft.caption && <p className="recap-muted">Showing a factual caption because AI writing was unavailable. You can edit it or retry below.</p>}
        {!published && <>
          <button className="recap-secondary" disabled={busy || !recap.selected_ids?.length} onClick={() => work(async () => {
            const next = await ownerRequest<Recap>(`mine/recaps/${recap.id}/caption`, token, "POST", { selected_ids: recap.selected_ids || [] });
            accept(next);
            setNotice(next.snapshot._caption_draft?.source === "llm" ? "AI caption saved. Review it and make it yours." : "AI writing is unavailable. A factual caption was saved for you to edit.");
          })}>Rewrite with AI</button>
          <p className="recap-muted">Rewriting saves your selected highlights and replaces the current caption.</p>
        </>}
        <div className="recap-controls">
          {published ? <button className="recap-secondary" disabled={busy} onClick={() => work(async () => {
            accept(await ownerRequest<Recap>(`mine/recaps/${recap.id}/unpublish`, token, "POST"));
            setNotice("Recap unpublished. You can edit it now.");
          })}>Unpublish to edit</button> : <>
            <button className="recap-secondary" disabled={busy} onClick={() => save(false)}>Save draft</button>
            <button disabled={busy || !recap.can_publish || !recap.selected_ids?.length} onClick={() => save(true)}>Publish recap</button>
            <button className="recap-secondary" disabled={busy || dirty} onClick={() => generate(true)}>Refresh facts</button>
          </>}
          <a className="recap-button recap-secondary" aria-disabled={dirty || busy} href={dirty || busy ? undefined : `/api/recaps/${recap.id}/image?preview=1&download=1`}>Download PNG</a>
        </div>
        {!recap.can_publish && <p className="recap-muted">Publish your profile before sharing a public recap.</p>}
        {published && <><p><Link href={recapPath(recap)}>View public recap ↗</Link></p><RecapShare recap={recap} /></>}
        {dirty && <p className="recap-muted">Save your changes before downloading or switching recaps.</p>}
      </section> : <section className="recap-panel"><h2>Your GitHub activity, ready to share</h2><p>Generate your first recap above. New public repositories and contribution totals from your linked GitHub profile are imported automatically.</p></section>}
    </div><aside>
      <section className="recap-panel"><h2>Record a milestone</h2><p className="recap-muted">Optional: add work outside GitHub or a learning milestone. These stay private until you include them in a published recap.</p>
        <form onSubmit={(e) => { e.preventDefault(); void work(async () => {
          await ownerRequest("mine/milestones", token, "POST", { kind, title, url, occurred_on: day });
          setTitle(""); setUrl(""); setDay("");
          setNotice("Milestone recorded. Generate or refresh a private draft to include it.");
        }); }}>
          <label>Milestone type<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="shipped">Shipped a project</option><option value="learned">Reached a learning milestone</option></select></label>
          {kind === "shipped" && initial.projects.length > 0 && <label>Start from a project<select defaultValue="" onChange={(e) => {
            const project = initial.projects[Number(e.target.value)]; if (project) { setTitle(project.name); setUrl(project.url); }
          }}><option value="" disabled>Choose a project</option>{initial.projects.map((p, i) => <option key={i} value={i}>{p.name}</option>)}</select></label>}
          <label>{kind === "shipped" ? "Project name" : "What did you learn?"}<input required value={title} maxLength={140} onChange={(e) => setTitle(e.target.value)} /></label>
          <label>Date<input required type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
          <label>Evidence link (optional)<input type="url" value={url} maxLength={500} placeholder="https://…" onChange={(e) => setUrl(e.target.value)} /></label>
          <button disabled={busy}>Confirm milestone</button>
        </form>
      </section>
      <section className="recap-panel"><h2>Your chapters</h2><div className="recap-history">
        {recaps.map((r) => <button key={r.id} className="recap-secondary" disabled={busy || dirty} onClick={() => accept(r)}>{r.snapshot.label}<span>{r.published_at ? "Public" : "Draft"}</span></button>)}
        {!recaps.length && <p className="recap-muted">Your saved recaps will appear here.</p>}
      </div></section>
    </aside></div>
  </div></main>;
}
