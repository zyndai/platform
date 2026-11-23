"use client";
/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { HERO } from "./copy";

// Same hand-off as the current landing page: /create owns auth, validation
// and job polling, and seeds the pasted link as the first source chip.
export function HeroUrlForm({ layout = "canvas" }: { layout?: "canvas" | "flow" }) {
  const router = useRouter();
  const [link, setLink] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = link.trim();
    router.push(trimmed ? `/create?url=${encodeURIComponent(trimmed)}` : "/create");
  }

  if (layout === "flow") {
    return (
      <form onSubmit={onSubmit} className="relative mx-auto flex h-[64px] w-full max-w-[576px] items-center gap-2 rounded-full border-[0.4px] border-solid border-[#dbd9d9] bg-white p-[7px] pl-[18px] sm:pl-[10px] shadow-[0px_4px_18px_0px_rgba(0,0,0,0.12)]">
        <span className="relative hidden size-[44px] shrink-0 sm:block">
          <img alt="" className="absolute block inset-0 size-full max-w-none" src="/assets/landing-v2/ellipse-14345-658e4002ca.svg" />
          <img alt="" className="absolute left-1/2 top-1/2 size-[22px] -translate-x-1/2 -translate-y-1/2 max-w-none" src="/assets/landing-v2/group-1-080abbb838.svg" />
        </span>
        <label htmlFor="landing-v2-m-url" className="sr-only">
          {HERO.urlLabel}
        </label>
        <input
          id="landing-v2-m-url"
          type="url"
          inputMode="url"
          autoComplete="url"
          value={link}
          onChange={(event) => setLink(event.target.value)}
          placeholder={HERO.urlPlaceholder}
          className="h-full min-w-0 flex-1 bg-transparent text-[15px] font-semibold tracking-[-0.03em] sm:text-[16px] text-[#262627] outline-none placeholder:text-[#b4b4b4]"
        />
        <button type="submit" aria-label="Build my profile" className="relative size-[50px] shrink-0 cursor-pointer rounded-full">
          <img alt="" className="absolute block inset-0 size-full max-w-none" src="/assets/landing-v2/ellipse-14344-c0987c0400.svg" />
          <img alt="" className="absolute left-1/2 top-1/2 size-[24px] -translate-x-1/2 -translate-y-1/2 -rotate-90 max-w-none" src="/assets/landing-v2/akar-icons-arrow-down-5590a16169.svg" />
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={onSubmit} className="absolute h-[71px] left-[417px] top-[474px] w-[576px]">
      <div className="absolute bg-white border-[#dbd9d9] border-[0.4px] border-solid inset-0 rounded-[142px]" />
      <div className="absolute left-[11px] size-[50px] top-[11px]">
        <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/ellipse-14345-658e4002ca.svg" />
      </div>
      <div className="absolute left-[24px] overflow-clip size-[24px] top-[24px]">
        <div className="absolute inset-[12.5%]">
          <div className="absolute inset-[-5.56%]">
            <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-1-080abbb838.svg" />
          </div>
        </div>
      </div>
      <label htmlFor="landing-v2-url" className="sr-only">
        {HERO.urlLabel}
      </label>
      <input
        id="landing-v2-url"
        type="url"
        inputMode="url"
        autoComplete="url"
        value={link}
        onChange={(event) => setLink(event.target.value)}
        placeholder={HERO.urlPlaceholder}
        className="absolute h-full left-[92px] w-[417px] bg-transparent font-semibold text-[16px] tracking-[-0.64px] text-[#262627] placeholder:text-[#b4b4b4] outline-none"
      />
      <button type="submit" aria-label="Build my profile" className="absolute left-[517px] size-[50px] top-[11px] cursor-pointer rounded-full">
        <span className="absolute inset-[0_-8%_-16%_-8%]">
          <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/ellipse-14344-c0987c0400.svg" />
        </span>
        <span className="absolute flex items-center justify-center left-[13px] size-[24px] top-[13px]">
          <span className="-rotate-90 flex-none">
            <span className="block relative size-[24px]">
              <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/akar-icons-arrow-down-5590a16169.svg" />
            </span>
          </span>
        </span>
      </button>
    </form>
  );
}
