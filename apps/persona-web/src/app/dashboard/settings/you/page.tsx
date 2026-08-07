"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CalendarDays,
  Copy,
  Globe2,
  MessageSquare,
  QrCode,
  Share2,
  X,
} from "lucide-react";
import { AvatarPicker, Button, EmptyState, FieldLabel, Input, Textarea } from "@/components/ui";
import DeleteAccountModal from "@/components/settings/DeleteAccountModal";
import { QrCode as QrCodeImage } from "@/components/QrCode";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";
import { defaultPersonaStyle, generateAvatarDataUri } from "@/lib/dicebear";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Memory service — social links are mirrored here so matches can show them.
const MEMORY_API = (process.env.NEXT_PUBLIC_MEMORY_API_URL || "https://api.zynd.ai").replace(/\/$/, "");

interface PersonaProfile {
  avatar_url?: string | null;
  picture?: string | null;
  interests?: string[] | string;
  title?: string | null;
  organization?: string | null;
  location?: string | null;
  visibility?: Partial<Record<VisibilityKey, boolean>>;
  [key: string]: unknown;
}

interface Persona {
  name: string;
  agent_id?: string;
  agent_handle?: string | null;
  description: string;
  capabilities?: string[];
  profile?: PersonaProfile;
}

interface LinkedInData {
  present: boolean;
  raw_profile?: {
    skills?: string[];
    headline?: string;
  };
}

interface DraftProfile {
  name: string;
  bio: string;
  title: string;
  organization: string;
  location: string;
  tags: string[];
  linkedin: string;
  twitter: string;
  instagram: string;
  telegram: string;
  website: string;
}

// Social fields shown in the "Links" section; also what ZYND surfaces with a match.
const SOCIAL_FIELDS: { key: "linkedin" | "twitter" | "instagram" | "telegram" | "website"; label: string; placeholder: string }[] = [
  { key: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/you" },
  { key: "twitter", label: "Twitter / X", placeholder: "@handle or url" },
  { key: "instagram", label: "Instagram", placeholder: "@handle" },
  { key: "telegram", label: "Telegram", placeholder: "@handle" },
  { key: "website", label: "Website", placeholder: "https://…" },
];

type VisibilityKey = "publicProfile" | "calendar" | "chat" | "contact";

const EMPTY_DRAFT: DraftProfile = {
  name: "",
  bio: "",
  title: "",
  organization: "",
  location: "",
  tags: [],
  linkedin: "",
  twitter: "",
  instagram: "",
  telegram: "",
  website: "",
};

// Default visibility — what a brand-new card shows publicly. Stored on
// persona.profile.visibility; loaded into state on mount and sent back
// on Save so toggling actually persists.
const DEFAULT_VISIBILITY: Record<VisibilityKey, boolean> = {
  publicProfile: true,
  calendar: true,
  chat: true,
  contact: false,
};

function intoTags(v: unknown): string[] {
  if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean);
  if (typeof v === "string") {
    return v.split(",").map((x) => x.trim()).filter(Boolean);
  }
  return [];
}

