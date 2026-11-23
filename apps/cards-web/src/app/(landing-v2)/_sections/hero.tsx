/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */
import Image from "next/image";
import Link from "next/link";

import { HeroAuthCta } from "./hero-auth-cta";
import { HeroCarousel } from "./hero-carousel";
import { HeroUrlForm } from "./hero-url-form";
import { HERO, NAV_LINKS } from "./copy";

// Desktop-only x positions (canvas px) for the shared NAV_LINKS, in order.
const NAV_CENTERS = [538.5, 672, 808.5, 914.5];

export function HeroSection() {
  return (
    <>
      <header className="absolute bg-[#6e6e6e] h-[1070px] left-[10px] overflow-clip rounded-[14px] top-[11px] w-[1419px]">
        <div className="absolute h-[1086px] left-[-40px] rounded-[14px] top-0 w-[1499px]">
          <div className="absolute inset-0 overflow-hidden pointer-events-none rounded-[14px]">
            <Image alt="" className="absolute h-[126.88%] left-[-14.38%] max-w-none top-[-13.44%] w-[128.68%]" src="/assets/landing-v2/image-2646-fd4c422aa6.png" width={1929} height={1378} fetchPriority="high" loading="eager" />
          </div>
        </div>
        <div className="absolute bg-white blur-[143px] h-[637px] left-0 rounded-[15px] top-[658px] w-[1419px]" />
        <h1 className="-translate-x-1/2 [word-break:break-word] absolute font-bold leading-[0] left-[710.5px] not-italic text-[#262627] text-[63px] text-center top-[238px] tracking-[-3.15px] whitespace-nowrap">
          {HERO.headline.map((line) => (
            <span key={line} className="block leading-[1.028]">{line}</span>
          ))}
        </h1>
        <p className="-translate-x-1/2 [word-break:break-word] absolute font-normal leading-[normal] left-[709.5px] not-italic text-[21px] text-black text-center top-[382px] w-[445px]">
          {HERO.sub}
        </p>
        <HeroAuthCta />
        <HeroCarousel />
        <div className="absolute flex inset-[38.22%_80.69%_54.59%_13.81%] items-center justify-center" style={{ containerType: "size" }}>
          <div className="flex-none h-[hypot(44.2834cqw,55.7166cqh)] rotate-[-38.06deg] skew-x-[0.83deg] w-[hypot(55.7166cqw,-44.2834cqh)]">
            <div className="relative size-full">
              <div className="absolute inset-[-5.45%_-12.68%_-20%_-12.68%]">
                <img alt="" className="block max-w-none size-full" src="/assets/landing-v2/vector-444035a910.svg" />
              </div>
            </div>
          </div>
        </div>
        <nav aria-label="Primary" className="absolute bg-[#f1f1f1] border-[#b9b9b9] border-[0.8px] border-solid h-[62px] left-[417px] rounded-[71px] top-[35px] w-[602px]">
          {NAV_LINKS.map((link, i) => (
            <a
              key={link.href}
              href={link.href}
              className="-translate-x-1/2 [word-break:break-word] absolute font-normal leading-[1.178] not-italic text-[16px] text-black text-center top-[19.2px] tracking-[-0.8px] whitespace-nowrap hover:opacity-60 transition-opacity"
              style={{ left: NAV_CENTERS[i] - 417.8 }}
            >
              {link.label}
            </a>
          ))}
        </nav>
        <HeroUrlForm />
        <Link href="/" aria-label="Zynd home" className="-translate-x-1/2 [word-break:break-word] absolute font-extrabold leading-[normal] left-[129px] not-italic text-[#262627] text-[38px] text-center top-[43px] tracking-[-1.52px] whitespace-nowrap">
          ZYND
        </Link>
      </header>
      <div className="absolute flex items-center justify-center left-[1142px] size-[102.982px] top-[371px]">
        <div className="flex-none rotate-38">
          <div className="relative size-[73.366px]">
            <Image alt="" className="absolute inset-0 max-w-none object-contain pointer-events-none size-full" src="/assets/landing-v2/x-f1f1021dd8.png" width={73} height={73} />
          </div>
        </div>
      </div>
    </>
  );
}
