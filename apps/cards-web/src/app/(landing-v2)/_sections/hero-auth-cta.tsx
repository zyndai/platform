"use client";

import Link from "next/link";

import { useMyCard } from "@/hooks/useMyCard";
import { signInHref } from "@/lib/auth/session";

// Mirrors the current landing page's hero CTAs: visitors create a card,
// signed-in owners go to their card (or finish publishing it).
function primaryCta(authenticated: boolean, handle: string | null, published: boolean): { label: string; href: string } {
  if (!authenticated || !handle) return { label: "Get Started", href: "/create" };
  const path = `/p/${encodeURIComponent(handle)}`;
  return published ? { label: "My card", href: path } : { label: "Finish card", href: `${path}/edit` };
}

export function useHeroCta() {
  const { ready, authenticated, handle, card } = useMyCard();
  const cta = primaryCta(ready && authenticated, handle, card?.status === "published");
  return { ready, authenticated, cta };
}

export function HeroAuthCta() {
  const { ready, authenticated, cta } = useHeroCta();

  return (
    <>
      {ready && !authenticated && (
        <a
          href={signInHref("/")}
          className="-translate-x-1/2 absolute font-normal leading-[1.178] left-[1086px] text-[16px] text-black text-center top-[55px] tracking-[-0.8px] whitespace-nowrap hover:opacity-60 transition-opacity"
        >
          Sign in
        </a>
      )}
      <Link href={cta.href} className="absolute content-stretch drop-shadow-[0px_4px_9.5px_rgba(0,0,0,0.61)] flex h-[62px] items-center justify-center left-[1153px] p-[10px] rounded-[53px] top-[35px] w-[190px]">
        <span aria-hidden className="absolute bg-[#262627] inset-0 pointer-events-none rounded-[53px]" />
        <span className="[word-break:break-word] font-normal leading-[normal] not-italic relative shrink-0 text-[#fff8f8] text-[21px] text-center whitespace-nowrap">
          {cta.label}
        </span>
        <span className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
      </Link>
    </>
  );
}
