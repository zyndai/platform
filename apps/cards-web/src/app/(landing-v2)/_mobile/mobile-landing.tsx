/* eslint-disable @next/next/no-img-element -- static SVG icons from the design; next/image adds nothing for vectors */
import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  CTA_BANNER,
  DISCOVER,
  EXPLORE,
  FAQ_HEADLINE,
  HERO,
  HOW_IT_WORKS,
  MCP,
  PRODUCT_CTA,
  PRODUCT_FEATURES,
} from "../_sections/copy";
import { FaqList } from "../_sections/faq-list";
import { HeroCarouselFlow } from "../_sections/hero-carousel-flow";
import { HeroUrlForm } from "../_sections/hero-url-form";
import { MobileNav } from "./mobile-nav";

const A = "/assets/landing-v2/";

/**
 * The same page as the 1440px Figma canvas, re-flowed for phones and tablets
 * (below the `lg` breakpoint). Same sections, copy (from `_sections/copy`) and
 * assets; layout is normal flow, stacked, mobile-first. Section ids are prefixed
 * `m-` so they never clash with the desktop canvas ids (hidden via CSS).
 */
export function MobileLanding() {
  return (
    <main className="overflow-x-clip bg-white pb-6 text-[#262627]">
      <Hero />
      <Product />
      <HowItWorks />
      <CtaBanner />
      <Discover />
      <Mcp />
      <Explore />
      <Faq />
      <Wordmark />
    </main>
  );
}

const H2 = "text-balance text-[38px] font-medium leading-[1.05] tracking-[-0.05em] text-[#262627] sm:text-[52px]";
const LEAD = "text-[17px] font-light leading-[1.45] text-black sm:text-[19px]";
const SECTION = "relative mx-2 mt-3 overflow-clip bg-[#fdfaf1] px-5 sm:mx-3 sm:px-10 scroll-mt-3";

function DarkLink({ href, children, className = "" }: { href: string; children: ReactNode; className?: string }) {
  return (
    <Link href={href} className={`relative flex h-[56px] min-w-[220px] items-center justify-center rounded-[35px] px-8 drop-shadow-[0px_4px_4px_rgba(0,0,0,0.38)] ${className}`}>
      <span aria-hidden className="absolute inset-0 rounded-[35px] bg-[#262627]" />
      <span className="relative whitespace-nowrap text-[17px] font-semibold tracking-[-0.04em] text-white">{children}</span>
      <span className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
    </Link>
  );
}

function Cloud({ className }: { className: string }) {
  return <Image alt="" aria-hidden className={`pointer-events-none absolute max-w-none select-none ${className}`} src={`${A}image-2656-8e521353f9.png`} width={628} height={441} />;
}

function Lines({ lines }: { lines: string[] }) {
  return (
    <>
      {lines.map((line, i) => (
        <span key={line} className="block sm:inline">
          {line}
          {i < lines.length - 1 && " "}
        </span>
      ))}
    </>
  );
}

function Hero() {
  return (
    <header className="relative mx-2 mt-2 overflow-clip rounded-[14px] bg-[#6e6e6e] sm:mx-3 sm:mt-3">
      <Image alt="" className="pointer-events-none absolute inset-0 size-full object-cover object-[40%_30%]" src={`${A}image-2646-fd4c422aa6.png`} width={1484} height={1060} fetchPriority="high" loading="eager" />
      <div aria-hidden className="absolute inset-x-0 bottom-0 h-[45%] bg-gradient-to-t from-white via-white/85 to-transparent" />
      <MobileNav />
      <div className="relative px-5 pb-10 pt-12 text-center sm:px-10 sm:pt-20">
        <h1 className="mx-auto max-w-[640px] text-balance text-[40px] font-bold leading-[1.03] tracking-[-0.05em] text-[#262627] sm:text-[60px]">
          {HERO.headline.join(" ")}
        </h1>
        <p className="mx-auto mt-4 max-w-[360px] text-[18px] leading-[1.3] text-black sm:max-w-[440px] sm:text-[21px]">{HERO.sub}</p>
        <div className="relative mt-8">
          <HeroUrlForm layout="flow" />
        </div>
        <div className="-mx-5 mt-4 sm:-mx-10">
          <HeroCarouselFlow />
        </div>
      </div>
    </header>
  );
}

