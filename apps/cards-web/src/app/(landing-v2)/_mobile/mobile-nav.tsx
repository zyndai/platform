"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { NAV_LINKS } from "../_sections/copy";
import { useHeroCta } from "../_sections/hero-auth-cta";
import { signInHref } from "@/lib/auth/session";

/** Section ids in the mobile layout are prefixed so they never clash with the (hidden) desktop canvas ids. */
export const mobileHref = (href: string) => `#m-${href.slice(1)}`;

/** Phone/tablet header: logo, primary CTA and a menu button that opens the section links. */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const { ready, authenticated, cta } = useHeroCta();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative z-30 flex items-center justify-between px-4 pt-4 sm:px-8 sm:pt-6">
      <Link href="/" aria-label="Zynd home" className="flex min-h-[44px] items-center text-[30px] font-extrabold tracking-[-0.04em] text-[#262627]">
        ZYND
      </Link>
      <div className="flex items-center gap-2">
        <Link
          href={cta.href}
          className="relative flex h-[44px] items-center justify-center rounded-full px-5 text-[16px] text-[#fff8f8] drop-shadow-[0px_4px_9.5px_rgba(0,0,0,0.45)]"
        >
          <span aria-hidden className="absolute inset-0 rounded-full bg-[#262627]" />
          <span className="relative whitespace-nowrap">{cta.label}</span>
          <span className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
        </Link>
        <button
          type="button"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="landing-v2-m-menu"
          onClick={() => setOpen((o) => !o)}
          className="flex size-[44px] cursor-pointer items-center justify-center rounded-full border-[0.8px] border-solid border-[#b9b9b9] bg-[#f1f1f1]"
        >
          <span className="relative block h-[14px] w-[18px]">
            <span className={`absolute left-0 h-[2px] w-full rounded bg-[#262627] transition-all ${open ? "top-[6px] rotate-45" : "top-0"}`} />
            <span className={`absolute left-0 top-[6px] h-[2px] w-full rounded bg-[#262627] transition-opacity ${open ? "opacity-0" : ""}`} />
            <span className={`absolute left-0 h-[2px] w-full rounded bg-[#262627] transition-all ${open ? "top-[6px] -rotate-45" : "top-[12px]"}`} />
          </span>
        </button>
      </div>
      <nav
        id="landing-v2-m-menu"
        aria-label="Primary"
        hidden={!open}
        className="absolute right-4 top-[68px] w-[min(260px,calc(100%-32px))] rounded-[28px] border-[0.8px] border-solid border-[#b9b9b9] bg-[#f1f1f1] p-2 shadow-[0px_12px_32px_rgba(0,0,0,0.18)] sm:right-8 sm:top-[84px]"
      >
        {NAV_LINKS.map((link) => (
          <a
            key={link.href}
            href={mobileHref(link.href)}
            onClick={() => setOpen(false)}
            className="flex min-h-[48px] items-center rounded-full px-5 text-[17px] tracking-[-0.03em] text-black active:bg-black/5"
          >
            {link.label}
          </a>
        ))}
        {ready && !authenticated && (
          <a href={signInHref("/")} className="flex min-h-[48px] items-center rounded-full px-5 text-[17px] tracking-[-0.03em] text-black active:bg-black/5">
            Sign in
          </a>
        )}
      </nav>
    </div>
  );
}
