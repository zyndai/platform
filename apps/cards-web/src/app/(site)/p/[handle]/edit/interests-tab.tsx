"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import type { ExploringItem } from "@/lib/cards";
import { removeMyExploring } from "@/lib/companion";
import { Card, Field, TagInput, type ShowToast } from "./edit-ui";
import type { EditForm, SetField } from "./edit-form";

const LEVELS = ["expert", "advanced", "intermediate", "beginner"] as const;
const LEVEL_LABELS: Record<string, string> = {
  expert: "Expert", advanced: "Advanced", intermediate: "Intermediate", beginner: "Beginner",
};

const INTERESTS = [
  { key: "talkingAbout", id: "pe-talking", label: "Love talking about", hint: "e.g. AI agents, climbing" },
  { key: "workingOn", id: "pe-working", label: "Working on", hint: "e.g. an open-source CLI" },
  { key: "connectWith", id: "pe-connect", label: "Connect with", hint: "e.g. founders, Rust devs" },
] as const;

export function InterestsTab({ form, set }: { form: EditForm; set: SetField }) {
  const [newSkill, setNewSkill] = useState("");
  const [newLevel, setNewLevel] = useState("intermediate");

  function addSkill() {
    const name = newSkill.trim();
    if (!name) return;
    set("skills", [...form.skills, { name, level: newLevel, evidence_count: 1 }]);
    setNewSkill("");
  }

  const editSkill = (i: number, patch: Partial<EditForm["skills"][number]>) =>
    set("skills", form.skills.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <>
      <Card id="signals" title="Interests" hint="Shown as chips on your card. Press Enter after each one.">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {INTERESTS.map((item) => (
            <Field key={item.key} label={item.label} htmlFor={item.id}>
              <TagInput id={item.id} tags={form[item.key]} onChange={(v) => set(item.key, v)} placeholder={item.hint} />
            </Field>
          ))}
        </div>
      </Card>

      <Card id="skills" title="Skills" hint="Shown on your public skill matrix.">
        {form.skills.length > 0 && (
          <div className="pe-skills">
            {form.skills.map((skill, i) => (
              <div key={i} className="pe-skill">
                <input value={skill.name} onChange={(e) => editSkill(i, { name: e.target.value })} aria-label="Skill name" />
                <select className="pe-select pe-select-sm" value={skill.level} onChange={(e) => editSkill(i, { level: e.target.value })} aria-label={`${skill.name} level`}>
                  {LEVELS.map((l) => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                </select>
                <button type="button" className="pe-icon-btn is-danger" onClick={() => set("skills", form.skills.filter((_, j) => j !== i))} aria-label={`Remove ${skill.name}`}>
                  <X size={15} />
                </button>
                <input type="url" style={{ flex: "1 0 100%", fontSize: 12 }} value={skill.evidence?.[0]?.url ?? ""} placeholder="Public evidence URL (optional)" aria-label={`${skill.name} evidence URL`}
                  onChange={e => editSkill(i, { evidence: e.target.value.trim() ? [{ label: skill.evidence?.[0]?.label ?? `${skill.name} source`, url: e.target.value, kind: "owner" }, ...(skill.evidence?.slice(1) ?? [])] : [] })} />
              </div>
            ))}
          </div>
        )}
        <div className="pe-skill-add">
          <input className="pe-input" value={newSkill} onChange={(e) => setNewSkill(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(); } }}
            placeholder="Add a skill" aria-label="New skill" />
          <select className="pe-select" value={newLevel} onChange={(e) => setNewLevel(e.target.value)} aria-label="New skill level">
            {LEVELS.map((l) => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
          </select>
          <button type="button" className="pe-btn pe-btn-secondary" style={{ height: 44 }} onClick={addSkill} disabled={!newSkill.trim()}>
            <Plus size={15} /> Add
          </button>
        </div>
      </Card>
    </>
  );
}

function addedOn(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Clips added from Zynd Companion. Removing saves at once, like the beacon: section saves
 *  (s10_save_section) cannot write `exploring`, so it goes through the Companion's own save. */
export function ExploringEditor({ token, initial, showToast }: { token: string; initial: ExploringItem[]; showToast: ShowToast }) {
  const [clips, setClips] = useState(initial);
  const [removing, setRemoving] = useState<string | null>(null);

  async function remove(clip: ExploringItem) {
    setRemoving(clip.url);
    try {
      setClips(await removeMyExploring(token, clip.url));
      showToast("Removed from Currently exploring", "ok");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Could not remove it. Try again.", "err");
    } finally {
      setRemoving(null);
    }
  }

  if (clips.length === 0) return null;
  return (
    <Card id="exploring" title="Currently exploring" hint="Links you added with Zynd Companion. Your card shows the last 30 days.">
      <div className="pe-list">
        {clips.map((clip) => (
          <div key={clip.url} className="pe-item">
            <div className="pe-item-main">
              <div className="pe-item-title truncate">{clip.title || clip.url}</div>
              <div className="pe-item-sub truncate" title={clip.url}>{clip.url}{addedOn(clip.added_at) && ` · added ${addedOn(clip.added_at)}`}</div>
            </div>
            <button type="button" className="pe-icon-btn is-danger" disabled={removing !== null}
              onClick={() => void remove(clip)} aria-label={`Remove ${clip.title || clip.url}`}>
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
    </Card>
  );
}
