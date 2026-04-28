"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Avatar, Button, Input, Textarea } from "@/components/ui";

interface PersonaCardFormProps {
  /** Avatar src + display-name fallback. Pass `null` to skip the avatar entirely. */
  avatar?: { src?: string | null; name?: string | null } | null;
  initialName: string;
  initialBio: string;
  initialTags: string[];
  bioPlaceholder?: string;
  italicPlaceholder?: boolean;
  onSave: (data: { name: string; bio: string; tags: string[] }) => Promise<void>;
  saveLabel: string;
  savingLabel?: string;
  /** Show inline `Saved` confirmation under the card on success. */
  showSaved?: boolean;
}

/**
 * The persona card editor used on S3 (onboarding) and S15 (settings → You).
 * Avatar + inline-editable name + bio + interest tags + a single save button.
 */
export default function PersonaCardForm({
  avatar,
  initialName,
  initialBio,
  initialTags,
  bioPlaceholder = "Tell me what you're working on",
  italicPlaceholder = true,
  onSave,
  saveLabel,
  savingLabel = "Saving…",
  showSaved = false,
}: PersonaCardFormProps) {
  const [name, setName] = useState(initialName);
  const [bio, setBio] = useState(initialBio);
  const [tagInput, setTagInput] = useState("");
  const [tags, setTags] = useState<string[]>(initialTags);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Re-seed when the parent's initials change (e.g., after a fresh fetch).
  useEffect(() => setName(initialName), [initialName]);
  useEffect(() => setBio(initialBio), [initialBio]);
  useEffect(() => setTags(initialTags), [initialTags]);

  const commitTag = () => {
    const v = tagInput.trim();
    if (!v) return;
    if (tags.includes(v)) {
      setTagInput("");
      return;
    }
    setTags([...tags, v]);
    setTagInput("");
  };

  const removeTag = (t: string) => setTags(tags.filter((x) => x !== t));

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Give me a name to go by.");
      return;
    }
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await onSave({ name: name.trim(), bio: bio.trim(), tags });
      if (showSaved) {
        setSaved(true);
        setTimeout(() => setSaved(false), 2200);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: "100%" }}>
      {avatar !== null && (
        <Avatar
          size="xl"
          src={avatar?.src ?? null}
          name={avatar?.name ?? name}
          variant="accent"
          className="stage-avatar"
        />
      )}

      <div className="persona-card">
        <div className="field-row">
          <span className="row-label">Name</span>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name"
            disabled={saving}
          />
        </div>
        <div className="field-row">
          <span className="row-label">How I&apos;ll describe you</span>
          <Textarea
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            placeholder={bioPlaceholder}
            className={italicPlaceholder ? "italic-placeholder" : ""}
            maxLength={200}
            rows={3}
            disabled={saving}
          />
        </div>
        <div className="field-row">
          <span className="row-label">What you&apos;re into</span>
          <div className="tag-row">
            {tags.map((t) => (
              <span key={t} className="tag" style={{ gap: 6 }}>
                {t}
                <button
                  type="button"
                  onClick={() => removeTag(t)}
                  style={{
                    display: "inline-flex",
                    background: "transparent",
                    color: "var(--accent)",
                    padding: 0,
                  }}
                  aria-label={`Remove ${t}`}
                  disabled={saving}
                >
                  <X size={12} strokeWidth={1.5} />
                </button>
              </span>
            ))}
            <input
              className="tag-input"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  commitTag();
                }
              }}
              onBlur={commitTag}
              placeholder="add an interest…"
              disabled={saving}
            />
          </div>
        </div>
      </div>

      {error && (
        <p className="body-s" style={{ color: "var(--danger)", marginTop: 12 }}>
          {error}
        </p>
      )}

      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
        <Button onClick={handleSave} disabled={saving}>
          {saving ? savingLabel : saveLabel}
        </Button>
        {saved && (
          <span className="caption" style={{ color: "var(--success)" }}>
            Saved.
          </span>
        )}
      </div>
    </div>
  );
}
