"use client";

import { useSectionAutosave } from "@/hooks/useSectionAutosave";
import { imgProxyUrl } from "@/lib/avatar";
import { ownerHomeEnabled } from "@/lib/owner-home";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent } from "react";
import Link from "next/link";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import { Check, Loader2 } from "lucide-react";
import {
  type AgentProfileCard,
  updateCard,
  githubLoginFromUrl,
  refreshCardGithub,
  refreshCardLinkedIn,
} from "@/lib/cards";
import { Toast, type ShowToast, type ToastType } from "./edit-ui";
import {
  TABS, TAB_SECTIONS, cardFromForm, formFromCard, formLinks, initialsOf, tabForHash,
  type EditForm, type SetField, type TabKey,
} from "./edit-form";
import { ProfileTab } from "./profile-tab";
import { InterestsTab } from "./interests-tab";
import { ImportedTab } from "./imported-tab";
import { AiTab } from "./ai-tab";
import { EditPageAsk } from "@/components/asks/EditPageAsk";

const geist = Geist({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--pe-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--pe-mono" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--pe-display" });
const FONT_VARS = `${geist.variable} ${geistMono.variable} ${spaceGrotesk.variable}`;

// The open tab lives in the URL hash, so /edit#inbox style deep links keep
// working. Tab clicks replace the hash without a history entry and announce it
// themselves, because replaceState doesn't fire hashchange.
const TAB_EVENT = "pe-tabchange";
function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  window.addEventListener(TAB_EVENT, onChange);
  return () => {
    window.removeEventListener("hashchange", onChange);
    window.removeEventListener(TAB_EVENT, onChange);
  };
}
const readHash = () => decodeURIComponent(window.location.hash.slice(1));
const serverHash = () => "";
function goToHash(hash: string) {
  window.history.replaceState(null, "", `#${hash}`);
  window.dispatchEvent(new Event(TAB_EVENT));
}

interface Props { initialCard: AgentProfileCard; handle: string; token: string; }

