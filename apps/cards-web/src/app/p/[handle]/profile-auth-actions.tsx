"use client";

import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";
import { getMyCard, updateCard, type AgentProfileCard } from "@/lib/cards";

export function ProfileSignIn({ handle }: { handle: string }) {
  function signIn(provider: "google" | "github") {
    setAuthNext(`/p/${encodeURIComponent(handle)}`, "card");
    createClient().auth.signInWithOAuth({
      provider,
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  }

  return (
    <button
      type="button"
      onClick={() => signIn("google")}
      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full font-mono text-[12px]! font-semibold cursor-pointer hover:opacity-90 transition-opacity"
      style={{ background: "#7B72E9", color: "#fff", border: "none" }}
    >
      Sign In
    </button>
  );
}

export function ClaimIfCreator({ handle, card }: { handle: string; card: AgentProfileCard }) {
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    let cancelled = false;

    async function claim() {
      try {
        const stored: string[] = JSON.parse(localStorage.getItem("zynd_my_handles") || "[]");
        if (!stored.includes(handle)) return;
        const { data: { session } } = await createClient().auth.getSession();
        const token = session?.access_token;
        if (!token) return;
        const mine = await getMyCard(token);
        if (mine?.handle) return;
        if (cancelled) return;
        await updateCard(handle, card, token);
      } catch (err) {
        console.error("[ClaimIfCreator] failed:", err);
      }
    }

    claim();
    return () => { cancelled = true; };
  }, [handle, card]);

  return null;
}
