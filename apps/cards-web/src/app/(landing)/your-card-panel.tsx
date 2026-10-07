"use client";

import Link from "next/link";
import { useState } from "react";
import { useMyCard } from "@/hooks/useMyCard";
import { updateCard, type AgentProfileCard } from "@/lib/cards";
import { createClient } from "@/lib/supabase/client";
import { imgProxyUrl } from "@/lib/avatar";
import { HeroCardStack } from "./hero-card-stack";

/**
 * The hero's right column for signed-in visitors: their actual card, styled
 * to match this page, instead of the marketing card stack. Data comes from
 * the SSR-seeded MyCardProvider so it paints on first render — no waiting
 * for a client-side session + /cards/mine round-trip after hydration.
 */

function isBlank(s: string | null | undefined): boolean {
  return !s || !s.trim() || /^(n\/a|not specified|unknown|none)$/i.test(s.trim());
}

const LEVEL_LABEL: Record<string, string> = {
  expert: "EXPERT", advanced: "ADVANCED", intermediate: "MID", beginner: "BEGINNER",
};

function initialsOf(name: string): string {
  return name.split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "?";
}

function IdentityBlock({ card, handle }: { card: AgentProfileCard; handle: string }) {
  const identity = card.identity ?? {};
  const name = identity.name?.trim() || "Your profile";
  const avatarRaw = /^https?:\/\//.test(identity.avatar_url || "") ? identity.avatar_url : null;
  const avatar = imgProxyUrl(avatarRaw, null, handle);

  return (
    <div className="flex items-start gap-4">
      {avatar ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={avatar}
          alt={name}
          className="w-16 h-16 rounded-2xl object-cover border border-white/15 shrink-0"
          onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
        />
      ) : (
        <span className="w-16 h-16 rounded-2xl bg-[#7b72e9] text-black font-mono font-bold flex items-center justify-center text-xl shrink-0">
          {initialsOf(name)}
        </span>
      )}
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="font-display uppercase text-xl text-white leading-tight truncate">{name}</div>
        {!isBlank(identity.headline) && (
          <div className="text-xs text-[#a0a09a] mt-1 leading-snug">{identity.headline}</div>
        )}
        {!isBlank(identity.location) && (
          <div className="text-[10px] font-mono text-[#7b72e9] mt-1.5">{identity.location}</div>
        )}
      </div>
    </div>
  );
}

