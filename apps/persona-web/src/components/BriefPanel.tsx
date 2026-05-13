"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { Button, EmptyState } from "@/components/ui";

interface BriefState {
  exists: boolean;
  doc_id?: string;
  url?: string;
  content?: string;
  title?: string;
  fallback_description?: string;
  error?: string;
}

export default function BriefPanel() {
  const { user } = useDashboard();
  const [brief, setBrief] = useState<BriefState | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
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

  const handleCreate = async () => {
    if (!user?.id) return;
    setCreating(true);
    setError(null);
    try {
      await apiPost(`/api/persona/${user.id}/brief/init`, {});
      await fetchBrief();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create brief doc.");
    } finally {
      setCreating(false);
    }
  };

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

  if (!brief?.exists) {
    return (
      <Shell>
        <EmptyState
          title="Create your brief"
          body="Your brief is the long-form context the AI agent uses to represent you. It lives as a single Google Doc — the agent can only see this one doc, never the rest of your Drive."
          action={
            <Button onClick={handleCreate} disabled={creating}>
              {creating ? "Creating…" : "Create my brief"}
            </Button>
          }
        />
        {brief?.fallback_description && (
          <div
            style={{
              maxWidth: "480px",
              margin: "0 auto 32px",
              padding: "12px 14px",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-default)",
              borderRadius: "var(--r-sm)",
              fontSize: "13px",
              color: "var(--text-secondary)",
              whiteSpace: "pre-wrap",
            }}
          >
            <p className="section-label" style={{ marginBottom: "6px" }}>
              CURRENT SHORT BRIEF (will seed the doc)
            </p>
            {brief.fallback_description}
          </div>
        )}
      </Shell>
    );
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
  // savedSnapshot reflects what's actually in Google Docs. When we pre-fill
  // a template, draft != savedSnapshot, so the editor correctly shows
  // "Unsaved changes" and prompts the user to commit it.
  const [savedSnapshot, setSavedSnapshot] = useState(rawInitial);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Tracks whether the user has interacted with the textarea since mount.
  // Suppresses autosave on the initial template prefill (we don't want to
  // silently commit a template the user hasn't seen yet) AND is used by
  // the status indicator to choose between "Saving in a moment…" (user
  // typed) vs "Template ready — Save when you're happy" (just the prefill).
  const [userTouched, setUserTouched] = useState(false);

  useEffect(() => {
    setDraft(initial);
    setSavedSnapshot(rawInitial);
    setUserTouched(false); // server re-sync is not user input
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial, rawInitial]);

  const dirty = draft !== savedSnapshot;

  // Save is wrapped in useCallback so the debouncing effect below has a
  // stable identity. It snapshots the content via a ref so a save kicked
  // off by the debouncer always writes the latest text — never a stale
  // value captured at the moment the timer was scheduled.
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const savedSnapshotRef = useRef(savedSnapshot);
  savedSnapshotRef.current = savedSnapshot;

  const handleSave = useCallback(async () => {
    if (!user?.id) return;
    const content = draftRef.current;
    if (content === savedSnapshotRef.current) return; // already in sync
    setSaving(true);
    setSaveError(null);
    try {
      await apiPatch(`/api/persona/${user.id}/brief`, { content });
      setSavedSnapshot(content);
      setSavedAt(Date.now());
      await onSaved();
    } catch (err) {
      setSaveError(friendlySaveError(err));
    } finally {
      setSaving(false);
    }
  }, [user?.id, onSaved]);

  // Debounced autosave — fires 1.5s after the user stops typing.
  // Skipped while: a save is already in flight (the in-flight save will
  // pick up any newer content on its post-completion re-eval), or a save
  // just failed (don't retry on a loop — user must click Save explicitly
  // to clear the error and try again), or the user hasn't actually
  // edited yet (the template prefill is not their intent).
  useEffect(() => {
    if (!userTouched) return;
    if (!dirty) return;
    if (saving) return;
    if (saveError) return;
    const timer = setTimeout(() => {
      void handleSave();
    }, 1500);
    return () => clearTimeout(timer);
  }, [draft, dirty, saving, saveError, userTouched, handleSave]);

  // After an in-flight save finishes, the user may have typed more during
  // the round-trip. The autosave effect picks it up automatically because
  // `dirty` flips back to true on the next render — no extra wiring here.

  // ⌘S / Ctrl-S: explicit save. Also clears any save error and re-tries
  // immediately. Helpful as a manual retry path when autosave is paused.
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

  // Warn before navigating away with unsaved changes. The autosave should
  // catch most cases, but if the user closes the tab during the 1.5s
  // debounce window or in the middle of an error state, we don't want
  // them to lose the edit silently.
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
      <div
        style={{
          maxWidth: "760px",
          width: "100%",
          margin: "0 auto",
          padding: "40px 32px 48px",
        }}
      >
        <h1
          className="display-m"
          style={{ margin: "0 0 8px", color: "var(--text-primary)" }}
        >
          Your brief
        </h1>
        <p
          style={{
            margin: "0 0 28px",
            color: "var(--text-secondary)",
            fontSize: "15px",
            lineHeight: 1.55,
            maxWidth: "560px",
          }}
        >
          The long-form context your agent uses to represent you. Lives as a single Google Doc
          only your agent can see. Edit here or in Google Docs — your agent re-reads it whenever
          it changes.
        </p>

        <div
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
            autosaveActive={userTouched}
          />
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            {brief.url && (
              <a
                href={brief.url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-secondary"
                style={{ textDecoration: "none" }}
              >
                Open in Google Docs ↗
              </a>
            )}
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
            onChange={(e) => {
              if (!userTouched) setUserTouched(true);
              setDraft(e.target.value);
            }}
            placeholder="Start typing. A few honest lines is enough — what you're shipping, who you'd like in the room, what to skip."
          />
        </div>

        {startedFromTemplate && draft === DEFAULT_TEMPLATE && (
          <div
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
                setUserTouched(true);
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
          Autosaves to Google Docs as you type · ⌘S forces an immediate save · todos auto-extracted from lines like “- [ ] follow up with X” or “TODO: ship demo”.
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
  autosaveActive,
}: {
  saving: boolean;
  dirty: boolean;
  savedAt: number | null;
  initialIsSynced: boolean;
  hasError: boolean;
  autosaveActive: boolean;
}) {
  // Tick once a minute so "Saved 12s ago" → "Saved 1 min ago" reflows.
  const [, force] = useState(0);
  useEffect(() => {
    if (!savedAt) return;
    const id = setInterval(() => force((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [savedAt]);

  let label: string;
  let tone: "muted" | "active" | "error" = "muted";
  if (hasError) {
    label = "Save paused — fix the error above to resume";
    tone = "error";
  } else if (saving) {
    label = "Saving…";
    tone = "active";
  } else if (dirty) {
    label = autosaveActive
      ? "Saving in a moment…"
      : "Draft ready — Save when you're happy with it";
    tone = autosaveActive ? "active" : "muted";
  } else if (savedAt) {
    label = `Saved ${relativeTime(savedAt)}`;
  } else if (initialIsSynced) {
    label = "Synced from Google Docs";
  } else {
    label = "Autosaves as you type";
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
  // A freshly created Google Doc returns "\n" for body. Treat single-newline
  // as effectively empty so the editor doesn't show "Unsaved changes" on load.
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

function friendlySaveError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail;
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      return detail.message;
    }
    if (typeof detail === "string") {
      return summarizeRawGoogleError(detail);
    }
  } catch {
    /* not JSON, fall through */
  }
  return summarizeRawGoogleError(raw);
}

function summarizeRawGoogleError(raw: string): string {
  if (/SERVICE_DISABLED|has not been used in project/.test(raw)) {
    return "Couldn't sync to Google Docs right now. Your edit isn't lost — try again in a moment.";
  }
  if (/PERMISSION_DENIED|insufficient/i.test(raw)) {
    return "Google rejected the request. Try disconnecting and reconnecting Google in Settings → Accounts.";
  }
  if (/rateLimit|quotaExceeded/i.test(raw)) {
    return "Google is rate-limiting us right now. Try again in a moment.";
  }
  return "Couldn't save right now. Try again in a moment.";
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

