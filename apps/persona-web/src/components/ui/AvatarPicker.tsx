"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw, X } from "lucide-react";
import {
  generateAvatarDataUri,
  GROUP_STYLES,
  PERSONA_STYLES,
  type DiceBearStyleId,
  type GroupStyleId,
  type PersonaStyleId,
} from "@/lib/dicebear";

export type AvatarPickerMode = "persona" | "group";

interface AvatarPickerProps {
  mode: AvatarPickerMode;
  seed: string;
  currentUrl?: string | null;
  onSave: (dataUri: string) => Promise<void> | void;
  onClose: () => void;
}

function randomSeed(): string {
  return Math.random().toString(36).slice(2, 10);
}

function initialStyleFor(mode: AvatarPickerMode, currentUrl: string | null | undefined): DiceBearStyleId {
  if (mode === "persona") return "botttsNeutral";
  return "shapes";
}

export default function AvatarPicker({
  mode,
  seed: initialSeed,
  currentUrl,
  onSave,
  onClose,
}: AvatarPickerProps) {
  const styles = mode === "persona" ? PERSONA_STYLES : GROUP_STYLES;
  const [selectedStyle, setSelectedStyle] = useState<DiceBearStyleId>(
    () => initialStyleFor(mode, currentUrl),
  );
  const [seed, setSeed] = useState(initialSeed || randomSeed());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  // Close on backdrop click
  const onBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  const previewUri = generateAvatarDataUri(selectedStyle, seed);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(previewUri);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="avatar-picker-backdrop" onClick={onBackdropClick}>
      <div
        className="avatar-picker-dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Choose avatar"
      >
        {/* Header */}
        <div className="avatar-picker-header">
          <span className="avatar-picker-title">Choose avatar</span>
          <button
            type="button"
            className="avatar-picker-close"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        {/* Preview */}
        <div className="avatar-picker-preview-wrap">
          <img
            src={previewUri}
            alt="Avatar preview"
            className="avatar-picker-preview"
          />
        </div>

        {/* Style grid */}
        <div className="avatar-picker-section-label">Style</div>
        <div className="avatar-picker-style-grid">
          {styles.map((s) => {
            const uri = generateAvatarDataUri(s.id, seed);
            return (
              <button
                key={s.id}
                type="button"
                className={`avatar-picker-style-btn ${selectedStyle === s.id ? "is-selected" : ""}`}
                onClick={() => setSelectedStyle(s.id)}
                title={s.label}
              >
                <img src={uri} alt={s.label} className="avatar-picker-style-img" />
                <span className="avatar-picker-style-label">{s.label}</span>
              </button>
            );
          })}
        </div>

        {/* Seed / randomise */}
        <div className="avatar-picker-section-label">Seed</div>
        <div className="avatar-picker-seed-row">
          <input
            className="avatar-picker-seed-input"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="type anything…"
            spellCheck={false}
          />
          <button
            type="button"
            className="avatar-picker-randomize"
            onClick={() => setSeed(randomSeed())}
            title="Randomize"
          >
            <RefreshCw size={14} strokeWidth={1.8} />
          </button>
        </div>

        {error && <p className="avatar-picker-error">{error}</p>}

        {/* Actions */}
        <div className="avatar-picker-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Use this avatar"}
          </button>
        </div>
      </div>
    </div>
  );
}