function FeatureIcon({ k }: { k: (typeof PRODUCT_FEATURES)[number]["key"] }) {
  const map = {
    showcase: { bg: "ellipse-14355-855bb43f48.svg", glyph: "mdi-eye-d6422c5be2.svg", size: "w-[50%]" },
    connect: { bg: "ellipse-14361-37bfc43233.svg", glyph: "group-f488b23a99.svg", size: "w-[38%]" },
    collaborate: { bg: "ellipse-14361-37bfc43233.svg", glyph: "ant-design-team-outlined-d2c86eb292.svg", size: "w-[61%]" },
    skills: { bg: "ellipse-14361-37bfc43233.svg", glyph: "pepicons-pencil-electricity-793898b504.svg", size: "w-[48%]" },
    ai: { bg: "ellipse-14361-37bfc43233.svg", glyph: "weui-discover-filled-6e4d92d301.svg", size: "w-[59%]" },
    opportunities: { bg: "ellipse-14361-37bfc43233.svg", glyph: "fa-solid-brain-e2de72b3e6.svg", size: "w-[45%]" },
  }[k];
  return (
    <span className="relative size-[56px] shrink-0">
      <img alt="" className="absolute inset-0 size-full max-w-none" src={A + map.bg} />
      <img alt="" className={`absolute left-1/2 top-1/2 h-auto max-w-none -translate-x-1/2 -translate-y-1/2 ${map.size}`} src={A + map.glyph} />
    </span>
  );
}

