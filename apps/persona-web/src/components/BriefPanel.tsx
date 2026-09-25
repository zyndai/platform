"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPatch } from "@/lib/api";
import { Button } from "@/components/ui";

interface BriefState {
  content?: string;
  fallback_description?: string;
}

export default function BriefPanel() {
  const { user } = useDashboard();
  const [brief, setBrief] = useState<BriefState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBrief = async () => {
    if (!user?.id) return;
    try {
      const data = await apiGet<BriefState>(`/api/persona/${user.id}/brief`);
      setBrief(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load brief.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.id) fetchBrief();
  }, [user?.id]);

  if (loading) {
    return (
      <Shell>
        <EmptyContainer>Loading brief…</EmptyContainer>
      </Shell>
    );
  }

  if (error) {
    return (
      <Shell>
        <EmptyContainer style={{ color: "var(--text-secondary)" }}>{error}</EmptyContainer>
      </Shell>
    );
  }

  if (!brief) {
    return null;
  }

  return <BriefEditor brief={brief} onSaved={fetchBrief} />;
}

const DEFAULT_TEMPLATE = `What I'm working on
—

Who I'd like to meet
—

What I'm avoiding right now
— recruiters, fundraising calls, etc.

Anything else my agent should know
— `;

function BriefEditor({
  brief,
  onSaved,
}: {
  brief: BriefState;
  onSaved: () => Promise<void>;
}) {
  const { user } = useDashboard();
  const rawInitial = normalizeContent(
    brief.content && brief.content.length > 0
      ? brief.content
      : brief.fallback_description || "",
  );
  // Empty brief? Pre-fill with the template as a starting scaffold. The user
  // can overwrite it or delete what they don't want — it's not committed
  // until they hit Save.
  const initial = rawInitial.trim().length === 0 ? DEFAULT_TEMPLATE : rawInitial;
  const startedFromTemplate = rawInitial.trim().length === 0;
  const [draft, setDraft] = useState(initial);
  const [savedSnapshot, setSavedSnapshot] = useState(rawInitial);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const dirty = draft !== savedSnapshot;

  const draftRef = useRef(draft);
  draftRef.current = draft;
  const savedSnapshotRef = useRef(savedSnapshot);
  savedSnapshotRef.current = savedSnapshot;

  const handleSave = useCallback(async () => {
    if (!user?.id) return;
    const content = draftRef.current;
    if (content === savedSnapshotRef.current) return;
    setSaving(true);
    setSaveError(null);
    try {
      await apiPatch(`/api/persona/${user.id}/brief`, { content });
      setSavedSnapshot(content);
      setSavedAt(Date.now());
      void onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Couldn't save right now. Try again in a moment.");
    } finally {
      setSaving(false);
    }
  }, [user?.id, onSaved]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        setSaveError(null);
        void handleSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleSave]);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = ""; // Chrome requires a non-empty string
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        overflowY: "auto",
        background: "var(--bg-base)",
      }}
    >
      <div className="brief-page-shell">
        <h1
          className="display-m brief-page-title"
          style={{ margin: "0 0 8px", color: "var(--text-primary)" }}
        >
          Your brief
        </h1>
        <p className="brief-page-lede">
          Your brief is the long-form context your agent uses to represent you. Edit here any time.
        </p>

        <div
          className="brief-page-header"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
            marginBottom: "10px",
          }}
        >
          <SaveStatus
            saving={saving}
            dirty={dirty}
            savedAt={savedAt}
            initialIsSynced={!!brief.content && brief.content.length > 1}
            hasError={!!saveError}
          />
          <div
            className="brief-page-actions"
            style={{ display: "flex", gap: "8px", alignItems: "center" }}
          >
            <Button
              onClick={() => {
                setSaveError(null);
                void handleSave();
              }}
              disabled={!dirty || saving}
              variant={saveError ? "primary" : "secondary"}
            >
              {saving ? "Saving…" : saveError ? "Retry save" : "Save now"}
            </Button>
          </div>
        </div>

        {saveError && (
          <div
            style={{
              padding: "10px 14px",
              marginBottom: "12px",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-sm)",
              color: "var(--text-secondary)",
              fontSize: "13px",
              lineHeight: 1.45,
            }}
          >
            {saveError}
          </div>
        )}

        <div className="brief-paper">
          <textarea
            ref={textareaRef}
            className="brief-textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Start typing. A few honest lines is enough — what you're shipping, who you'd like in the room, what to skip."
          />
        </div>

        {startedFromTemplate && draft === DEFAULT_TEMPLATE && (
          <div
            className="brief-template-hint"
            style={{
              marginTop: "14px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "12px",
              padding: "10px 14px",
              background: "var(--bg-surface)",
              border: "1px dashed var(--border-default)",
              borderRadius: "var(--r-sm)",
              fontSize: "13px",
              color: "var(--text-secondary)",
            }}
          >
            <span>This is a starter template. Edit the prompts, fill in your own — or clear it and write fresh.</span>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setDraft("");
                textareaRef.current?.focus();
              }}
              style={{ fontSize: "12px", whiteSpace: "nowrap" }}
            >
              Clear template
            </button>
          </div>
        )}

        <p
          style={{
            marginTop: "16px",
            fontSize: "12px",
            color: "var(--text-muted)",
          }}
        >
          Click <strong>Save now</strong> or press ⌘S to save · todos auto-extracted from lines like &ldquo;- [ ] follow up with X&rdquo; or &ldquo;TODO: ship demo&rdquo;.
        </p>
      </div>
    </div>
  );
}

function SaveStatus({
  saving,
  dirty,
  savedAt,
  initialIsSynced,
  hasError,
}: {
  saving: boolean;
  dirty: boolean;
  savedAt: number | null;
  initialIsSynced: boolean;
  hasError: boolean;
}) {
  const [, force] = useState(0);
  useEffect(() => {
    if (!savedAt) return;
    const id = setInterval(() => force((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [savedAt]);

  let label: string;
  let tone: "muted" | "active" | "error" = "muted";
  if (hasError) {
    label = "Save failed — try again";
    tone = "error";
  } else if (saving) {
    label = "Saving…";
    tone = "active";
  } else if (dirty) {
    label = "Unsaved changes";
    tone = "muted";
  } else if (savedAt) {
    label = `Saved ${relativeTime(savedAt)}`;
  } else if (initialIsSynced) {
    label = "Saved";
  } else {
    label = "Not saved yet";
  }

  const dotColor =
    tone === "error"
      ? "var(--status-error-fg)"
      : tone === "active"
        ? "var(--accent, #6366f1)"
        : "var(--border-default)";
  const textColor =
    tone === "error"
      ? "var(--status-error-fg)"
      : tone === "muted"
        ? "var(--text-muted)"
        : "var(--text-secondary)";

  return (
    <span
      role="status"
      aria-live="polite"
      style={{
        fontSize: "12px",
        color: textColor,
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: "6px",
          height: "6px",
          borderRadius: "50%",
          background: dotColor,
          animation: tone === "active" ? "bootloader-pulse 1.2s ease-in-out infinite" : "none",
        }}
      />
      {label}
    </span>
  );
}

function normalizeContent(s: string): string {
  // Treat a lone newline as effectively empty so the editor doesn't show
  // "Unsaved changes" on load.
  return s === "\n" ? "" : s;
}

function relativeTime(ts: number): string {
  const diffSec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const min = Math.round(diffSec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  return `${hr}h ago`;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        background: "var(--bg-base)",
      }}
    >
      {children}
    </div>
  );
}

function EmptyContainer({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "32px",
        gap: "12px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

