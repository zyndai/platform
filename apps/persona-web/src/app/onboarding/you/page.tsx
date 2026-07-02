"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import PersonaCardForm from "@/components/settings/PersonaCardForm";
import { useDashboard } from "@/contexts/DashboardContext";
import { getSupabase } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function PersonaSavePage() {
  const router = useRouter();
  const { user, refreshOnboarding } = useDashboard();

  const defaultName = useMemo(() => {
    const meta = user?.user_metadata as Record<string, string> | null;
    return (
      meta?.full_name ||
      meta?.name ||
      user?.email?.split("@")[0] ||
      ""
    );
  }, [user]);

  const avatarUrl = (user?.user_metadata as Record<string, string> | null)
    ?.avatar_url as string | undefined;

  // Pre-fill the LinkedIn field from the scrape that ran on the previous
  // (reading) step, so a user who signed in with LinkedIn isn't asked for it
  // again. Best-effort; the form still renders if the lookup fails or is empty.
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [prefillLoaded, setPrefillLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data: { session } } = await getSupabase().auth.getSession();
        const jwt = session?.access_token;
        if (jwt) {
          const res = await fetch(`${API_BASE}/api/linkedin/me`, {
            headers: { Authorization: `Bearer ${jwt}` },
          });
          if (res.ok) {
            const data = await res.json();
            if (!cancelled && data?.present && data?.profile_url) {
              setLinkedinUrl(String(data.profile_url));
            }
          }
        }
      } catch {
        // best-effort prefill — never block onboarding
      } finally {
        if (!cancelled) setPrefillLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
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
        Here&apos;s what I picked up — add anything I missed.
      </p>
      {prefillLoaded && (
        <PersonaCardForm
          avatar={{ src: avatarUrl, name: defaultName || "You" }}
          initialName={defaultName}
          initialBio=""
          initialTags={[]}
          initialSocials={{ linkedin: linkedinUrl }}
          showSocials
          onSave={handleSave}
          saveLabel="This is me →"
        />
      )}
    </section>
  );
}