function PublishedPanel({ card, handle }: { card: AgentProfileCard; handle: string }) {
  const skills = (card.skills ?? []).slice(0, 6);

  return (
    <div className="rounded-3xl bg-[#0e1010] border border-[#7b72e9]/30 p-6 sm:p-7 space-y-5 shadow-[0_0_40px_rgba(123,114,233,0.12)]">
      <div className="flex items-center justify-between">
        <div className="inline-flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-[#7b72e9] bg-[#7b72e9]/10 border border-[#7b72e9]/25 px-3 py-1 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9] animate-pulse" />
          Your living profile
        </div>
        <span className="text-[10px] font-mono text-[#7d7d77]">LIVE</span>
      </div>

      <IdentityBlock card={card} handle={handle} />

      {skills.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {skills.map((s) => (
            <span key={s.name} className="text-[10px] font-mono text-[#d7d7d1] bg-black/50 border border-white/10 rounded-full px-2.5 py-1 flex items-center gap-1.5">
              {s.name}
              {s.level && s.level !== "intermediate" && (
                <span className="text-[#7b72e9]">{LEVEL_LABEL[s.level] ?? ""}</span>
              )}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-[10px] font-mono text-[#7d7d77] border-t border-white/[0.08] pt-4">
        <span className="truncate">cards.zynd.ai/p/{handle}</span>
        <span className="text-emerald-400 flex items-center gap-1.5 shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> discoverable
        </span>
      </div>

      <div className="flex flex-col sm:flex-row gap-2.5">
        <Link
          href={`/p/${encodeURIComponent(handle)}`}
          className="flex-1 bg-[#7b72e9] hover:bg-[#a78bfa] text-black font-mono font-bold text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2 active:scale-95 shadow-[0_0_24px_rgba(123,114,233,0.3)]"
        >
          View my profile <span className="text-base leading-none">→</span>
        </Link>
        <Link
          href={`/p/${encodeURIComponent(handle)}/edit`}
          className="flex-1 bg-white/[0.05] hover:bg-white/[0.09] text-white border border-white/15 font-mono text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2"
        >
          Edit card
        </Link>
      </div>
    </div>
  );
}

function PendingPanel({ card, handle }: { card: AgentProfileCard; handle: string }) {
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { refresh } = useMyCard();

  async function publish() {
    setPublishing(true);
    setError(null);
    try {
      const { data: { session } } = await createClient().auth.getSession();
      const token = session?.access_token;
      if (!token) throw new Error("not signed in");
      const result = await updateCard(handle, { ...card, status: "published" }, token);
      if (!result) throw new Error("publish refused");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not publish");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="rounded-3xl bg-[#0e1010] border border-amber-400/30 p-6 sm:p-7 space-y-5 shadow-[0_0_40px_rgba(251,191,36,0.08)]">
      <div className="flex items-center justify-between">
        <div className="inline-flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-amber-400 bg-amber-400/10 border border-amber-400/25 px-3 py-1 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          Your profile awaits review
        </div>
        <span className="text-[10px] font-mono text-[#7d7d77]">DRAFT</span>
      </div>

      <IdentityBlock card={card} handle={handle} />

      <p className="text-xs font-mono text-[#a0a09a] leading-relaxed">
        This card exists but is not published yet — it was left in review by an
        earlier version of the flow. Publish it to go live, or edit it first.
      </p>

      <div className="flex items-center justify-between text-[10px] font-mono text-[#7d7d77] border-t border-white/[0.08] pt-4">
        <span className="truncate">cards.zynd.ai/p/{handle}</span>
        <span className="text-amber-400 flex items-center gap-1.5 shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> not public yet
        </span>
      </div>

      {error && <p className="text-[11px] font-mono text-red-400">{error}</p>}

      <div className="flex flex-col sm:flex-row gap-2.5">
        <button
          type="button"
          onClick={publish}
          disabled={publishing}
          className="flex-1 bg-amber-400 hover:bg-amber-300 disabled:opacity-50 disabled:cursor-not-allowed text-black font-mono font-bold text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2 active:scale-95"
        >
          {publishing ? "Publishing…" : "Publish my card"} <span className="text-base leading-none">→</span>
        </button>
        <Link
          href={`/p/${encodeURIComponent(handle)}/edit`}
          className="flex-1 bg-white/[0.05] hover:bg-white/[0.09] text-white border border-white/15 font-mono text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2"
        >
          Edit first
        </Link>
      </div>
    </div>
  );
}

export function YourCardPanel() {
  const { ready, authenticated, handle, card } = useMyCard();

  if (!ready || !authenticated) return <HeroCardStack />;

  if (!handle || !card) {
    return (
      <div className="rounded-3xl bg-[#0e1010] border border-white/10 p-7 sm:p-8 space-y-5">
        <div className="inline-flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest text-[#7b72e9] bg-[#7b72e9]/10 border border-[#7b72e9]/25 px-3 py-1 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9]" />
          Signed in
        </div>
        <h3 className="font-display uppercase text-2xl text-white leading-tight">
          You don&apos;t have a living profile yet.
        </h3>
        <p className="text-xs font-mono text-[#a0a09a] leading-relaxed">
          Paste your GitHub, LinkedIn or X — we scrape the public web and draft your card in about a minute.
        </p>
        <Link
          href="/create"
          className="w-full bg-[#7b72e9] hover:bg-[#a78bfa] text-black font-mono font-bold text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2 active:scale-95"
        >
          Create your Living Profile <span className="text-base leading-none">→</span>
        </Link>
      </div>
    );
  }

  if (card.status && card.status !== "published") {
    return <PendingPanel card={card} handle={handle} />;
  }

  return <PublishedPanel card={card} handle={handle} />;
}