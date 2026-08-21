"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shield } from "lucide-react";
import { Button, Card, Input, FieldLabel } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { patchOnboardingMeta } from "@/lib/onboarding";
import { useDashboard } from "@/contexts/DashboardContext";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// LinkedIn's OAuth login only hands us a name — no profile URL, which needs
// partner-tier API access we don't have. Asking for it here, once, replaces
// the fragile "guess by name" scrape fallback with the pasted URL.
const PROFILE_RE = /^https?:\/\/([\w-]+\.)?linkedin\.com\/in\/[\w-]+\/?$/i;

// Lucide dropped brand glyphs in v0.452 (trademark concerns), so the
// LinkedIn mark is inlined here — same path used on the Accounts page.
function LinkedinIcon({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zm1.78 13.02H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

export default function LinkedInStep() {
  const router = useRouter();
  const { refreshOnboarding } = useDashboard();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState<"continue" | "skip" | null>(null);

  const openMyProfile = () => {
    window.open("https://www.linkedin.com/in/me", "_blank", "noopener,noreferrer");
  };

  const finish = async (profileUrl?: string) => {
    const sb = getSupabase();
    const {
      data: { session },
    } = await sb.auth.getSession();
    const jwt = session?.access_token;
    if (jwt) {
      const params = profileUrl ? `?profile_url=${encodeURIComponent(profileUrl)}` : "";
      // Fire and forget, same as the reading step's scrape kick-off — the
      // result lands in linkedin_profiles long after the user has moved on.
      await fetch(`${API_BASE}/api/linkedin/scrape${params}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${jwt}` },
      }).catch(() => {});
    }
    await patchOnboardingMeta({ linkedin_step_seen: true });
    await refreshOnboarding();
    router.replace("/onboarding/reading");
  };

  const continueClick = async () => {
    const trimmed = url.trim();
    if (trimmed && !PROFILE_RE.test(trimmed)) {
      setError(
        "That doesn't look like a LinkedIn profile URL — expected something like https://www.linkedin.com/in/your-name.",
      );
      return;
    }
    setError("");
    setWorking("continue");
    await finish(trimmed || undefined);
  };

  const skip = async () => {
    setWorking("skip");
    await finish();
  };

  return (
    <section className="s-linkedin">
      <Card className="li-card">
        <div className="li-icon">
          <LinkedinIcon size={28} />
        </div>
        <h2 className="display-s" style={{ marginBottom: 12 }}>
          Got a LinkedIn? Let&apos;s pull in your profile.
        </h2>
        <p className="body secondary" style={{ marginBottom: 20 }}>
          Paste your profile link and I&apos;ll read your experience, so you don&apos;t have to
          type it all out.
        </p>
        <Button variant="secondary" fullWidth onClick={openMyProfile} style={{ marginBottom: 14 }}>
          Open my LinkedIn profile ↗
        </Button>
        <FieldLabel htmlFor="li-url">Then copy the link from your address bar and paste it here</FieldLabel>
        <Input
          id="li-url"
          placeholder="https://www.linkedin.com/in/your-name"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setError("");
          }}
          disabled={working !== null}
        />
        {error && (
          <p className="body" style={{ color: "var(--danger)", fontSize: 13, marginTop: 8 }}>
            {error}
          </p>
        )}
        <Button fullWidth onClick={continueClick} disabled={working !== null} style={{ marginTop: 16 }}>
          {working === "continue" ? "One sec…" : "Continue"}
        </Button>
        <div className="trust">
          <Shield />
          <span>We only read your public profile — nothing gets posted on your behalf.</span>
        </div>
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <Button variant="tertiary" onClick={skip} disabled={working !== null}>
            {working === "skip" ? "One sec…" : "Skip for now"}
          </Button>
        </div>
      </Card>
    </section>
  );
}
