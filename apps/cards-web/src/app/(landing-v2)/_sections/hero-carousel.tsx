"use client";
/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */

import Image from "next/image";
import { useState } from "react";

type Slot = {
  centerX: number;
  centerY: number;
  rotate: number;
  imageOffset: { left: number; top: number };
  chip: { left: number; top: number; rotate: number };
};

type Person = {
  src: string;
  height: number;
  label: string;
  chipWidth: number;
  sheen?: boolean;
};

// Fan geometry from the Figma frame (Card 421:3, nodes 421:10–421:26): centre
// of each rotated 218x256 photo card, its tilt, and where the role chip sits.
const SLOTS: Slot[] = [
  { centerX: 135 + 325.592 / 2, centerY: 718 + 334.81 / 2, rotate: -35.12, imageOffset: { left: -11, top: -11 }, chip: { left: 35.05, top: 180.63, rotate: 0 } },
  { centerX: 359 + 281.521 / 2, centerY: 643 + 307.217 / 2, rotate: -16.43, imageOffset: { left: -11, top: -11 }, chip: { left: 38.04, top: 183.27, rotate: 0 } },
  { centerX: 600 + 228.046 / 2, centerY: 629 + 264.499 / 2, rotate: 2.29, imageOffset: { left: -11, top: -11 }, chip: { left: 40.12, top: 183.11, rotate: 0 } },
  { centerX: 779 + 283.58 / 2, centerY: 651 + 308.742 / 2, rotate: 17.08, imageOffset: { left: -11.02, top: -10.97 }, chip: { left: 31.66, top: 188.26, rotate: 0 } },
  { centerX: 947 + 323.467 / 2, centerY: 720 + 333.962 / 2, rotate: 33.74, imageOffset: { left: -10.78, top: -11.16 }, chip: { left: 34.5, top: 186.49, rotate: -0.29 } },
];

const PEOPLE: Person[] = [
  { src: "/assets/landing-v2/rectangle-1430106962-63d2a62404.png", height: 327, label: "GTM", chipWidth: 121.898 },
  { src: "/assets/landing-v2/rectangle-1430106961-ae8a5b24e1.png", height: 273, label: "Product Designer", chipWidth: 134.811, sheen: true },
  { src: "/assets/landing-v2/rectangle-1430106958-e209af98cd.png", height: 327, label: "Software Dev", chipWidth: 121.898 },
  { src: "/assets/landing-v2/rectangle-1430106959-ed29ebb545.png", height: 327, label: "Full stack dev", chipWidth: 121.898 },
  { src: "/assets/landing-v2/rectangle-1430106960-ddd2114224.png", height: 327, label: "Designer", chipWidth: 121.898 },
];

const CARD_W = 218;
const CARD_H = 256;

export function HeroCarousel() {
  const [offset, setOffset] = useState(0);
  const count = PEOPLE.length;

  return (
    <>
      {PEOPLE.map((person, i) => {
        const slotIndex = (i + offset) % count;
        const slot = SLOTS[slotIndex];
        return (
          <div
            key={person.src}
            className="absolute border-11 border-solid border-white h-[256px] overflow-clip rounded-[7px] shadow-[0px_4px_28px_0px_rgba(0,0,0,0.42)] w-[218px] transition-[left,top,rotate] duration-500 ease-out"
            style={{ left: slot.centerX - CARD_W / 2, top: slot.centerY - CARD_H / 2, rotate: `${slot.rotate}deg`, zIndex: slotIndex + 1 }}
          >
            <div
              className="absolute border-5 border-[#474646] border-solid h-[256px] rounded-[7px] shadow-[0px_0px_0px_2px_white,0px_4px_14px_4px_rgba(0,0,0,0.33)] w-[218px]"
              style={{ left: slot.imageOffset.left, top: slot.imageOffset.top }}
            >
              <Image alt="" className="absolute inset-0 max-w-none object-cover pointer-events-none rounded-[7px] size-full" src={person.src} width={CARD_W} height={person.height} loading="eager" />
              {person.sheen && (
                <div className="absolute inset-0 pointer-events-none rounded-[7px]" style={{ backgroundImage: "linear-gradient(3.8725672052428024deg, rgba(102, 102, 102, 0) 2.922%, rgba(255, 255, 255, 0.2) 97.078%)" }} />
              )}
            </div>
            <div
              className="absolute content-stretch drop-shadow-[0px_4px_9.5px_rgba(0,0,0,0.61)] flex h-[38.969px] items-center justify-center p-[10px] rounded-[43px]"
              style={{ left: slot.chip.left, top: slot.chip.top, width: person.chipWidth, rotate: `${slot.chip.rotate}deg` }}
            >
              <div aria-hidden className="absolute bg-white inset-0 pointer-events-none rounded-[43px]" />
              <p className="[word-break:break-word] font-medium leading-[normal] not-italic relative shrink-0 text-[#7e7e7e] text-[13px] text-center tracking-[-0.52px] whitespace-nowrap">
                {person.label}
              </p>
              <div className="absolute inset-0 pointer-events-none rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(0,0,0,0.43)]" />
            </div>
          </div>
        );
      })}
      <button
        type="button"
        aria-label="Next profiles"
        onClick={() => setOffset((o) => (o + 1) % count)}
        className="absolute left-[1273px] size-[88px] top-[933px] z-10 cursor-pointer rounded-full"
      >
        <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/group-1597880892-4f40331185.svg" />
      </button>
      <button
        type="button"
        aria-label="Previous profiles"
        onClick={() => setOffset((o) => (o + count - 1) % count)}
        className="absolute left-[59px] size-[88px] top-[933px] z-10 cursor-pointer rounded-full"
      >
        <img alt="" className="absolute block inset-0 max-w-none size-full" src="/assets/landing-v2/group-1597880891-1d843e2475.svg" />
      </button>
    </>
  );
}