function Product() {
  return (
    <section id="m-product" className="relative mx-2 mt-3 scroll-mt-3 overflow-clip rounded-[8px] bg-[#e3edf4] px-5 pb-12 pt-14 shadow-[0px_4px_0px_0px_rgba(0,0,0,0.13)] sm:mx-3 sm:px-10">
      <img alt="" aria-hidden className="pointer-events-none absolute left-1/2 top-[18px] w-[640px] max-w-none -translate-x-1/2" src={`${A}group-1597880893-fb438652f5.svg`} />
      <span aria-hidden className="pointer-events-none absolute left-1/2 top-[-12px] flex h-[640px] w-[596px] -translate-x-1/2 items-center justify-center">
        <img alt="" className="w-[640px] max-w-none flex-none -rotate-90" src={`${A}group-1597880894-c9c39592c7.svg`} />
      </span>
      <div className="relative mx-auto w-full max-w-[300px] sm:max-w-[330px]">
        <div aria-hidden className="absolute inset-x-6 inset-y-6 rounded-[60px] bg-[#5cbbfb] blur-[50px]" />
        <div className="relative rounded-b-[32px] rounded-t-[60px] bg-white p-4 shadow-[0px_4px_20px_0px_rgba(0,0,0,0.25),inset_0px_4px_5px_0px_rgba(0,0,0,0.4)]">
          <div className="relative aspect-[437/442] overflow-clip rounded-[48px] shadow-[inset_-1px_4px_46px_0px_rgba(0,0,0,0.25)]">
            <Image alt="" className="absolute inset-0 size-full object-cover object-[50%_20%]" src={`${A}image-2651-f7979bcfa8.png`} width={480} height={720} />
            <span className="absolute right-4 top-4 flex h-[30px] items-center gap-1.5 rounded-full border-[0.3px] border-solid border-[#a5a5a5] bg-white px-3 text-[14px] font-medium tracking-[-0.04em] text-[#8a8a8a] shadow-[inset_0px_4px_9px_0px_rgba(0,0,0,0.17)]">
              <img alt="" className="size-3" src={`${A}ellipse-14343-b6375e7ceb.svg`} />
              Online
            </span>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <span className="relative size-[48px] shrink-0 overflow-clip rounded-full">
              <Image alt="" className="absolute left-[-96px] top-[-96px] max-w-none" src={`${A}ellipse-14342-023fd59896.png`} width={241} height={241} />
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block text-[17px] font-semibold tracking-[-0.04em] text-[#121214]">@john</span>
              <span className="block text-[13px] font-medium text-[#6b6969]">Product Designer</span>
            </span>
            <Link href="/create" className="relative flex h-[46px] shrink-0 items-center justify-center rounded-full px-4 text-[15px] text-white drop-shadow-[0px_4px_9.5px_rgba(0,0,0,0.4)]">
              <span aria-hidden className="absolute inset-0 rounded-full bg-[#262627]" />
              <span className="relative whitespace-nowrap">{PRODUCT_CTA}</span>
              <span className="pointer-events-none absolute inset-0 rounded-[inherit] shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]" />
            </Link>
          </div>
        </div>
        <img alt="" className="relative mx-auto mt-2 block w-[250px] max-w-none" src={`${A}group-1597880895-27620fa2df.svg`} />
      </div>
      <ul className="relative mx-auto mt-6 grid max-w-[720px] gap-3 sm:grid-cols-2">
        {PRODUCT_FEATURES.map((f) => (
          <li key={f.key} className="flex items-center gap-3 rounded-[40px] border border-solid border-[#d7d7d7] bg-white p-2 pr-5">
            <FeatureIcon k={f.key} />
            <span className="min-w-0">
              <span className="block text-[18px] font-semibold leading-tight tracking-[-0.04em] text-black">{f.title}</span>
              <span className="mt-0.5 block text-[14px] font-medium leading-[1.3] text-[#6d6d6d]">{f.body}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Chip({ icon, children, tilt }: { icon: string; children: ReactNode; tilt: number }) {
  return (
    <span
      className="inline-flex h-[44px] items-center gap-2 rounded-full border border-solid border-[#e4e4e4] bg-[#f9f7f5] px-4 text-[16px] font-medium text-[#262627] shadow-[0px_4px_6px_-3px_rgba(0,0,0,0.25),inset_0px_4px_5px_0px_rgba(0,0,0,0.08)]"
      style={{ rotate: `${tilt}deg` }}
    >
      <img alt="" className="size-[20px]" src={A + icon} />
      {children}
    </span>
  );
}

function StepHeader({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="relative flex size-[50px] shrink-0 items-center justify-center text-[22px] font-medium tracking-[-0.05em]">
          <img alt="" aria-hidden className="absolute inset-0 size-full" src={`${A}ellipse-14364-aad5983032.svg`} />
          <span className="relative">{n}</span>
        </span>
        <h3 className="text-[26px] font-medium leading-tight tracking-[-0.05em] sm:text-[30px]">{title}</h3>
      </div>
      <p className="mt-3 text-[17px] font-light leading-[1.45] text-black sm:max-w-[420px]">{body}</p>
    </div>
  );
}

function SkillTag({ children }: { children: ReactNode }) {
  return <span className="rounded-full border border-solid border-[#e4e4e4] bg-[#f9f7f5] px-3 py-1 text-[12px] font-medium text-[#505050]">{children}</span>;
}

function HowItWorks() {
  const [s1, s2, s3] = HOW_IT_WORKS.steps;
  return (
    <section id="m-how-it-works" className={`${SECTION} mt-3 rounded-[8px] pb-14 pt-14`}>
      <Cloud className="-right-16 -top-6 w-[320px] opacity-90 sm:right-0 sm:w-[420px]" />
      <h2 className={`relative ${H2}`}>
        <Lines lines={HOW_IT_WORKS.headline} />
      </h2>
      <p className={`relative mt-4 max-w-[460px] ${LEAD}`}>{HOW_IT_WORKS.intro}</p>

      <div className="relative mt-12 grid gap-14 md:grid-cols-2 md:gap-x-10">
        {/* 1: add links */}
        <div className="space-y-6">
          <StepHeader n="01" {...s1} />
          <div className="mx-auto max-w-[340px]">
            <div className="flex flex-wrap justify-center gap-x-3 gap-y-2">
              <Chip icon="ant-design-github-filled-efefdd9e9c.svg" tilt={-3}>Github</Chip>
              <Chip icon="entypo-social-linkedin-with-circle-dd2abf58b3.svg" tilt={2}>Linkedin</Chip>
              <Chip icon="group-3-45f1fe3aeb.svg" tilt={-2}>Portfolio</Chip>
              <Chip icon="group-4-b548d306dd.svg" tilt={4}>Other Links</Chip>
            </div>
            <div className="relative mx-auto mt-6 w-[290px]">
              <span aria-hidden className="absolute inset-0 translate-x-4 translate-y-3 rotate-[-9deg] rounded-[28px] border border-solid border-[#bec9b0] bg-[#d6e0c9]" />
              <span aria-hidden className="absolute inset-0 translate-x-2 translate-y-2 rotate-[-4deg] rounded-[20px] border border-solid border-[#aec5cf] bg-[#dae8ee]" />
              <div className="relative rounded-[22px] bg-white p-4 shadow-[0px_4px_9px_-1px_rgba(0,0,0,0.14)]">
                <div className="flex items-center justify-between">
                  <span className="text-[17px] font-semibold">Zynd</span>
                  <img alt="" className="size-[18px]" src={`${A}iconoir-spark-solid-f48985691f.svg`} />
                </div>
                <div className="mt-3 flex h-[44px] items-center gap-2 rounded-full border border-solid border-[#d3d3d3] bg-[#fefefe] px-3 text-[13px] font-medium">
                  <img alt="" className="size-[16px]" src={`${A}group-2-06bbccf6cf.svg`} />
                  https://github.com/yourname
                </div>
                <span className="mt-3 flex h-[44px] items-center justify-center rounded-full bg-[#262627] text-[14px] font-semibold text-white shadow-[inset_0px_4px_12px_0px_rgba(255,255,255,0.25)]">Build my profile</span>
              </div>
            </div>
          </div>
        </div>

        {/* 2: identity */}
        <div className="space-y-6">
          <StepHeader n="02" {...s2} />
          <div className="relative mx-auto max-w-[340px]">
            <div className="flex flex-wrap justify-center gap-x-3 gap-y-2">
              <Chip icon="mdi-flash-eeb12ec150.svg" tilt={-3}>Skills</Chip>
              <Chip icon="ant-design-camera-filled-a7e59c09de.svg" tilt={2}>Projects</Chip>
              <Chip icon="group-7-f6c4181413.svg" tilt={-2}>About You</Chip>
              <Chip icon="group-4-b548d306dd.svg" tilt={3}>Other Links</Chip>
            </div>
            <div className="relative mx-auto mt-6 w-[270px] rotate-[-4deg] rounded-[22px] bg-white p-3 shadow-[0px_10px_30px_rgba(0,0,0,0.16)]">
              <div className="relative aspect-[4/3] overflow-clip rounded-[16px]">
                <Image alt="" className="absolute inset-0 size-full object-cover object-[50%_15%]" src={`${A}image-26511-a2a3b7e1b8.png`} width={288} height={433} />
                <span className="absolute right-2 top-2 flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[12px] font-medium text-[#a2a2a2]">
                  <img alt="" className="size-2.5" src={`${A}ellipse-14343-b6375e7ceb.svg`} />
                  Online
                </span>
              </div>
              <p className="mt-2 text-[22px] font-semibold leading-none tracking-[-0.05em]">John</p>
              <p className="text-[12px] font-medium text-[#6b6969]">Product Designer</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {["Design", "Figma", "React", "Web 3"].map((t) => <SkillTag key={t}>{t}</SkillTag>)}
              </div>
              <div className="mt-3 flex gap-2">
                {["ant-design-github-filled-efefdd9e9c.svg", "entypo-social-linkedin-with-circle-1-0e8962fa2c.svg", "group-5-dcaaea69ab.svg", "group-6-e434278a5f.svg"].map((g) => (
                  <span key={g} className="relative size-[40px] rounded-full bg-white shadow-[0px_2px_6px_rgba(0,0,0,0.18)]">
                    <img alt="" className="absolute left-1/2 top-1/2 size-[22px] -translate-x-1/2 -translate-y-1/2" src={A + g} />
                  </span>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-3 rounded-[12px] bg-[#f1f1f1] p-2">
                <Image alt="" className="size-[44px] rounded-[5px] object-cover" src={`${A}rectangle-1430106988-a31752bf18.png`} width={78} height={54} />
                <span className="text-[11px] font-medium leading-tight text-[#6b6969]">
                  Current Project
                  <span className="block text-[13px] font-semibold text-[#262627]">Zynd Cards</span>
                  Product Design 2025
                </span>
              </div>
              <p className="mt-3 flex items-center gap-2 text-[13px] font-medium">
                <img alt="" className="size-2.5" src={`${A}ellipse-14343-b6375e7ceb.svg`} />
                Available for new Opportunities.
              </p>
            </div>
          </div>
        </div>

        {/* 3: discovered */}
        <div className="space-y-6 md:col-span-2 md:mx-auto md:max-w-[520px]">
          <StepHeader n="03" {...s3} />
          <div className="mx-auto flex max-w-[340px] items-end justify-center gap-4">
            <div className="flex w-[130px] shrink-0 flex-col items-center">
              <Image alt="" className="w-[120px]" src={`${A}image-2659-7b88293419.png`} width={198} height={141} />
              <p className="mt-2 w-full rounded-[19px] border border-solid border-[#ddd] bg-white px-3 py-2 text-[13px] leading-tight shadow-[0px_4px_4px_0px_rgba(0,0,0,0.09)]">
                <span className="block text-[15px] font-medium">Hi</span>
                <span className="text-[#6d6d6d]">Lemme help you find a great match!</span>
              </p>
            </div>
            <div className="relative h-[200px] w-[170px] shrink-0">
              <span aria-hidden className="absolute inset-y-4 right-0 w-[130px] rotate-[10deg] rounded-[14px] bg-white opacity-70 shadow-[0px_4px_14px_rgba(0,0,0,0.15)]" />
              <div className="absolute left-0 top-0 w-[150px] rounded-[14px] bg-white p-2 shadow-[0px_6px_18px_rgba(0,0,0,0.2)]">
                <div className="relative overflow-clip rounded-[10px]">
                  <Image alt="" className="aspect-[149/112] w-full object-cover" src={`${A}rectangle-1430106993-312c592cc1.png`} width={149} height={112} />
                  <span className="absolute right-0 top-0 rounded-bl-[8px] bg-[#e3f4da] px-2 py-0.5 text-[11px] font-medium text-[#58ae31]">Match</span>
                </div>
                <p className="mt-2 text-[13px] font-semibold leading-none">Riya Sharma</p>
                <p className="text-[11px] font-medium text-[#6b6969]">Frontend Developer</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {["React", "UI UX", "Web dev"].map((t) => <SkillTag key={t}>{t}</SkillTag>)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function CtaBanner() {
  return (
    <section className="relative mx-2 mt-3 flex min-h-[380px] flex-col items-center justify-between overflow-clip px-5 py-12 text-center sm:mx-3 sm:min-h-[440px]">
      <Image alt="" className="pointer-events-none absolute inset-0 size-full object-cover object-[60%_100%]" src={`${A}frame-2147261358-df69ab0a91.png`} width={1362} height={474} />
      <h2 className="relative max-w-[560px] text-balance text-[38px] font-medium leading-[1.05] tracking-[-0.05em] text-[#262627] sm:text-[52px]">
        {CTA_BANNER.headline.join(" ")}
      </h2>
      <DarkLink href="/create" className="relative mt-10">{CTA_BANNER.cta}</DarkLink>
    </section>
  );
}

function Pill({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`relative inline-flex h-[34px] items-center rounded-full bg-[#4e4e5a] px-4 text-[13px] font-medium tracking-[-0.02em] text-white drop-shadow-[0px_4px_5.5px_rgba(0,0,0,0.18)] ${className}`}>
      {children}
    </span>
  );
}

function Person({ src, role, pos = "50% 0%" }: { src: string; role: string; pos?: string }) {
  return (
    <li className="flex flex-col items-center">
      <span className="relative block size-[112px] overflow-clip rounded-full border-[6px] border-solid border-white bg-white shadow-[0px_4px_4px_0px_rgba(0,0,0,0.25)] sm:size-[140px]">
        <Image alt="" className="size-full -scale-x-100 object-cover" style={{ objectPosition: pos }} src={A + src} width={200} height={300} />
      </span>
      <Pill className="-mt-3">{role}</Pill>
    </li>
  );
}

function Discover() {
  return (
    <section id="m-discover" className={`${SECTION} rounded-[8px] pb-14 pt-14`}>
      <Cloud className="-right-20 -top-10 w-[300px] opacity-80 sm:right-0 sm:w-[420px]" />
      <h2 className={`relative ${H2}`}>
        <Lines lines={DISCOVER.headline} />
      </h2>
      <p className={`relative mt-4 max-w-[480px] ${LEAD}`}>{DISCOVER.body}</p>
      <div className="relative mt-10">
        <Cloud className="left-[-20%] top-[10%] w-[110%] opacity-30" />
        <ul className="relative mx-auto grid max-w-[520px] grid-cols-2 justify-items-center gap-x-4 gap-y-8 sm:grid-cols-3">
          <Person src="image-2667-1c44d0d4ad.png" role="UI/UX designer" pos="50% 15%" />
          <Person src="rectangle-1430106958-e209af98cd.png" role="Frontend Developer" />
          <Person src="image-2666-0fe80f6168.png" role="Content Creator" />
          <Person src="image-2668-09082652b2.png" role="Illustrator" />
          <Person src="image-2669-ec4e37a04f.png" role="Product Designer" />
          <li className="flex items-center justify-center">
            <Image alt="" className="w-[130px]" src={`${A}image-2659-7b88293419.png`} width={308} height={219} />
          </li>
        </ul>
      </div>
      <div className="relative mt-12 flex justify-center">
        <DarkLink href="/network">{DISCOVER.cta}</DarkLink>
      </div>
    </section>
  );
}

const MCP_GLYPHS = ["group-d36c5b29d0.svg", "group-1-c4f1cd5141.svg", "vector-72e2e45cd4.svg", "vector-1-16f7f1a807.svg"];

function Mcp() {
  return (
    <section id="m-mcp" className={`${SECTION} rounded-[8px] pt-[150px]`}>
      <Cloud className="-right-20 -top-6 w-[320px] opacity-90 sm:right-0 sm:w-[420px]" />
      <Image alt="" className="pointer-events-none absolute right-[12%] top-[28px] w-[150px] -rotate-[13deg] sm:w-[200px]" src={`${A}image-2659-7b88293419.png`} width={258} height={184} />
      <h2 className={`relative ${H2}`}>
        <Lines lines={MCP.headline} />
      </h2>
      <p className={`relative mt-4 max-w-[460px] ${LEAD}`}>{MCP.body}</p>
      <div className="relative mt-8 flex flex-wrap items-center gap-3">
        <span className="rotate-[-5deg] rounded-[24px] border-[7px] border-solid border-white bg-[#f8f8f8] px-5 py-4 text-[18px] font-medium leading-tight tracking-[-0.04em] text-black drop-shadow-[0px_4px_2px_rgba(0,0,0,0.25)]">
          {MCP.note[0]} <br className="hidden sm:block" />
          {MCP.note[1]}
        </span>
        <span className="flex flex-col gap-2 pl-2">
          <Chip icon="ant-design-github-filled-efefdd9e9c.svg" tilt={-2}>Github</Chip>
          <Chip icon="entypo-social-linkedin-with-circle-dd2abf58b3.svg" tilt={2}>Linkedin</Chip>
          <Chip icon="bxl-notion-804f650110.svg" tilt={-1}>Notion</Chip>
        </span>
      </div>
      <div className="relative mx-auto mt-12 max-w-[760px] rounded-[16px] border-[0.5px] border-solid border-[#d9d9d9] bg-white p-6 shadow-[0px_4px_16px_0px_rgba(0,0,0,0.06)] sm:p-8">
        <h3 className="text-[26px] font-semibold leading-tight tracking-[-0.05em] sm:text-[27px]">{MCP.listTitle}</h3>
        <ul className="mt-6 grid gap-6 sm:grid-cols-2">
          {MCP.features.map((f, i) => (
            <li key={f.title} className="flex items-start gap-4">
              <span className="relative size-[52px] shrink-0">
                <img alt="" className="absolute inset-0 size-full" src={`${A}group-1597880899-017ebe0abb.svg`} />
                <img alt="" className="absolute left-1/2 top-1/2 h-[24px] w-auto max-w-[24px] -translate-x-1/2 -translate-y-1/2" src={A + MCP_GLYPHS[i]} />
              </span>
              <span>
                <span className="block text-[17px] font-semibold leading-tight tracking-[-0.04em]">{f.title}</span>
                <span className="mt-1 block text-[15px] font-light leading-[1.4] text-black">{f.body}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="relative -mx-5 mt-[-40px] flex justify-center sm:-mx-10">
        <Image alt="" className="absolute inset-x-0 bottom-0 h-full w-full object-cover object-[50%_100%]" src={`${A}image-2662-2b92a48855.png`} width={1429} height={478} />
        <div className="relative pb-12 pt-[110px]">
          <DarkLink href="/claude">{MCP.cta}</DarkLink>
        </div>
      </div>
    </section>
  );
}

const EXPLORE_ICONS: ReactNode[] = [
  <span key="0" className="relative size-[52px] shrink-0">
    <img alt="" className="absolute inset-0 size-full" src={`${A}ellipse-14374-ff5bc30d2c.svg`} />
    <img alt="" className="absolute left-1/2 top-1/2 w-[53%] -translate-x-1/2 -translate-y-1/2" src={`${A}group-04774a9f5b.svg`} />
  </span>,
  <span key="1" className="relative size-[52px] shrink-0">
    <img alt="" className="absolute inset-0 size-full" src={`${A}ellipse-14374-ff5bc30d2c.svg`} />
    <img alt="" className="absolute left-1/2 top-1/2 w-[40%] -translate-x-1/2 -translate-y-1/2" src={`${A}group-1-62fe7d74c8.svg`} />
  </span>,
  ...["group-1597880902-ebd01d5049.svg", "group-1597880900-118f5968dd.svg", "group-1597880903-e5fb3f36e8.svg", "group-1597880904-f6a17b0aa3.svg"].map((g) => (
    <img key={g} alt="" className="size-[52px] shrink-0" src={A + g} />
  )),
];

function Explore() {
  return (
    <section id="m-explore" className={`${SECTION} rounded-[8px] pb-0 pt-[170px]`}>
      <Cloud className="-right-16 top-0 w-[340px] opacity-90 sm:right-0 sm:w-[440px]" />
      <Image alt="" className="pointer-events-none absolute right-[10%] top-[24px] w-[170px] -rotate-[13deg] sm:w-[240px]" src={`${A}image-2659-7b88293419.png`} width={437} height={311} />
      <h2 className={`relative ${H2}`}>
        <Lines lines={EXPLORE.headline} />
      </h2>
      <p className={`relative mt-4 max-w-[400px] ${LEAD}`}>{EXPLORE.body}</p>
      <DarkLink href="/create" className="relative mt-8 w-full sm:w-fit">{EXPLORE.cta}</DarkLink>
      <ul className="relative mt-12 grid gap-3 sm:grid-cols-2">
        {EXPLORE.items.map((item, i) => (
          <li key={item.title} className="flex items-start gap-4 rounded-[13px] border-[0.5px] border-solid border-[#d9d9d9] bg-[#fffefe] p-4 shadow-[0px_4px_16px_0px_rgba(0,0,0,0.04)]">
            {EXPLORE_ICONS[i]}
            <span>
              <span className="block text-[20px] font-semibold leading-tight tracking-[-0.05em]">{item.title}</span>
              <span className="mt-1 block text-[16px] leading-[1.35] text-black">{item.body}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="relative -mx-5 mt-8 h-[150px] sm:-mx-10 sm:h-[220px]">
        <Image alt="" className="size-full object-cover object-[50%_100%]" src={`${A}image-2662-2b92a48855.png`} width={1429} height={478} />
      </div>
    </section>
  );
}

function Faq() {
  return (
    <section id="m-faq" className="relative mx-2 mt-3 scroll-mt-3 overflow-clip bg-[#fdfaf1] px-4 pb-14 pt-14 sm:mx-3 sm:px-10">
      <div className="pointer-events-none absolute inset-0 opacity-50">
        <Image alt="" className="size-full object-cover" src={`${A}image-2661-0b8f242f3b.png`} width={1424} height={1013} />
      </div>
      <h2 className={`relative mb-8 text-center ${H2}`}>
        <Lines lines={FAQ_HEADLINE} />
      </h2>
      <div className="relative">
        <FaqList layout="flow" />
      </div>
    </section>
  );
}

// Same debossed white wordmark as the canvas, scaled to the viewport width.
function Wordmark() {
  return (
    <svg aria-hidden viewBox="0 0 1460 411" className="mt-6 block h-auto w-[calc(100%+8px)] max-w-none overflow-visible -translate-x-1">
      <defs>
        <filter id="landing-v2-m-wordmark-inset" x="-2%" y="-5%" width="104%" height="110%">
          <feComponentTransfer in="SourceAlpha" result="inverse">
            <feFuncA type="table" tableValues="1 0" />
          </feComponentTransfer>
          <feGaussianBlur in="inverse" stdDeviation="4" />
          <feOffset dx="2" dy="4" result="shadow" />
          <feFlood floodColor="#000" floodOpacity="0.3" />
          <feComposite in2="shadow" operator="in" />
          <feComposite in2="SourceAlpha" operator="in" result="inner" />
          <feMerge>
            <feMergeNode in="SourceGraphic" />
            <feMergeNode in="inner" />
          </feMerge>
        </filter>
      </defs>
      <text x={0} y={351} fill="#fff" filter="url(#landing-v2-m-wordmark-inset)" className="font-extrabold text-[400px] tracking-[-20px]" textLength={1441} lengthAdjust="spacing">
        ZYNDAI
      </text>
    </svg>
  );
}