export default function YouPage() {
  const router = useRouter();
  const { user } = useDashboard();

  const [persona, setPersona] = useState<Persona | null>(null);
  const [loading, setLoading] = useState(true);
  const [linkedin, setLinkedin] = useState<LinkedInData | null>(null);
  const [draft, setDraft] = useState<DraftProfile>(EMPTY_DRAFT);
  const [tagInput, setTagInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [refreshingTopics, setRefreshingTopics] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [refreshedNotice, setRefreshedNotice] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [avatarPickerOpen, setAvatarPickerOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [visibility, setVisibility] = useState<Record<VisibilityKey, boolean>>(DEFAULT_VISIBILITY);

  const oauthAvatarUrl = (user?.user_metadata as Record<string, string> | null)
    ?.avatar_url as string | undefined;

  const personaAvatarUrl =
    persona?.profile?.avatar_url ||
    persona?.profile?.picture ||
    oauthAvatarUrl ||
    (persona?.name ? generateAvatarDataUri(defaultPersonaStyle(), persona.name) : undefined);

  const fetchAll = useCallback(async () => {
    if (!user) return;
    try {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const jwt = session?.access_token;

      const [personaRes, linkedinRes] = await Promise.all([
        fetch(`${API}/api/persona/${user.id}/status`),
        jwt
          ? fetch(`${API}/api/linkedin/me`, {
              headers: { Authorization: `Bearer ${jwt}` },
            })
          : Promise.resolve(null),
      ]);

      if (personaRes.ok) {
        const data = await personaRes.json();
        if (data.deployed) setPersona(data);
      }
      if (linkedinRes && linkedinRes.ok) {
        setLinkedin(await linkedinRes.json());
      }
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  useEffect(() => {
    const profile = persona?.profile || {};
    setDraft({
      name: persona?.name ?? "",
      bio: persona?.description ?? "",
      title: String(profile.title || ""),
      organization: String(profile.organization || ""),
      location: String(profile.location || ""),
      tags: intoTags(profile.interests),
      linkedin: String(profile.linkedin || ""),
      twitter: String(profile.twitter || ""),
      instagram: String(profile.instagram || ""),
      telegram: String(profile.telegram || ""),
      website: String(profile.website || ""),
    });
    // Visibility is stored as a small partial object on the profile;
    // missing keys fall back to defaults so older personas (created
    // before this field existed) keep their original behaviour.
    const stored = profile.visibility || {};
    setVisibility({
      publicProfile: stored.publicProfile ?? DEFAULT_VISIBILITY.publicProfile,
      calendar: stored.calendar ?? DEFAULT_VISIBILITY.calendar,
      chat: stored.chat ?? DEFAULT_VISIBILITY.chat,
      contact: stored.contact ?? DEFAULT_VISIBILITY.contact,
    });
  }, [persona]);

  const skills = useMemo(
    () => linkedin?.raw_profile?.skills ?? [],
    [linkedin?.raw_profile?.skills],
  );

  // The first name of the principal — used as the persona's display label
  // ("Chat with Sahil's persona", "This week, Sahil's persona...").
  const firstName = (draft.name || persona?.name || "")
    .trim()
    .split(/\s+/)[0];
  const personaLabel = firstName ? `${firstName}'s persona` : "your persona";

  const memoryBranches = useMemo(
    () => buildMemoryBranches(draft, skills),
    [draft, skills],
  );
  const memoryCount = memoryBranches.length + draft.tags.length;

  const publicPath = user?.id ? `/p/${user.id}` : "#";
  // Render-time absolute URL for QR + share. Falls back to "" during SSR;
  // both the QR component and the copy/share handlers no-op on empty.
  const publicHref = useMemo(() => {
    if (typeof window === "undefined" || !user?.id) return "";
    return new URL(`/p/${user.id}`, window.location.origin).toString();
  }, [user?.id]);
  // Pretty display form — host + full path, no scheme. Survives SSR by
  // checking window first. Kept as the real path (not a truncated id) so
  // the visible text always matches what the link actually resolves to;
  // long ids overflow with an ellipsis in CSS instead of being lied about.
  const publicDisplay = useMemo(() => {
    if (typeof window === "undefined" || !user?.id) return "";
    const host = window.location.host;
    return `${host}/p/${user.id}`;
  }, [user?.id]);

  const updateDraft = (patch: Partial<DraftProfile>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setSaved(false);
  };

  const toggleVisibility = (key: VisibilityKey) => {
    setVisibility((current) => ({ ...current, [key]: !current[key] }));
    setSaved(false);
  };

  const commitTag = () => {
    const v = tagInput.trim();
    if (!v) return;
    setDraft((current) => ({
      ...current,
      tags: current.tags.includes(v) ? current.tags : [...current.tags, v],
    }));
    setTagInput("");
    setSaved(false);
  };

  const removeTag = (tag: string) => {
    setDraft((current) => ({
      ...current,
      tags: current.tags.filter((t) => t !== tag),
    }));
    setSaved(false);
  };

  const publicUrl = useCallback(() => {
    if (typeof window === "undefined" || !user?.id) return "";
    return new URL(`/p/${user.id}`, window.location.origin).toString();
  }, [user?.id]);

  const handleShareCard = useCallback(async () => {
    const url = publicUrl();
    if (!url) return;
    try {
      if (navigator.share) {
        await navigator.share({ url, title: `${draft.name || "My"} persona card` });
      } else {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      }
    } catch {
      /* Share was dismissed. */
    }
  }, [draft.name, publicUrl]);

  const handleCopyLink = useCallback(async () => {
    const url = publicUrl();
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }, [publicUrl]);

  const handleSaveAvatar = useCallback(
    async (dataUri: string) => {
      if (!user) throw new Error("Not signed in");
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const res = await fetch(`${API}/api/persona/${user.id}/profile`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
        },
        body: JSON.stringify({
          profile: { ...(persona?.profile || {}), avatar_url: dataUri },
        }),
      });
      if (!res.ok) throw new Error((await res.text()) || "Couldn't save avatar.");
      setPersona(await res.json());
    },
    [user, persona],
  );

  const handleSave = async () => {
    if (!user) throw new Error("Not signed in");
    if (!draft.name.trim()) {
      setSaveError("Give the card a public name.");
      return;
    }
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const res = await fetch(`${API}/api/persona/${user.id}/profile`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
        },
        body: JSON.stringify({
          name: draft.name.trim(),
          description: draft.bio.trim(),
          profile: {
            ...(persona?.profile || {}),
            title: draft.title.trim(),
            organization: draft.organization.trim(),
            location: draft.location.trim(),
            interests: draft.tags,
            visibility,
            linkedin: draft.linkedin.trim(),
            twitter: draft.twitter.trim(),
            instagram: draft.instagram.trim(),
            telegram: draft.telegram.trim(),
            website: draft.website.trim(),
          },
        }),
      });
      if (!res.ok) throw new Error((await res.text()) || "Couldn't save that.");
      setPersona(await res.json());
      // Mirror the social links into ZYND memory-layer so matches surface them.
      // Best-effort — the persona profile is already saved above.
      try {
        await fetch(`${MEMORY_API}/me/social-links`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
          },
          body: JSON.stringify({
            linkedin: draft.linkedin.trim(),
            twitter: draft.twitter.trim(),
            instagram: draft.instagram.trim(),
            telegram: draft.telegram.trim(),
            website: draft.website.trim(),
          }),
        });
      } catch {
        /* memory-layer sync is best-effort */
      }
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2200);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Couldn't save that.");
    } finally {
      setSaving(false);
    }
  };

  const handleRefreshTopics = async () => {
    setRefreshingTopics(true);
    setRefreshError(null);
    setRefreshedNotice(false);
    try {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      if (!session?.access_token) {
        setRefreshError("Sign in again to refresh from LinkedIn.");
        return;
      }
      const res = await fetch(`${API}/api/linkedin/scrape`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        setRefreshError((body?.detail as string) || "Couldn't refresh from LinkedIn — try again.");
        return;
      }
      setTimeout(() => void fetchAll(), 2000);
      setRefreshedNotice(true);
      setTimeout(() => setRefreshedNotice(false), 3000);
    } catch {
      setRefreshError("Couldn't reach LinkedIn — try again in a moment.");
    } finally {
      setRefreshingTopics(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!user) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const res = await fetch(`${API}/api/persona/${user.id}/account`, {
        method: "DELETE",
      });
      if (!res.ok) {
        throw new Error((await res.text()) || "Couldn't delete the account.");
      }
      try {
        await getSupabase().auth.signOut();
      } catch {
        /* ignore */
      }
      router.replace("/");
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Something got tangled.");
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="persona-workbench">
        <EmptyState title="Loading your profile…" body="One moment." />
      </div>
    );
  }

  if (!persona) {
    return (
      <div className="persona-workbench">
        <EmptyState
          title="No persona deployed yet"
          body="Finish onboarding to create your persona, then come back here to edit the card people see."
        />
      </div>
    );
  }

  return (
    <div className="persona-workbench">
      <header className="persona-workbench-head">
        <div>
          <p className="persona-kicker">Your profile</p>
          <h1 className="display-s">The card people see.</h1>
        </div>
        <div className="persona-head-actions">
          <a href={publicPath} target="_blank" rel="noopener noreferrer" className="persona-public-link">
            <Globe2 size={18} strokeWidth={2} />
            <span className="persona-public-link-text">{publicDisplay || "your card"}</span>
          </a>
          <Button variant="secondary" size="sm" leftIcon={<QrCode size={16} strokeWidth={2} />} onClick={() => setQrOpen(true)}>
            Show QR
          </Button>
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Share2 size={16} strokeWidth={2} />}
            onClick={handleShareCard}
          >
            {copied ? "Copied" : "Share card"}
          </Button>
        </div>
      </header>

      <div className="persona-workbench-grid">
        <section className="persona-editor-card">
          <div className="persona-editor-section persona-identity-section">
            <h2>Identity</h2>
            <div className="persona-identity-row">
              <button
                type="button"
                className="persona-avatar-edit avatar-edit-wrap"
                onClick={() => setAvatarPickerOpen(true)}
                aria-label="Change profile photo"
              >
                <ProfileAvatar src={personaAvatarUrl} name={draft.name} />
                <span className="avatar-edit-overlay">Edit</span>
              </button>
              <div className="persona-identity-fields">
                <FieldLabel htmlFor="persona-name">Name</FieldLabel>
                <Input
                  id="persona-name"
                  value={draft.name}
                  onChange={(e) => updateDraft({ name: e.target.value })}
                  placeholder="Your name"
                  disabled={saving}
                />
                <FieldLabel htmlFor="persona-title">Title</FieldLabel>
                <Input
                  id="persona-title"
                  value={draft.title}
                  onChange={(e) => updateDraft({ title: e.target.value })}
                  placeholder="Title, role, or headline"
                  disabled={saving}
                />
                <div className="persona-mini-grid">
                  <div>
                    <FieldLabel htmlFor="persona-org">Company</FieldLabel>
                    <Input
                      id="persona-org"
                      value={draft.organization}
                      onChange={(e) => updateDraft({ organization: e.target.value })}
                      placeholder="Company"
                      disabled={saving}
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="persona-location">Location</FieldLabel>
                    <Input
                      id="persona-location"
                      value={draft.location}
                      onChange={(e) => updateDraft({ location: e.target.value })}
                      placeholder="Location"
                      disabled={saving}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="persona-editor-section">
            <FieldLabel htmlFor="persona-public-bio">Bio — shown publicly</FieldLabel>
            <Textarea
              id="persona-public-bio"
              value={draft.bio}
              onChange={(e) => updateDraft({ bio: e.target.value })}
              placeholder="Working on tools that help small teams feel calm. Coffee shops > conference rooms."
              rows={3}
              maxLength={220}
              disabled={saving}
              className="persona-bio-input"
            />
            <p className="persona-char-count">{draft.bio.length}/220</p>
          </div>

          <div className="persona-editor-section">
            <h2>Links</h2>
            <p className="persona-section-sub">
              Shared with people you match with on ZYND so they can reach you.
            </p>
            <div className="persona-mini-grid">
              {SOCIAL_FIELDS.map((f) => (
                <div key={f.key}>
                  <FieldLabel htmlFor={`persona-social-${f.key}`}>{f.label}</FieldLabel>
                  <Input
                    id={`persona-social-${f.key}`}
                    value={draft[f.key]}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDraft((c) => ({ ...c, [f.key]: v }));
                      setSaved(false);
                    }}
                    placeholder={f.placeholder}
                    disabled={saving}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="persona-editor-section">
            <h2>Visibility</h2>
            <p className="persona-section-sub">
              What people who scan can do. Each row applies the moment you save.
            </p>
            <div className="persona-visibility-list">
              <VisibilityToggle
                checked={visibility.publicProfile}
                onChange={() => toggleVisibility("publicProfile")}
                label="See your name, title, bio"
              />
              <VisibilityToggle
                checked={visibility.calendar}
                onChange={() => toggleVisibility("calendar")}
                label="Book time on your calendar (up to 30 min)"
              />
              <VisibilityToggle
                checked={visibility.chat}
                onChange={() => toggleVisibility("chat")}
                label={`Chat with ${personaLabel} about your work`}
              />
              <VisibilityToggle
                checked={visibility.contact}
                onChange={() => toggleVisibility("contact")}
                label="See email + phone (only after you approve)"
              />
            </div>
          </div>

          <div className="persona-editor-section persona-memory-head">
            <div>
              <h2>Profile tags &middot; {memoryCount}</h2>
              <p className="persona-section-sub">
                What {personaLabel} leads with about you. Title, company, and location above
                add tags automatically — add your own below too.
              </p>
            </div>
            <button type="button" className="text-link" onClick={handleRefreshTopics} disabled={refreshingTopics}>
              {refreshingTopics ? "Refreshing…" : "Refresh from LinkedIn"}
              <ArrowRight size={13} strokeWidth={2} />
            </button>
          </div>
          {refreshError && <p className="persona-save-error">{refreshError}</p>}
          {refreshedNotice && <p className="persona-save-success">Refreshed.</p>}

          <div className="persona-branch-row">
            {memoryBranches.map((branch) => (
              <span key={branch.kind} className={`persona-branch persona-branch-${branch.tone}`} title="Auto-added from Title/Company/Location above">
                <span>{branch.kind}</span>
                {branch.label}
              </span>
            ))}
            {draft.tags.map((tag) => (
              <button
                type="button"
                key={tag}
                className="persona-branch persona-branch-neutral"
                onClick={() => removeTag(tag)}
                title={`Remove ${tag}`}
              >
                <span>tag</span>
                {tag}
                <X size={12} strokeWidth={2} />
              </button>
            ))}
            <input
              className="persona-branch-input"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") {
                  e.preventDefault();
                  commitTag();
                }
              }}
              onBlur={commitTag}
              placeholder="+ Add tag"
              disabled={saving}
            />
          </div>

          <div className="persona-save-row">
            <div>
              {saveError && <p className="persona-save-error">{saveError}</p>}
              {saved && <p className="persona-save-success">Saved.</p>}
            </div>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </section>

        <aside className="persona-preview-column">
          <div className="persona-preview-label-row">
            <p className="persona-kicker">Public preview</p>
            <span className="persona-live-pill">
              <span />
              Live
            </span>
          </div>
          <PersonaPreviewCard
            draft={draft}
            avatarUrl={personaAvatarUrl}
            personaLabel={personaLabel}
          />

          <div className="persona-audit-card">
            <div className="persona-audit-head">
              <strong>This week, {personaLabel}...</strong>
            </div>
            <p className="persona-section-sub">
              Activity summary will appear here once {personaLabel} has been
              active. Until then, the dashboard&apos;s Inbox and Meetings
              tabs are the source of truth.
            </p>
          </div>
        </aside>
      </div>

      <section className="persona-account-card">
        <div>
          <h2>Account</h2>
          <p>Deleting removes your brief, matches, meetings, and login. It can&rsquo;t be undone.</p>
        </div>
        <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
          Delete account
        </Button>
      </section>

      {qrOpen && (
        <div
          className="modal-scrim"
          role="dialog"
          aria-modal="true"
          aria-label="Share QR code"
          onClick={(e) => {
            if (e.target === e.currentTarget) setQrOpen(false);
          }}
        >
          <div className="persona-qr-modal">
            <button type="button" className="persona-modal-close" onClick={() => setQrOpen(false)} aria-label="Close">
              <X size={18} strokeWidth={2} />
            </button>
            <p className="persona-kicker">Share card</p>
            <h2>{publicDisplay || "your card"}</h2>
            <div className="persona-qr-art">
              {publicHref ? (
                <QrCodeImage value={publicHref} size={220} />
              ) : (
                <span className="persona-section-sub">Saving your handle…</span>
              )}
            </div>
            <Button variant="primary" leftIcon={<Copy size={16} strokeWidth={2} />} onClick={handleCopyLink}>
              {copied ? "Copied" : "Copy link"}
            </Button>
          </div>
        </div>
      )}

      {deleteOpen && (
        <DeleteAccountModal
          personaName={persona?.name ?? "your account"}
          deleting={deleting}
          error={deleteError}
          onCancel={() => {
            if (!deleting) {
              setDeleteOpen(false);
              setDeleteError(null);
            }
          }}
          onConfirm={handleDeleteAccount}
        />
      )}

      {avatarPickerOpen && (
        <AvatarPicker
          mode="persona"
          seed={persona?.name ?? user?.email?.split("@")[0] ?? "persona"}
          currentUrl={persona?.profile?.avatar_url}
          onSave={handleSaveAvatar}
          onClose={() => setAvatarPickerOpen(false)}
        />
      )}
    </div>
  );
}