export function EditProfileClient({ initialCard, handle, token }: Props) {
  const [draft, setDraft] = useState<AgentProfileCard>({ ...initialCard, status: ownerHomeEnabled ? initialCard.status : "published" });
  const [form, setForm] = useState<EditForm>(() => formFromCard(initialCard));
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: ToastType } | null>(null);
  const [reviewCount, setReviewCount] = useState(0);
  const tabsTop = useRef<HTMLDivElement>(null);
  const hash = useSyncExternalStore(subscribeHash, readHash, serverHash);
  const tab = tabForHash(hash);

  const set = useCallback<SetField>((key, value) => setForm((f) => ({ ...f, [key]: value })), []);
  const showToast = useCallback<ShowToast>((msg, type = "info") => setToast({ msg, type }), []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  // A section anchor (not a tab name) scrolls to its card once its tab shows.
  useEffect(() => {
    if (!hash || TABS.some((t) => t.key === hash)) return;
    document.getElementById(hash)?.scrollIntoView({ block: "start" });
  }, [hash]);

  const headAvatar = imgProxyUrl(form.avatar, null, handle);
  const formCard = cardFromForm(draft, form);
  const autosave = useSectionAutosave(handle, token, {
    identity: { identity: formCard.identity },
    summary: { summary: formCard.summary, availability: formCard.availability, industries: formCard.industries },
    signals: { working_on: formCard.working_on, connect_with: formCard.connect_with, love_talking_about: formCard.love_talking_about },
    skills: { skills: formCard.skills },
    settings: { calendly_url: formCard.calendly_url ?? null, google_calendar_url: formCard.google_calendar_url ?? null },
  }, ownerHomeEnabled, false);

  function restoreUnsavedEdits() {
    if (!autosave.recovery) return;
    const restored = { ...draft, ...Object.assign({}, ...Object.values(autosave.recovery)) } as AgentProfileCard;
    setForm(formFromCard(restored));
    autosave.discardRecovery();
  }

  // Edits are saved only on request, so a slip (an accidental removal) can be discarded.
  async function saveChanges() {
    const ok = await autosave.flush();
    showToast(ok ? "Changes saved" : "Couldn't save — try again", ok ? "ok" : "err");
  }

  function discardChanges() {
    const savedCard = { ...draft, ...Object.assign({}, ...Object.values(autosave.saved)) } as AgentProfileCard;
    setForm(formFromCard(savedCard));
    autosave.reset();
    showToast("Changes discarded");
  }

  const saveShortcut = useRef<() => void>(() => {});
  useEffect(() => {
    saveShortcut.current = () => {
      if (autosave.unsaved && autosave.status !== "Saving…") void saveChanges();
    };
  });
  useEffect(() => {
    if (!ownerHomeEnabled) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveShortcut.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Only without autosave (S10 flag off): one explicit save of the whole card.
  async function save() {
    setSaving(true);
    const result = await updateCard(handle, { ...cardFromForm(draft, form), status: "published" }, token);
    if (result) {
      setDraft({ ...result, status: "published" });
      showToast("Saved — your profile is live", "ok");
    } else {
      showToast("Save failed — try again", "err");
    }
    setSaving(false);
  }

  async function refreshFromLinks() {
    const links = formLinks(form);
    const linkedinUrl = links.linkedin || "";
    const githubHandle = links.github ? githubLoginFromUrl(links.github) : null;
    if (!linkedinUrl && !githubHandle) {
      showToast("Add a GitHub or LinkedIn URL first", "err");
      return;
    }
    if (ownerHomeEnabled && autosave.unsaved) {
      showToast("Save or discard your changes first", "err");
      return;
    }
    setRefreshing(true);
    try {
      // Wait for any save still in flight before a source refresh; don't replace the whole
      // card with an older local memory snapshot or publish a private card.
      if (ownerHomeEnabled && !await autosave.flush()) return;
      const saved = ownerHomeEnabled ? draft : await updateCard(handle, { ...cardFromForm(draft, form), status: "published" }, token);
      if (saved) setDraft({ ...saved, status: ownerHomeEnabled ? saved.status : "published" });

      const parts: string[] = [];
      const failures: string[] = [];
      let next = saved ?? draft;

      if (linkedinUrl) {
        try {
          const data = await refreshCardLinkedIn(handle, token, linkedinUrl);
          if (data.work_experience) {
            next = { ...next, work_experience: data.work_experience };
            parts.push("LinkedIn");
          }
        } catch (err) {
          failures.push(err instanceof Error ? err.message : "LinkedIn refresh failed");
        }
      }
      if (githubHandle) {
        try {
          const data = await refreshCardGithub(handle, token, githubHandle);
          next = {
            ...next,
            github_stats: data.github_stats ?? next.github_stats,
            contribution_stats: data.contribution_stats ?? next.contribution_stats,
          };
          parts.push("GitHub");
        } catch (err) {
          failures.push(err instanceof Error ? err.message : "GitHub refresh failed");
        }
      }

      setDraft({ ...next, status: ownerHomeEnabled ? next.status : "published" });
      if (parts.length > 0 && failures.length === 0) {
        showToast(`Updated ${parts.join(" & ")}`, "ok");
      } else if (parts.length > 0) {
        showToast(`Updated ${parts.join(" & ")}. ${failures[0]}`, "err");
      } else {
        showToast(failures[0] || "Refresh failed", "err");
      }
    } catch {
      showToast("Refresh failed", "err");
    } finally {
      setRefreshing(false);
    }
  }

  function selectTab(key: TabKey) {
    goToHash(key);
    // Switching from deep in a long tab: bring the new tab's top into view.
    if ((tabsTop.current?.getBoundingClientRect().top ?? 0) < 0) tabsTop.current?.scrollIntoView();
  }

  function onTabKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = TABS.findIndex((t) => t.key === tab);
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length
      : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
      : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    selectTab(TABS[next].key);
    document.getElementById(`pe-tab-${TABS[next].key}`)?.focus();
  }

  const saveState = autosave.status === "Saving…" ? "saving"
    : autosave.status === "Not saved" ? "error"
    : autosave.unsaved ? "unsaved" : "saved";

  return (
    <>
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className={`pe ${FONT_VARS}`}>
        <div className="pe-shell">
          <header className="pe-head">
            <div className="pe-head-id">
              <span className="pe-head-avatar" aria-hidden="true">
                {headAvatar ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={headAvatar} alt="" />
                ) : initialsOf(form.name)}
              </span>
              <div style={{ minWidth: 0 }}>
                <h1 className="pe-h1">Edit your card</h1>
                <div className="pe-head-meta">
                  <span className="pe-url">cards.zynd.ai/p/{handle}</span>
                  {ownerHomeEnabled && (
                    <span className="pe-save">
                      <span role="status" aria-live="polite" className={`pe-save-state is-${saveState}`}>
                        {saveState === "saving" ? <Loader2 size={12} className="pe-spin" /> : <span className="pe-dot" />}
                        {saveState === "saved" ? "All changes saved" : saveState === "saving" ? "Saving…"
                          : saveState === "unsaved" ? "Unsaved changes"
                          : `Not saved${autosave.error ? ` — ${autosave.error}` : ""}`}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="pe-head-actions">
              {ownerHomeEnabled && <Link href="/home" className="pe-btn pe-btn-secondary">Owner home</Link>}
              <Link href={`/p/${handle}`} className="pe-btn pe-btn-secondary">View card</Link>
              {ownerHomeEnabled && autosave.unsaved && saveState !== "saving" && (
                <button type="button" className="pe-btn pe-btn-secondary" onClick={discardChanges}>Discard</button>
              )}
              {ownerHomeEnabled && (
                <button type="button" className="pe-btn pe-btn-primary" onClick={() => void saveChanges()}
                  disabled={!autosave.unsaved || saveState === "saving"}>
                  {saveState === "saving" ? <Loader2 size={16} className="pe-spin" /> : <Check size={16} />}
                  {saveState === "saving" ? "Saving…" : "Save changes"}
                </button>
              )}
              {!ownerHomeEnabled && (
                <button type="button" className="pe-btn pe-btn-primary" onClick={save} disabled={saving}>
                  {saving ? <Loader2 size={16} className="pe-spin" /> : <Check size={16} />}
                  {saving ? "Saving…" : "Save changes"}
                </button>
              )}
            </div>
          </header>

          {ownerHomeEnabled && autosave.recovery && (
            <aside role="status" className="pe-banner">
              <p>You have unsaved changes from your last visit.</p>
              <div className="pe-banner-actions">
                <button type="button" className="pe-btn pe-btn-primary pe-btn-sm" onClick={restoreUnsavedEdits}>Restore unsaved changes</button>
                <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={autosave.discardRecovery}>Discard draft</button>
              </div>
            </aside>
          )}

          <div ref={tabsTop} />
          <div className="pe-tabbar">
            <div className="pe-tabs" role="tablist" aria-label="Edit sections" onKeyDown={onTabKey}>
              {TABS.map((t) => {
                const selected = t.key === tab;
                const tabSaving = saveState !== "saved" &&
                  TAB_SECTIONS[t.key]?.some((s) => autosave.sectionStates[s] === "Saving…");
                const badge = t.key === "ai" ? reviewCount : 0;
                return (
                  <button key={t.key} type="button" role="tab" id={`pe-tab-${t.key}`} className="pe-tab"
                    aria-selected={selected} aria-controls={`pe-panel-${t.key}`} tabIndex={selected ? 0 : -1}
                    aria-label={badge > 0 ? `${t.label}, ${badge} to review` : undefined}
                    onClick={() => selectTab(t.key)}>
                    <span className="pe-tab-long">{t.label}</span>
                    <span className="pe-tab-short">{t.short}</span>
                    {badge > 0 && <span className="pe-tab-badge" aria-hidden="true">{badge}</span>}
                    {tabSaving && <span className="pe-tab-saving" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          </div>

          <div role="tabpanel" id="pe-panel-profile" aria-labelledby="pe-tab-profile" className="pe-panel" hidden={tab !== "profile"}>
            <ProfileTab form={form} set={set} handle={handle} token={token} />
          </div>
          <div role="tabpanel" id="pe-panel-interests" aria-labelledby="pe-tab-interests" className="pe-panel" hidden={tab !== "interests"}>
            <InterestsTab form={form} set={set} />
            {ownerHomeEnabled && (
              <EditPageAsk
                key={handle}
                token={token}
                initial={initialCard.beacon}
                author={{ handle, name: initialCard.identity.name, headline: initialCard.identity.headline, avatar_url: initialCard.identity.avatar_url || null, location: initialCard.identity.location }}
              />
            )}
          </div>
          <div role="tabpanel" id="pe-panel-imported" aria-labelledby="pe-tab-imported" className="pe-panel" hidden={tab !== "imported"}>
            <ImportedTab card={draft} links={formLinks(form)} refreshing={refreshing} disabled={saving}
              onRefresh={refreshFromLinks} onEditLinks={() => goToHash("presence")} />
          </div>
          <div role="tabpanel" id="pe-panel-ai" aria-labelledby="pe-tab-ai" className="pe-panel" hidden={tab !== "ai"}>
            <AiTab handle={handle} token={token} firstName={(form.name || "You").split(" ")[0]}
              initialFacts={(initialCard.zynd_memory ?? []) as Array<Record<string, unknown>>}
              onFactsChange={(facts) => setDraft((prev) => ({ ...prev, zynd_memory: facts }))}
              onReviewCount={setReviewCount} showToast={showToast} />
          </div>
        </div>
      </div>
    </>
  );
}
