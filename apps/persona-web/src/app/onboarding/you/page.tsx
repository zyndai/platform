"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import PersonaCardForm from "@/components/settings/PersonaCardForm";
import { useDashboard } from "@/contexts/DashboardContext";

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
        LinkedIn was a little quiet. Fill this in yourself and I&apos;ll learn from your brief.
      </p>
      <PersonaCardForm
        avatar={{ src: avatarUrl, name: defaultName || "You" }}
        initialName={defaultName}
        initialBio=""
        initialTags={[]}
        showSocials
        onSave={handleSave}
        saveLabel="This is me →"
      />
    </section>
  );
}