function PersonaPreviewCard({
  draft,
  avatarUrl,
  personaLabel,
}: {
  draft: DraftProfile;
  avatarUrl?: string | null;
  personaLabel: string;
}) {
  const subline = buildSubline(draft);
  const bio = draft.bio.trim();

  return (
    <div className="persona-card-preview">
      <div className="persona-preview-top">
        <span>persona</span>
        <span>v &middot; 2026</span>
      </div>
      <ProfileAvatar src={avatarUrl} name={draft.name} compact />
      <h2>{draft.name || "Your name"}</h2>
      {subline && <p className="persona-preview-role">{subline}</p>}
      {bio && <p className="persona-preview-bio">&quot;{bio}&quot;</p>}
      <div className="persona-preview-actions">
        <button type="button" disabled title="Preview only — this is what visitors will see, not a live action here">
          <MessageSquare size={16} strokeWidth={2} />
          Chat with {personaLabel}
        </button>
        <button type="button" disabled title="Preview only — this is what visitors will see, not a live action here">
          <CalendarDays size={16} strokeWidth={2} />
          Book time
        </button>
      </div>
      <p className="persona-preview-disclaimer">Preview only — buttons work on your live public card</p>
    </div>
  );
}

function VisibilityToggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className="persona-toggle-row"
      onClick={onChange}
    >
      <span className={`persona-toggle ${checked ? "is-on" : ""}`} aria-hidden>
        <span />
      </span>
      <span>{label}</span>
    </button>
  );
}

