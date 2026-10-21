"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Card, Field, TagInput } from "./edit-ui";
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
