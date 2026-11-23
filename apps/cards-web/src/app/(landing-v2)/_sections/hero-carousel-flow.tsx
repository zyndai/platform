"use client";
/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */

import Image from "next/image";
import { useRef } from "react";

import { CARD_W, PEOPLE } from "./hero-carousel";

// Phone/tablet version of HeroCarousel: the same five people as a swipeable
// snap strip, with the design's arrow buttons scrolling it. The desktop fan
// needs ~1300px of canvas.
export function HeroCarouselFlow() {
  const ref = useRef<HTMLUListElement>(null);
  const scrollByCard = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    const card = el.querySelector("li");
    const step = (card?.getBoundingClientRect().width ?? 200) + 16;
    el.scrollBy({ left: dir * step, behavior: "smooth" });
  };
  return (
    <div className="relative">
      <ul ref={ref} className="flex snap-x snap-mandatory gap-4 overflow-x-auto px-[max(16px,calc(50%-100px))] pb-6 pt-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {PEOPLE.map((person, i) => (
          <li
            key={person.src}
            className="relative aspect-[218/256] w-[200px] shrink-0 snap-center overflow-clip rounded-[7px] border-[8px] border-solid border-white shadow-[0px_4px_20px_0px_rgba(0,0,0,0.35)] sm:w-[218px]"
            style={{ rotate: `${[-3, 2, -1.5, 3, -2][i % 5]}deg` }}
          >
            <Image alt="" className="pointer-events-none absolute inset-0 size-full max-w-none rounded-[3px] object-cover" src={person.src} width={CARD_W} height={person.height} loading="eager" />
            {person.sheen && (
              <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: "linear-gradient(3.87deg, rgba(102, 102, 102, 0) 2.9%, rgba(255, 255, 255, 0.2) 97%)" }} />
            )}
            <span className="absolute bottom-3 left-1/2 flex h-[34px] -translate-x-1/2 items-center rounded-full bg-white px-4 text-[13px] font-medium tracking-[-0.04em] whitespace-nowrap text-[#7e7e7e] shadow-[0px_4px_9.5px_rgba(0,0,0,0.4),inset_0px_4px_12px_0px_rgba(0,0,0,0.25)]">
              {person.label}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex justify-center gap-4">
        <button type="button" aria-label="Previous profiles" onClick={() => scrollByCard(-1)} className="size-[56px] cursor-pointer rounded-full">
          <img alt="" className="block size-full" src="/assets/landing-v2/group-1597880891-1d843e2475.svg" />
        </button>
        <button type="button" aria-label="Next profiles" onClick={() => scrollByCard(1)} className="size-[56px] cursor-pointer rounded-full">
          <img alt="" className="block size-full" src="/assets/landing-v2/group-1597880892-4f40331185.svg" />
        </button>
      </div>
    </div>
  );
}
