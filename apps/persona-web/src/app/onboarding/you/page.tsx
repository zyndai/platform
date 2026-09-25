"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import PersonaCardForm from "@/components/settings/PersonaCardForm";
import { useDashboard } from "@/contexts/DashboardContext";
import { getSupabase } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// How long to wait for the fast (profile-only) LinkedIn scrape kicked off
// by the previous onboarding step before giving up and rendering the form
// with whatever's available. PersonaCardForm re-seeds its fields whenever
// initialName/initialBio/initialTags change, so this data must be settled
// BEFORE the form first renders — updating it after the user could already
// be typing would silently overwrite their edits.
const POLL_INTERVAL_MS = 2500;
const POLL_MAX_ATTEMPTS = 10; // ~25s, bounded by the profile actor alone now

const REAL_DATA_KEYS = ["headline", "experience", "education", "skills", "summary"] as const;

function hasRealLinkedinData(rawProfile: Record<string, unknown>): boolean {
  return REAL_DATA_KEYS.some((k) => Boolean(rawProfile[k]));
}

// Skills come back as either plain strings or {name, positions} objects
// depending on actor version — handle both rather than betting on one.
function extractSkills(rawProfile: Record<string, unknown>): string[] {
  const skills = rawProfile.skills;
  if (!Array.isArray(skills)) return [];
  return skills
    .map((s) => (typeof s === "string" ? s : (s as { name?: string })?.name))
    .filter((s): s is string => Boolean(s && s.trim()))
    .slice(0, 8);
}

// Field name for the scraped photo isn't confirmed against this specific
// actor version (unlike headline/summary/skills, which are already read
// elsewhere in this codebase) — try the plausible variants defensively.
// oauthAvatar is preferred over this at the call site regardless.
function extractPhoto(rawProfile: Record<string, unknown>): string | undefined {
  return (
    (rawProfile.photo as string | undefined) ||
    (rawProfile.profilePicture as string | undefined) ||
    (rawProfile.profilePictureUrl as string | undefined) ||
    (rawProfile.avatarUrl as string | undefined) ||
    undefined
  );
}

function extractName(rawProfile: Record<string, unknown>): string | undefined {
  const first = (rawProfile.firstName as string | undefined) || "";
  const last = (rawProfile.lastName as string | undefined) || "";
  const full = `${first} ${last}`.trim();
  return full || undefined;
}

interface Prefill {
  name: string;
  avatar: string | undefined;
  bio: string;
  tags: string[];
  linkedinUrl: string;
}

export default function PersonaSavePage() {
  const router = useRouter();
  const { user, refreshOnboarding } = useDashboard();

  const oauthName = useMemo(() => {
    const meta = user?.user_metadata as Record<string, string> | null;
    return meta?.full_name || meta?.name || user?.email?.split("@")[0] || "";
  }, [user]);

  const oauthAvatar = (user?.user_metadata as Record<string, string> | null)
    ?.avatar_url as string | undefined;

  const [prefillLoaded, setPrefillLoaded] = useState(false);
  const [prefill, setPrefill] = useState<Prefill>({
    name: "",
    avatar: undefined,
    bio: "",
    tags: [],
    linkedinUrl: "",
  });

  // Poll for the fast LinkedIn scrape kicked off by the /onboarding/linkedin
  // step, so the persona card can come in pre-filled with name/photo/bio/
  // skills instead of just the bare OAuth name. Stops immediately (no wait)
  // if the user skipped that step — `present: false` means nothing was ever
  // scraped, so there's nothing to wait for.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      let rawProfile: Record<string, unknown> = {};
      let profileUrl = "";

      for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
        if (cancelled) return;
        try {
          const { data: { session } } = await getSupabase().auth.getSession();
          const jwt = session?.access_token;
          if (!jwt) break;
          const res = await fetch(`${API_BASE}/api/linkedin/me`, {
            headers: { Authorization: `Bearer ${jwt}` },
          });
          if (res.ok) {
            const data = await res.json();
            if (!data?.present) break; // never scraped (step skipped) — stop waiting
            rawProfile = (data.raw_profile || {}) as Record<string, unknown>;
            profileUrl = (data.profile_url as string) || "";
            if (hasRealLinkedinData(rawProfile)) break; // scrape landed
          }
        } catch {
          // best-effort — swallow and retry until the cap
        }
        if (!cancelled && attempt < POLL_MAX_ATTEMPTS - 1) {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
        }
      }

      if (cancelled) return;
      setPrefill({
        name: extractName(rawProfile) || oauthName,
        avatar: oauthAvatar || extractPhoto(rawProfile),
        bio: (rawProfile.summary as string) || (rawProfile.headline as string) || "",
        tags: extractSkills(rawProfile),
        linkedinUrl: profileUrl,
      });
      setPrefillLoaded(true);
    })();

    return () => {
      cancelled = true;
    };
    // Runs once per mount — oauthName/oauthAvatar are derived from `user`,
    // already stable by the time this page renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = async ({
    name,
    bio,
    tags,
    socials,
  }: {
    name: string;
    bio: string;
    tags: string[];
    socials?: { linkedin: string; instagram: string; telegram: string };
  }) => {
    if (!user) return;
    const res = await fetch(`${API_BASE}/api/persona/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: user.id,
        name,
        description: bio || "No bio yet.",
        capabilities: tags.length > 0 ? tags : ["general"],
        price: "Free",
      }),
    });
    if (!res.ok) {
      throw new Error((await res.text()) || "Couldn't save that.");
    }
    // Persona profile stores socials as a free JSONB dict — best-effort, never block
    // onboarding if it fails (the persona itself is already created above).
    if (socials && (socials.linkedin || socials.instagram || socials.telegram)) {
      const profile: Record<string, string> = {};
      if (socials.linkedin) profile.linkedin = socials.linkedin;
      if (socials.instagram) profile.instagram = socials.instagram;
      if (socials.telegram) profile.telegram = socials.telegram;
      try {
        await fetch(`${API_BASE}/api/persona/${user.id}/profile`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile }),
        });
      } catch (e) {
        console.warn("[onboarding] saving social links failed:", e);
      }
    }
    await refreshOnboarding();
    router.replace("/onboarding/brief");
  };

  return (
    <section className="s-persona">
      <h2 className="display-s stage-title" style={{ marginTop: "6vh" }}>
        This is how I&apos;ll describe you.
      </h2>
      <p className="stage-subtitle">
        {prefillLoaded && prefill.bio
          ? "Pulled this from your LinkedIn — add anything I missed."
          : "Here's what I picked up — add anything I missed."}
      </p>
      {!prefillLoaded && (
        <p className="body secondary" style={{ marginTop: 8 }}>
          Reading your LinkedIn…
        </p>
      )}
      {prefillLoaded && (
        <PersonaCardForm
          avatar={{ src: prefill.avatar, name: prefill.name || "You" }}
          initialName={prefill.name}
          initialBio={prefill.bio}
          initialTags={prefill.tags}
          initialSocials={{ linkedin: prefill.linkedinUrl }}
          showSocials
          onSave={handleSave}
          saveLabel="This is me →"
        />
      )}
    </section>
  );
}
