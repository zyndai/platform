"use client";

import Link from "next/link";
import { startLinkedInOAuth, signOutAndLeave } from "@/lib/auth/session";
import { useMyCard } from "@/hooks/useMyCard";
import { useAuth } from "@/hooks/useAuth";

function visitorIdentity(user: { user_metadata?: Record<string, unknown>; email?: string } | null): {
  name: string;
  avatar: string;
} {
  const md = user?.user_metadata ?? {};
  const nameRaw = md.full_name ?? md.name ?? md.preferred_name ?? user?.email?.split("@")[0] ?? "";
  const name = String(nameRaw).trim();
  const avatar = String(md.avatar_url ?? md.picture ?? md.avatar ?? "").trim();
  return { name, avatar };
}

export function AgentCardAuthBar() {
  const { ready, authenticated, handle } = useMyCard();
  const { user } = useAuth();

  function signIn() {
    void startLinkedInOAuth("/", "card");
  }

  function signOut() {
    void signOutAndLeave("/");
  }

  const { name, avatar } = visitorIdentity(user);
  const firstName = name.split(/\s+/)[0] || name;
  const initials = (name || "?")
    .split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "?";

  return (
    <div className="flex items-center gap-2 sm:gap-3">
      {ready && authenticated && handle && (
        <Link
          href={`/p/${encodeURIComponent(handle)}`}
          className="hidden sm:flex items-center gap-2 pl-1 pr-3 py-1 rounded-full border border-white/10 hover:border-[#7b72e9]/50 bg-white/[0.04] transition-colors"
        >
          {avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatar}
              alt=""
              referrerPolicy="no-referrer"
              className="w-6 h-6 rounded-full object-cover"
              onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
            />
          ) : (
            <span className="w-6 h-6 rounded-full bg-[#7b72e9] text-black text-[10px] font-mono font-bold flex items-center justify-center">
              {initials}
            </span>
          )}
          <span className="text-xs font-mono font-medium text-white/80">
            {firstName || "My profile"}
          </span>
        </Link>
      )}
      {ready && authenticated ? (
        <button
          type="button"
          onClick={signOut}
          className="text-xs font-mono font-medium text-white/70 hover:text-white px-2 py-2 cursor-pointer hidden sm:block"
        >
          Sign Out
        </button>
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
      <Link
        className="text-xs font-mono font-bold bg-[#7b72e9] hover:bg-[#a78bfa] text-black px-4 sm:px-5 py-2 sm:py-2.5 rounded-full transition-all hover:shadow-[0_0_20px_rgba(123,114,233,0.35)] active:scale-95 flex items-center gap-1.5 shrink-0"
        href={ready && authenticated && handle ? `/p/${encodeURIComponent(handle)}` : "/create"}
      >
        {ready && authenticated && handle ? "My card" : "Create profile"} <span className="text-sm font-bold leading-none">→</span>
      </Link>
    </div>
  );
}