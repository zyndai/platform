"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { startLinkedInOAuth, signOutAndLeave } from "@/lib/auth/session";
import { useMyCard } from "@/hooks/useMyCard";
import { useAuth } from "@/hooks/useAuth";
import { displayUserName, initialsOf, pickUserAvatar } from "@/lib/identity";
import { imgProxyUrl } from "@/lib/avatar";

/**
 * Signed-in state: an identity pill (photo/initials + name) that opens a
 * dropdown with the account actions. The pill shows whenever someone is
 * signed in — with or without a card — so the visitor always sees who they
 * are. The photo prefers the LinkedIn profile picture when the account
 * signed in through LinkedIn (Google's default initial image would otherwise
 * win), with a second URL and initials as fallbacks. The name truncates with
 * an ellipsis past a sane width instead of squeezing the pill.
 */
function AccountPill({ name, avatar, hasCard, published, handle }: {
  name: string;
  avatar: { primary: string; secondary: string | null };
  hasCard: boolean;
  published: boolean;
  handle: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [imgFailed, setImgFailed] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const initials = initialsOf(name);

  // First-party proxy: LinkedIn/Google CDNs get blocked third-party in some
  // browsers/extensions; /api/img fetches server-side and tries `secondary`
  // itself when the primary fails.
  const avatarSrc = imgProxyUrl(avatar.primary, avatar.secondary);

  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const menuItem =
    "w-full text-left px-4 py-2.5 text-xs font-mono text-white/85 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors flex items-center gap-2.5";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 pl-1.5 pr-3 py-1.5 rounded-full border border-white/12 hover:border-[#7b72e9]/60 bg-white/[0.05] hover:bg-white/[0.08] transition-colors cursor-pointer min-w-0 max-w-[240px] sm:max-w-[280px]"
      >
        {avatarSrc && !imgFailed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={avatarSrc}
            alt=""
            className="w-7 h-7 rounded-full object-cover shrink-0"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <span className="w-7 h-7 rounded-full bg-[#7b72e9] text-black text-[11px] font-mono font-bold flex items-center justify-center shrink-0">
            {initials}
          </span>
        )}
        <span className="text-xs font-mono font-medium text-white/90 truncate min-w-0">
          {name || "Signed in"}
        </span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M1 3l4 4 4-4" stroke="#a0a09a" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+8px)] w-56 rounded-2xl bg-[#121413] border border-white/12 shadow-[0_16px_48px_rgba(0,0,0,0.6)] p-1.5 z-50"
        >
          <div className="px-4 pt-2.5 pb-1.5 mb-1 border-b border-white/[0.07]">
            <div className="text-[10px] font-mono uppercase tracking-widest text-[#7d7d77]">Signed in as</div>
            <div className="text-xs font-mono text-white mt-1 truncate">{name}</div>
          </div>
          {hasCard && handle ? (
            published ? (
              <Link href={`/p/${encodeURIComponent(handle)}`} className={menuItem} onClick={() => setOpen(false)}>
                <span className="text-[#7b72e9]">▣</span> My card
              </Link>
            ) : (
              <Link href={`/p/${encodeURIComponent(handle)}/edit`} className={menuItem} onClick={() => setOpen(false)}>
                <span className="text-amber-400">✎</span> Finish my card
              </Link>
            )
          ) : (
            <Link href="/create" className={menuItem} onClick={() => setOpen(false)}>
              <span className="text-[#7b72e9]">＋</span> Create your card
            </Link>
          )}
          {hasCard && handle && published && (
            <Link href={`/p/${encodeURIComponent(handle)}/edit`} className={menuItem} onClick={() => setOpen(false)}>
              <span className="text-[#7b72e9]">✎</span> Edit my card
            </Link>
          )}
          <button type="button" className={menuItem} onClick={() => { setOpen(false); signOutAndLeave("/"); }}>
            <span className="text-[#7d7d77]">↪</span> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AgentCardAuthBar() {
  const { ready, authenticated, handle, card } = useMyCard();
  const { user } = useAuth();

  function signIn() {
    void startLinkedInOAuth("/", "card");
  }

  const md = (user?.user_metadata ?? {}) as Record<string, unknown>;
  const authName = displayUserName(md, user?.email);
  // The living profile IS the visitor's identity: prefer its name over the
  // auth account's (Google signups often carry a gamertag here).
  const cardName = (card?.identity?.name ?? "").trim();
  const name = cardName || authName;
  const avatar = pickUserAvatar(md);

  const hasCard = Boolean(handle);
  const published = card?.status === "published";

  return (
    <div className="flex items-center gap-2 sm:gap-3">
      {ready && authenticated ? (
        <AccountPill key={user?.id ?? "user"} name={name} avatar={avatar} hasCard={hasCard} published={published} handle={handle} />
      ) : ready ? (
        <button
          type="button"
          onClick={signIn}
          className="text-[11px] font-mono font-medium text-white/70 hover:text-white px-2 py-2 cursor-pointer max-w-[9.5rem] sm:max-w-none leading-tight text-right"
        >
          Already have a profile? Sign in
        </button>
      ) : (
        <span className="w-[7.5rem] hidden sm:block" aria-hidden />
      )}
      {ready && !authenticated && (
        <Link
          className="text-xs font-mono font-bold bg-[#7b72e9] hover:bg-[#a78bfa] text-black px-4 sm:px-5 py-2 sm:py-2.5 rounded-full transition-all hover:shadow-[0_0_20px_rgba(123,114,233,0.35)] active:scale-95 flex items-center gap-1.5 shrink-0"
          href="/create"
        >
          Create profile <span className="text-sm font-bold leading-none">→</span>
        </Link>
      )}
    </div>
  );
}