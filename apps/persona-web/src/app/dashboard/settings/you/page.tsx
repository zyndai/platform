"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AvatarPicker, Button } from "@/components/ui";
import PersonaCardForm from "@/components/settings/PersonaCardForm";
import DeleteAccountModal from "@/components/settings/DeleteAccountModal";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";
import { defaultPersonaStyle, generateAvatarDataUri } from "@/lib/dicebear";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Persona {
  name: string;
  description: string;
  capabilities?: string[];
  profile?: { avatar_url?: string | null; interests?: string[] | string };
}

interface LinkedInData {
  present: boolean;
  raw_profile?: {
    skills?: string[];
    headline?: string;
  };
}

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
  const [linkedin, setLinkedin] = useState<LinkedInData | null>(null);
  const [refreshingTopics, setRefreshingTopics] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [avatarPickerOpen, setAvatarPickerOpen] = useState(false);

  // OAuth avatar from Google/LinkedIn — we don't overwrite this by default,
  // but the user can override it by picking a DiceBear avatar.
  const oauthAvatarUrl = (user?.user_metadata as Record<string, string> | null)
    ?.avatar_url as string | undefined;

  // Persona's saved avatar takes priority; falls back to OAuth, then to a
  // deterministic DiceBear based on the user's name.
  const personaAvatarUrl =
    (persona?.profile?.avatar_url) ||
    oauthAvatarUrl ||
    (persona?.name ? generateAvatarDataUri(defaultPersonaStyle(), persona.name) : undefined);

  const avatarUrl = personaAvatarUrl;

  const fetchAll = useCallback(async () => {
    if (!user) return;
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
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
  }, [user]);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  const initialName = persona?.name ?? "";
  const initialBio = persona?.description ?? "";
  const initialTags = useMemo(
    () => intoTags(persona?.profile?.interests),
    [persona],
  );

  const handleSaveAvatar = useCallback(
    async (dataUri: string) => {
      if (!user) throw new Error("Not signed in");
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
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

  const handleSave = async ({
    name,
    bio,
    tags,
  }: {
    name: string;
    bio: string;
    tags: string[];
  }) => {
    if (!user) throw new Error("Not signed in");
    const res = await fetch(`${API}/api/persona/${user.id}/profile`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        description: bio,
        profile: { ...(persona?.profile || {}), interests: tags },
      }),
    });
    if (!res.ok) throw new Error((await res.text()) || "Couldn't save that.");
    setPersona(await res.json());
  };

  const handleRefreshTopics = async () => {
    setRefreshingTopics(true);
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) return;
      await fetch(`${API}/api/linkedin/scrape`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      // The scrape runs in background; give it a moment then re-fetch.
      setTimeout(() => void fetchAll(), 2000);
    } finally {
      // Hold the spinner state for the full 2s window so the user sees
      // *something* happen.
      setTimeout(() => setRefreshingTopics(false), 2200);
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

  const skills = linkedin?.raw_profile?.skills ?? [];

  return (
    <div className="settings-main">
      <div className="settings-header">
        <p className="body secondary">
          How I&apos;ll describe you to people I think you should meet.
        </p>
      </div>

      {/* ── Avatar ──────────────────────────────────────────────── */}
      <section className="you-section" style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div
          className="avatar-edit-wrap"
          style={{ borderRadius: "50%" }}
          onClick={() => setAvatarPickerOpen(true)}
          title="Change avatar"
        >
          <img
            src={avatarUrl}
            alt={persona?.name ?? "You"}
            style={{ width: 72, height: 72, borderRadius: "50%", border: "1px solid var(--v2-border-subtle)", display: "block", objectFit: "cover" }}
          />
          <span className="avatar-edit-overlay" style={{ borderRadius: "50%" }}>Edit</span>
        </div>
        <div>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 700, color: "var(--v2-ink)" }}>
            {persona?.name ?? "Your persona"}
          </p>
          <button
            type="button"
            className="text-link"
            style={{ fontSize: 12.5, marginTop: 4 }}
            onClick={() => setAvatarPickerOpen(true)}
          >
            Change avatar
          </button>
          {oauthAvatarUrl && !persona?.profile?.avatar_url && (
            <p style={{ margin: "4px 0 0", fontSize: 11.5, color: "var(--v2-ink-muted)" }}>
              Using your Google photo — change to override
            </p>
          )}
        </div>
      </section>

      {/* ── Profile card ─────────────────────────────────────────── */}
      <section className="you-section">
        <PersonaCardForm
          avatar={{ src: avatarUrl, name: persona?.name ?? "You" }}
          initialName={initialName}
          initialBio={initialBio}
          initialTags={initialTags}
          onSave={handleSave}
          saveLabel="Save"
          showSaved
        />
      </section>

      {/* ── What I've picked up ──────────────────────────────────── */}
      <section className="you-section">
        <h3 className="heading" style={{ marginBottom: 4 }}>
          What I&apos;ve picked up lately
        </h3>
        <p className="body-s" style={{ marginBottom: 16 }}>
          Topics I&apos;ve noticed in your posts and profile.
          {" "}
          <button
            type="button"
            onClick={handleRefreshTopics}
            disabled={refreshingTopics}
            className="text-link"
          >
            {refreshingTopics ? "Looking again…" : "Refresh what I know"}
          </button>
        </p>
        {skills.length > 0 ? (
          <div className="topic-row">
            {skills.slice(0, 16).map((s, i) => (
              <span key={i} className="tag tag-muted">{s}</span>
            ))}
          </div>
        ) : (
          <p className="body-s muted">
            I haven&apos;t read anything yet. Try refresh in a moment.
          </p>
        )}
      </section>

      {/* ── Danger zone ──────────────────────────────────────────── */}
      <section className="you-section you-danger">
        <h3 className="heading" style={{ marginBottom: 8, color: "var(--danger)" }}>
          Delete account
        </h3>
        <p className="body-s" style={{ marginBottom: 14 }}>
          Deleting removes your brief, your matches, your meetings, and your login.
          You can sign back in later with the same account, but you&apos;ll start fresh.
        </p>
        <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
          Delete my account
        </Button>
      </section>

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
