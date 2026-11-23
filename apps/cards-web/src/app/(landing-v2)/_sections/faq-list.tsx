"use client";
/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */

import Link from "next/link";
import { useState } from "react";

import { FAQS, FAQ_SUPPORT } from "./copy";

export function FaqList({ layout = "canvas" }: { layout?: "canvas" | "flow" }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  if (layout === "flow") {
    return (
      <div className="mx-auto flex w-full max-w-[710px] flex-col items-center">
        <ul className="flex w-full flex-col gap-3">
          {FAQS.map((faq, i) => {
            const open = openIndex === i;
            const panelId = `landing-v2-m-faq-${i}`;
            return (
              <li key={faq.question} className="rounded-[20px] bg-white shadow-[0px_4px_11px_0px_rgba(0,0,0,0.06)]">
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={panelId}
                  onClick={() => setOpenIndex(open ? null : i)}
                  className="flex min-h-[64px] w-full cursor-pointer items-center gap-3 px-4 py-3 text-left"
                >
                  <img alt="" className="size-[34px] shrink-0" src="/assets/landing-v2/group-1597880900-f46646d1ca.svg" />
                  <span className="flex-1 text-[17px] font-medium leading-[1.25] tracking-[-0.03em] text-[#262627]">{faq.question}</span>
                  <span className={`relative size-[32px] shrink-0 overflow-clip transition-transform duration-200 ${open ? "rotate-180" : ""}`}>
                    <span className="absolute inset-[43.96%_25.83%_35.33%_25.87%]">
                      <span className="absolute inset-[-11.32%_-4.86%_-11.32%_-4.85%]">
                        <img alt="" className="block size-full max-w-none" src="/assets/landing-v2/group-6ab1f4deda.svg" />
                      </span>
                    </span>
                  </span>
                </button>
                <div id={panelId} role="region" hidden={!open} className="px-4 pb-5 pl-[62px] text-[16px] leading-[1.5] text-[#575757]">
                  {faq.answer}
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-10 text-center text-[22px] font-medium leading-[1.1] tracking-[-0.04em] text-[#262627]">{FAQ_SUPPORT.title}</p>
        <p className="mt-2 text-center text-[16px] text-[#575757]">{FAQ_SUPPORT.body}</p>
        <Link href="/support" className="relative mt-5 flex h-[56px] w-[240px] items-center justify-center rounded-[35px] drop-shadow-[0px_4px_4px_rgba(0,0,0,0.38)]">
          <span aria-hidden className="absolute inset-0 rounded-[35px] bg-[#262627]" />
          <span className="relative text-[17px] font-semibold tracking-[-0.04em] text-white">{FAQ_SUPPORT.cta}</span>
          <span className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
        </Link>
      </div>
    );
  }

  return (
    <div className="absolute flex flex-col items-center left-[326px] top-[251px] w-[710px]">
      <ul className="flex flex-col gap-[22px] w-full">
        {FAQS.map((faq, i) => {
          const open = openIndex === i;
          const panelId = `landing-v2-faq-${i}`;
          return (
            <li key={faq.question} className="bg-white rounded-[24px] shadow-[0px_4px_11px_0px_rgba(0,0,0,0.06)]">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={panelId}
                onClick={() => setOpenIndex(open ? null : i)}
                className="block cursor-pointer h-[74px] relative text-left w-full"
              >
                <span className="absolute left-[27px] size-[38px] top-[18px]">
                  <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/group-1597880900-f46646d1ca.svg" />
                </span>
                <span className="[word-break:break-word] absolute font-medium leading-[1.028] left-[96px] text-[#262627] text-[18px] top-[26px] tracking-[-0.9px] whitespace-nowrap">
                  {faq.question}
                </span>
                <span className={`absolute left-[646px] overflow-clip size-[32px] top-[20px] transition-transform duration-200 ${open ? "rotate-180" : ""}`}>
                  <span className="absolute inset-[43.96%_25.83%_35.33%_25.87%]">
                    <span className="absolute inset-[-11.32%_-4.86%_-11.32%_-4.85%]">
                      <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/group-6ab1f4deda.svg" />
                    </span>
                  </span>
                </span>
              </button>
              <div id={panelId} role="region" hidden={!open} className="pb-[24px] pl-[96px] pr-[64px] text-[#575757] text-[15px] leading-[1.45] tracking-[-0.3px]">
                {faq.answer}
              </div>
            </li>
          );
        })}
      </ul>
      {/* Spacing reproduces the design's absolute tops (784 / 815 / 847) below a fully collapsed list ending at 709. */}
      <p className="[word-break:break-word] font-medium leading-[1.028] ml-[9px] mt-[75px] text-[#262627] text-[20px] text-center tracking-[-1px] w-[176px]">
        {FAQ_SUPPORT.title}
      </p>
      <p className="[word-break:break-word] font-medium leading-[1.028] ml-[9px] mt-[10.44px] text-[#575757] text-[14px] text-center tracking-[-0.7px] w-[319px]">
        {FAQ_SUPPORT.body}
      </p>
      <Link href="/support" className="content-stretch drop-shadow-[0px_4px_4px_rgba(0,0,0,0.38)] flex h-[63px] items-center justify-center ml-[9px] mt-[17.61px] p-[10px] relative rounded-[35px] w-[269px]">
        <span aria-hidden className="absolute bg-[#262627] inset-0 pointer-events-none rounded-[35px]" />
        <span className="[word-break:break-word] font-semibold leading-[normal] not-italic relative shrink-0 text-[17px] text-center text-white tracking-[-0.68px] whitespace-nowrap">
          {FAQ_SUPPORT.cta}
        </span>
        <span className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
      </Link>
    </div>
  );
}
