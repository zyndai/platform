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
//
// Parses the URL properly rather than matching a single regex against the
// whole string — LinkedIn's own /in/me redirect (and most copy-pasted
// profile links) land with tracking query params attached (?trk=...,
// ?originalSubdomain=...), which a regex anchored right after the slug
// rejects outright. Mirrors the backend's _normalize_linkedin_url.
function normalizeLinkedInUrl(raw: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(raw.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  const host = parsed.hostname.toLowerCase();
  if (host !== "linkedin.com" && !host.endsWith(".linkedin.com")) return null;
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length !== 2 || parts[0].toLowerCase() !== "in" || !parts[1]) return null;
  return `https://www.linkedin.com/in/${parts[1]}`;
}

// Lucide dropped brand glyphs in v0.452 (trademark concerns), so the
// LinkedIn mark is inlined here — same path used on the Accounts page.
function LinkedinIcon({ size = 18 }: { size?: number }) {
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
    if (jwt && profileUrl) {
      // fast=true: profile actor only (no posts) — the "you" step polls
      // for this and needs it back quickly. Posts get backfilled later,
      // once matches/brief actually need them (see trigger_scrape).
      const params = `?profile_url=${encodeURIComponent(profileUrl)}&fast=true`;
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
    let normalized: string | undefined;
    if (trimmed) {
      normalized = normalizeLinkedInUrl(trimmed) || undefined;
      if (!normalized) {
        setError(
          "That doesn't look like a LinkedIn profile URL — expected something like https://www.linkedin.com/in/your-name.",
        );
        return;
      }
    }
    setError("");
    setWorking("continue");
    await finish(normalized);
  };

  const skip = async () => {
    setWorking("skip");
    await finish();
  };

  return (
    <section className="s-linkedin">
      <h2 className="stage-title">Got a LinkedIn?</h2>
      <p className="stage-subtitle">
        Paste your profile link and I&apos;ll pull in your experience, photo, and skills — so
        you don&apos;t have to fill it all in by hand.
      </p>

      <Card className="li-card">
        <Button
          variant="secondary"
          fullWidth
          onClick={openMyProfile}
          leftIcon={<LinkedinIcon />}
        >
          Open my LinkedIn profile ↗
        </Button>

        <div className="li-connector">
          <span />
          then paste the link below
          <span />
        </div>

        <FieldLabel htmlFor="li-url">Your LinkedIn profile link</FieldLabel>
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
        {error && <p className="li-error">{error}</p>}

        <Button fullWidth onClick={continueClick} disabled={working !== null} style={{ marginTop: 18 }}>
          {working === "continue" ? "One sec…" : "Continue →"}
        </Button>

        <div className="trust">
          <Shield />
          <span>We only read your public profile — nothing gets posted on your behalf.</span>
        </div>
      </Card>

      <Button variant="tertiary" onClick={skip} disabled={working !== null}>
        {working === "skip" ? "One sec…" : "Skip for now"}
      </Button>
    </section>
  );
}
