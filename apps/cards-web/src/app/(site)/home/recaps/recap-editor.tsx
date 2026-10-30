"use client";

import Link from "next/link";
import { useState } from "react";
import { ownerRequest } from "@/lib/owner-home";
import { generatedCaption, recapPath, type Recap, type RecapHome } from "@/lib/recaps";
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
      const next = await ownerRequest<Recap>("mine/recaps", token, "POST", { period: refresh ? recap?.period : period, refresh });
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
    <p>Turn what you shipped and explored into a story worth sharing. Review it, make it yours, then share.</p>
    <div role="status" aria-live="polite" className="recap-notice">{notice}</div>
    <div className="recap-layout"><div>
      <section className="recap-panel"><h2>Choose your chapter</h2>
        <div className="recap-controls"><label>Month or quarter<input aria-label="Recap period" value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-10 or 2026-Q3" maxLength={7} /></label>
          <button disabled={busy || dirty} onClick={() => generate()}>Generate recap</button></div>
        <p className="recap-muted">Use YYYY-MM or YYYY-Q1. Completed months and quarters are prepared automatically. Current periods are labelled “so far.”</p>
      </section>
      {recap ? <section className="recap-panel" aria-label="Recap editor">
        <div className="recap-top"><h2>{recap.snapshot.label}</h2><span className="recap-badge">{published ? "Public" : "Private draft"}</span></div>
        <RecapPreview recap={recap} />
        <p className="recap-muted">Snapshot taken {new Date(recap.snapshot.generated_at).toLocaleDateString("en-GB", { timeZone: recap.snapshot.timezone })} · {recap.snapshot.timezone}</p>
        {!recap.snapshot.github_available && <p className="recap-preview-note recap-muted">GitHub contributions are unavailable for this snapshot. We left the count out.</p>}
        <p className="recap-muted">{recap.snapshot.history_note} GitHub totals reflect contributions visible to Zynd. Learning milestones are self-reported.</p>
        <h2>Choose your highlights</h2>
        {!recap.snapshot.highlights.length && <p>Add a dated milestone below, then refresh your draft.</p>}
        {recap.snapshot.highlights.map((h) => <label key={h.id} className="recap-check">
          <input type="checkbox" disabled={busy || published} checked={recap.selected_ids?.includes(h.id) ?? false} onChange={(e) => {
            const next = { ...recap, selected_ids: e.target.checked ? [...(recap.selected_ids || []), h.id] : recap.selected_ids?.filter((id) => id !== h.id) };
            if (recap.caption === generatedCaption(recap)) next.caption = generatedCaption(next);
            setRecap(next);
            setDirty(true);
          }} />
          <span>{h.kind === "github" ? `${h.count} GitHub contributions` : `${h.kind === "shipped" ? "Shipped" : h.kind === "learned" ? "Learned" : "Explored"}: ${h.title}`}
            <small className="recap-muted">{h.date ? `${h.date} · ` : ""}{h.source === "owner_confirmed" ? "Confirmed by you" : h.source === "github" ? "GitHub" : "From your card"}</small></span>
        </label>)}
        <label style={{ marginTop: 24 }}>Your caption<textarea disabled={busy || published} value={recap.caption} maxLength={2000} onChange={(e) => { setRecap({ ...recap, caption: e.target.value }); setDirty(true); }} /></label>
        <p className="recap-muted">Generated captions follow your selection. If you write your own caption, review it after hiding a highlight.</p>
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
      </section> : <section className="recap-panel"><h2>Your story starts with a milestone</h2><p>Generate your first recap above. No invented stats, no pressure to have a busy month.</p></section>}
    </div><aside>
      <section className="recap-panel"><h2>Record a milestone</h2><p className="recap-muted">Confirm what happened and when. These milestones stay private until you include them in a published recap.</p>
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
