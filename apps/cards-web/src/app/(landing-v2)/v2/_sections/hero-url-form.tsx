"use client";
/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

// Same hand-off as the current landing page: /create owns auth, validation
// and job polling, and seeds the pasted link as the first source chip.
export function HeroUrlForm() {
  const router = useRouter();
  const [link, setLink] = useState("");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = link.trim();
    router.push(trimmed ? `/create?url=${encodeURIComponent(trimmed)}` : "/create");
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
        Your GitHub or LinkedIn URL
      </label>
      <input
        id="landing-v2-url"
        type="url"
        inputMode="url"
        autoComplete="url"
        value={link}
        onChange={(event) => setLink(event.target.value)}
        placeholder="Paste your Github or Linkedin URL"
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