function ProfileAvatar({
  src,
  name,
  compact = false,
}: {
  src?: string | null;
  name?: string | null;
  compact?: boolean;
}) {
  return (
    <span className={`persona-avatar ${compact ? "persona-avatar-compact" : ""}`}>
      {src ? (
        <img src={src} alt={name || "Profile"} referrerPolicy="no-referrer" />
      ) : (
        <span>{initials(name)}</span>
      )}
    </span>
  );
}

function buildMemoryBranches(
  draft: DraftProfile,
  skills: string[],
): { kind: string; label: string; tone: string }[] {
  // Only emit branches we have real data for. Empty list is fine —
  // the caller will fall back to the "+ Add branch" input.
  const out: { kind: string; label: string; tone: string }[] = [];
  const work = [draft.title, draft.organization].filter(Boolean).join(" at ");
  if (work) out.push({ kind: "work", label: work, tone: "blue" });
  else if (skills[0]) out.push({ kind: "work", label: skills[0], tone: "blue" });
  if (draft.location) out.push({ kind: "based", label: draft.location, tone: "green" });
  return out;
}

function buildSubline(draft: DraftProfile) {
  const role = [draft.title, draft.organization].filter(Boolean).join(" at ");
  return [role, draft.location].filter(Boolean).join(" - ");
}

function initials(name?: string | null) {
  const parts = (name || "You").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return (parts[0]?.slice(0, 2) || "Y").toUpperCase();
}
