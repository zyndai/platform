"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";
import { Monogram } from "@/components/ui";
import { patchOnboardingMeta } from "@/lib/onboarding";
import { getSupabase } from "@/lib/supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TICKS = [
  "Reading your recent LinkedIn posts.",
  "Picking up on what you're into these days.",
  "Looking around the network for people in your orbit.",
  "Shortlisting a few worth your time.",
  "Drafting what I'd say to them.",
  "Almost there.",
];

// Sum ≈ 5.1s — inside the brief's 4–6s window. Variable spacing so the
// pacing reads like real work, not a metronome.
const DELAYS_MS = [300, 800, 850, 780, 720, 900];

async function kickOffLinkedInScrape() {
  const sb = getSupabase();
  const {
    data: { session },
  } = await sb.auth.getSession();
  if (!session?.access_token) return;
  // Fire and forget — the scrape can take 30-90s. The result lands in
  // linkedin_profiles long after the user has moved on.
  await fetch(`${API_BASE}/api/linkedin/scrape`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.access_token}` },
  }).catch(() => {});
}

export default function ReadingPage() {
  const router = useRouter();
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    void kickOffLinkedInScrape();

    const timers: ReturnType<typeof setTimeout>[] = [];
    let acc = 0;
    for (let i = 0; i < TICKS.length; i++) {
      acc += DELAYS_MS[i];
      timers.push(setTimeout(() => setVisibleCount(i + 1), acc));
    }
    timers.push(
      setTimeout(() => {
        // Don't await — any backend hiccup must not block the user.
        // The destination's onboarding guard recomputes step on mount.
        void patchOnboardingMeta({ reading_seen: true });
        router.replace("/onboarding/you");
      }, acc + 800),
    );

    return () => timers.forEach(clearTimeout);
    // Effect must run exactly once per real mount. router is stable in
    // Next 15+, and we deliberately don't recompute on context changes —
    // that's what caused the animation to replay before.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="s-reading">
      <Monogram size="md" className="mark" />
      <div className="intro-line">I&apos;m Aria. Give me a minute.</div>
      <ul className="ticks" aria-live="polite">
        {TICKS.map((text, i) => (
          <li
            key={i}
            className={`tick ${i < visibleCount ? "visible" : ""}`}
          >
            <Check size={18} strokeWidth={1.5} />
            <span>{text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
