"use client";

import { useState } from "react";
import { Github, Globe, Link2, Linkedin, Loader2, Plus, Sparkles, Twitter, X } from "lucide-react";
import { imgProxyUrl } from "@/lib/avatar";
import { fetchSummaryDraft, type SummaryDraft } from "@/lib/cards";
import { AutoGrowTextArea } from "@/components/AutoGrowTextArea";
import { EditionPicker } from "@/components/editions/edition-picker";
import { Card, Field, TagInput } from "./edit-ui";
import { initialsOf, type EditForm, type SetField } from "./edit-form";

function PlatformIcon({ platform }: { platform: string }) {
  const p = platform.trim().toLowerCase();
  if (p === "github") return <Github size={15} />;
  if (p === "linkedin") return <Linkedin size={15} />;
  if (p === "x" || p === "twitter") return <Twitter size={15} />;
  if (p === "website" || p === "site" || p === "blog") return <Globe size={15} />;
  return <Link2 size={15} />;
}

export function ProfileTab({ form, set, handle, token }: {
  form: EditForm; set: SetField; handle: string; token: string;
}) {
  // A preview built from the owner's latest public memory. It replaces the
  // About text only when the owner clicks "Use this draft".
  const [aboutDraft, setAboutDraft] = useState<
    { status: "idle" | "loading" | "ready" | "error"; draft?: SummaryDraft; error?: string }
  >({ status: "idle" });

  async function draftAbout() {
    setAboutDraft({ status: "loading" });
    try {
      setAboutDraft({ status: "ready", draft: await fetchSummaryDraft(token) });
    } catch (err) {
      setAboutDraft({ status: "error", error: err instanceof Error ? err.message : "Couldn't draft a summary" });
    }
  }

  const photo = imgProxyUrl(form.avatar, null, handle);
  const setLink = (i: number, next: [string, string]) => set("links", form.links.map((l, j) => (j === i ? next : l)));

  return (
    <>
      <Card id="identity" title="Basics" hint="How you show up at the top of your card.">
        <div className="pe-basics">
          <div className="pe-photo" id="avatar">
            <span className="pe-avatar">
              {photo ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={photo} alt="" />
              ) : <span className="ph">{initialsOf(form.name)}</span>}
            </span>
            <p className="pe-photo-note">From your linked accounts</p>
          </div>
          <div className="pe-grid">
            <Field label="Full name" htmlFor="pe-name">
              <input id="pe-name" className="pe-input" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Your name" />
            </Field>
            <Field label="Location" htmlFor="pe-loc">
              <input id="pe-loc" className="pe-input" value={form.location} onChange={(e) => set("location", e.target.value)} placeholder="City, country" />
            </Field>
            <Field label="Headline" htmlFor="pe-head" className="full">
              <input id="pe-head" className="pe-input" value={form.headline} onChange={(e) => set("headline", e.target.value)} placeholder="Role · what you do" />
            </Field>
          </div>
        </div>
      </Card>

      <Card id="style" title="Card style" hint="How your card looks to everyone who opens it.">
        <EditionPicker
          value={form.edition}
          onChange={(next) => set("edition", next)}
          person={{ name: form.name, headline: form.headline, avatarSrc: photo ?? null }}
        />
      </Card>

      <Card id="summary" title="About" hint="A few sentences on what you do and who you'd like to meet."
        action={
          <button type="button" className="pe-btn pe-btn-ghost pe-btn-sm" onClick={draftAbout} disabled={aboutDraft.status === "loading"}>
            {aboutDraft.status === "loading" ? <Loader2 size={15} className="pe-spin" /> : <Sparkles size={15} />}
            {aboutDraft.status === "loading" ? "Drafting…" : "Draft from memory"}
          </button>
        }>
        <AutoGrowTextArea
          id="pe-about"
          ariaLabel="About"
          value={form.summary}
          onChange={(v) => set("summary", v)}
          minRows={4}
          className="pe-input pe-textarea"
          placeholder="Write a short professional summary"
        />
        {aboutDraft.status === "error" && <p role="alert" className="pe-error" style={{ marginTop: 8 }}>{aboutDraft.error}</p>}
        {aboutDraft.status === "ready" && aboutDraft.draft && (
          <div data-testid="about-draft" className="pe-draft">
            <div className="pe-draft-label"><Sparkles size={12} /> Suggested from your public memory</div>
            <p className="pe-draft-text">{aboutDraft.draft.draft}</p>
            {aboutDraft.draft.based_on.length > 0 && (
              <p className="pe-note" style={{ marginTop: 8 }}>Based on: {aboutDraft.draft.based_on.join(" · ")}</p>
            )}
            <div className="pe-row">
              <button type="button" className="pe-btn pe-btn-primary pe-btn-sm"
                onClick={() => { set("summary", aboutDraft.draft!.draft); setAboutDraft({ status: "idle" }); }}>
                Use this draft
              </button>
              <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={() => setAboutDraft({ status: "idle" })}>
                Keep mine
              </button>
              <span className="pe-note">Your text only changes if you use the draft and save.</span>
            </div>
          </div>
        )}
        <div className="pe-grid" style={{ marginTop: 16 }}>
          <Field label="Availability" htmlFor="pe-avail">
            <input id="pe-avail" className="pe-input" value={form.availability} onChange={(e) => set("availability", e.target.value)} placeholder="Full-time, consulting…" />
          </Field>
          <Field label="Industries" htmlFor="pe-industries">
            <TagInput id="pe-industries" tags={form.industries} onChange={(v) => set("industries", v)} placeholder="Add an industry" />
          </Field>
        </div>
      </Card>

      <Card id="presence" title="Links" hint="Your GitHub and LinkedIn links also feed the Imported tab.">
        <div className="pe-links">
          {form.links.map(([p, u], i) => (
            <div key={i} className="pe-link">
              <div className="pe-link-platform">
                <PlatformIcon platform={p} />
                <input className="pe-input" value={p} onChange={(e) => setLink(i, [e.target.value, u])} placeholder="Platform" aria-label="Platform" />
              </div>
              <input className="pe-input" value={u} onChange={(e) => setLink(i, [p, e.target.value])} placeholder="https://" aria-label={`${p || "Link"} URL`} inputMode="url" />
              <button type="button" className="pe-icon-btn is-danger" onClick={() => set("links", form.links.filter((_, j) => j !== i))} aria-label={`Remove ${p || "link"}`}>
                <X size={16} />
              </button>
            </div>
          ))}
        </div>
        <button type="button" className="pe-btn pe-btn-ghost pe-btn-sm" style={{ marginTop: 10 }} onClick={() => set("links", [...form.links, ["", ""]])}>
          <Plus size={15} /> Add link
        </button>
      </Card>

      <Card id="settings" title="Booking" hint="Optional. Lets people book time with you from your card.">
        <div className="pe-grid">
          <Field label="Calendly" htmlFor="pe-cal">
            <input id="pe-cal" className="pe-input" value={form.calendly} onChange={(e) => set("calendly", e.target.value)} placeholder="https://calendly.com/…" inputMode="url" />
          </Field>
          <Field label="Google Calendar" htmlFor="pe-gcal">
            <input id="pe-gcal" className="pe-input" value={form.gcal} onChange={(e) => set("gcal", e.target.value)} placeholder="https://calendar.app.google/…" inputMode="url" />
          </Field>
        </div>
      </Card>
    </>
  );
}
