"use client";

import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { useMyCard } from "@/hooks/useMyCard";

const CALLBACK = () => `${window.location.origin}/auth/callback`;

export function AgentCardAuthBar() {
  const { ready, authenticated, handle } = useMyCard();

  function signIn() {
    setAuthNext("/agent-card", "card");
    createClient().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: CALLBACK() },
    });
  }

  async function signOut() {
    const { error } = await createClient().auth.signOut();
    if (error) console.error("Sign out failed:", error);
    window.location.href = "/agent-card";
  }

  return (
    <div className="flex items-center gap-2 sm:gap-3">
      {ready && authenticated && handle && (
        <Link
          href={`/p/${encodeURIComponent(handle)}`}
          className="text-xs font-mono font-medium text-white/80 hover:text-white px-2 py-2 hidden sm:block"
        >
          My profile
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
        href="/create"
      >
        Create profile <span className="text-sm font-bold leading-none">→</span>
      </Link>
    </div>
  );
}
