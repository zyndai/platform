"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useRef } from "react";

const CARDS_API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.zynd.ai";

import { HeroCardStack } from "./hero-card-stack";
import { Typewriter } from "./typewriter";
import { AgentCardAuthBar } from "./auth-bar";

/**
 * `/agent-card` — the standalone Zynd landing page.
 *
 * Static marketing markup, with two live hooks into the create flow:
 *  - every "Create your Living Profile" / "Claim Handle" CTA links to /create
 *  - the ingestion paste bar pushes to /create?url=<pasted link>, where the
 *    create page seeds it as the first source chip.
 */
export default function AgentCardPage() {
  const router = useRouter();
  const [link, setLink] = useState("");

  // Hand the pasted link off to /create rather than synthesizing here — the
  // create page owns auth, validation and the job polling.
  function synthesize() {
    const trimmed = link.trim();
    router.push(trimmed ? `/create?url=${encodeURIComponent(trimmed)}` : "/create");
  }

  // Handle claim section — debounced availability check
  const [handle, setHandle] = useState("");
  const [handleStatus, setHandleStatus] = useState<"idle" | "checking" | "available" | "taken" | "error">("idle");
  const handleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function onHandleInput(raw: string) {
    const slug = raw.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
    setHandle(slug);
    setHandleStatus("idle");
    if (handleTimer.current) clearTimeout(handleTimer.current);
    if (slug.length < 2) return;
    setHandleStatus("checking");
    handleTimer.current = setTimeout(async () => {
      try {
        const r = await fetch(`${CARDS_API}/cards/handle-available/${encodeURIComponent(slug)}`);
        if (!r.ok) { setHandleStatus("error"); return; }
        const d = await r.json();
        setHandleStatus(d.available ? "available" : "taken");
      } catch {
        setHandleStatus("error");
      }
    }, 400);
  }

  function claimHandle() {
    if (!handle || handleStatus === "taken") return;
    router.push(`/create?handle=${encodeURIComponent(handle)}`);
  }

  return (
    <>
{/* BEGIN: HeaderNav */}
<header className="sticky top-0 z-50 backdrop-blur-xl bg-[#080909]/90 border-b border-white/[0.08]" data-purpose="top-navigation">
<div className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 h-16 sm:h-20 flex items-center justify-between">
{/* Brand Logo */}
<Link aria-label="Zynd Home" className="flex items-center gap-3 group" href="/">
<img src="/assets/zynd-logo.png" alt="Zynd" className="h-9 sm:h-10 w-auto opacity-90 group-hover:opacity-100 transition-opacity" style={{filter: "brightness(0) invert(1)"}} />
<span className="text-2xl font-bold text-white tracking-wide opacity-90 group-hover:opacity-100 transition-opacity">Zynd</span>
<span className="hidden sm:inline-block text-[10px] font-mono text-white/60 tracking-widest pl-3 border-l border-white/20">LIVING IDENTITY</span>
</Link>
{/* Navigation links */}
<nav className="hidden md:flex items-center gap-7 text-xs font-mono text-[#8a8a84]">
<a className="hover:text-white transition-colors" href="#ingestion">Synthesize</a>
<a className="hover:text-white transition-colors" href="#paradigm">Shift</a>
<a className="hover:text-white transition-colors" href="#signals">Signals</a>
<a className="hover:text-white transition-colors" href="#discovery">Agent Query</a>
<a className="hover:text-white transition-colors" href="#dual-view">Dual Interface</a>
<a className="hover:text-white transition-colors" href="#privacy">Privacy</a>
</nav>
{/* Quick Action CTA */}
<div className="flex items-center gap-3">
<a className="text-xs font-mono font-medium text-white/80 hover:text-white px-3 py-2 transition-colors hidden lg:block" href="https://www.zynd.ai">Explore Network</a>
<AgentCardAuthBar />
</div>
</div>
</header>
{/* END: HeaderNav */}
<main className="space-y-24 sm:space-y-32 pb-24">
{/* ========================================================================= */}
{/* SECTION 01 — HERO (THE HOOK & REAL PREVIEW) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 pt-10 sm:pt-16 lg:pt-20" data-purpose="hero">
<div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-start">
{/* Left 7 cols */}
<div className="lg:col-span-7 space-y-7">
<div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/[0.04] border border-white/10 text-xs font-mono text-[#7b72e9]">
<span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9] animate-pulse"></span>
<span className="tracking-wider uppercase">Living Identity for Builders &amp; Agents</span>
</div>
<h1 className="font-display text-4xl sm:text-6xl lg:text-[68px] font-normal text-white uppercase tracking-tight leading-[0.94]">
          Your next collaborator won&apos;t Google you. <br />
<span className="text-[#7b72e9]">Their agent will.</span>
</h1>
{/* 3 Key Value Subtitle items */}
<div className="space-y-2 text-sm sm:text-base text-[#a0a09a]">
<div className="flex items-center gap-2.5">
<span className="text-[#7b72e9] font-mono text-xs">●</span>
<span className="text-white font-medium">Zynd creates a living professional identity.</span>
</div>
<div className="flex items-center gap-2.5">
<span className="text-[#7b72e9] font-mono text-xs">●</span>
<span className="">Built from the internet you already have (GitHub, LinkedIn, papers, work).</span>
</div>
<div className="flex items-center gap-2.5">
<span className="text-[#7b72e9] font-mono text-xs">●</span>
<span className="">Directly discoverable by people and searchable by AI agents.</span>
</div>
</div>
{/* Primary and Secondary Actions */}
<div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-2">
<Link className="bg-[#7b72e9] hover:bg-[#a78bfa] text-black font-mono font-bold text-sm py-3.5 px-6 rounded-xl transition-all shadow-[0_0_24px_rgba(123,114,233,0.3)] flex items-center justify-center gap-2 active:scale-95" href="/create">
<span className="">Create your Living Profile</span>
<span className="text-base leading-none">→</span>
</Link>
<Link className="bg-white/[0.05] hover:bg-white/[0.09] text-white border border-white/15 font-mono text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2" href="/directory">
<span className="">Explore the Network</span>
<span className="text-xs text-[#a0a09a]">→</span>
</Link>
</div>
<div className="flex flex-wrap items-center gap-5 text-xs font-mono text-[#7d7d77] pt-2">
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">✓</span> Free to create</span>
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">✓</span> 60-second synthesis</span>
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">✓</span> No password or resume needed</span>
</div>
</div>
{/* Right 5 cols: ANIMATED LIVING-PROFILE CARD STACK */}
<div className="lg:col-span-5 relative" data-purpose="hero-profile-card">
<div className="absolute -inset-1 bg-gradient-to-tr from-[#7b72e9]/20 via-transparent to-[#7b72e9]/5 rounded-3xl blur-2xl -z-10 opacity-70"></div>
<HeroCardStack />
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 02 — CREATE YOUR PROFILE (THE INGESTION) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="how-to-create" id="ingestion">
<div className="rounded-3xl bg-[#0e1010] border border-white/10 p-7 sm:p-11 lg:p-14 space-y-10">
<div className="max-w-3xl space-y-3">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 01 THE INGESTION"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          Paste your internet. Get your profile.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a] leading-relaxed">
          LinkedIn + GitHub + X + website → Zynd synthesizes them → living profile in 60 seconds. No resume builder. No blank forms to stare at.
        </p>
</div>
{/* Interactive paste bar */}
<div className="p-2.5 rounded-2xl bg-[#121413] border border-white/15 shadow-2xl max-w-3xl">
<div className="flex flex-col sm:flex-row items-stretch gap-2.5">
<div className="flex items-center flex-1 bg-[#080909] border border-white/10 rounded-xl px-4 py-3.5 focus-within:border-[#7b72e9] transition-all">
<span className="material-symbols-outlined text-[#7d7d77] text-lg mr-2">link</span>
<input autoComplete="off" className="w-full bg-transparent border-none p-0 text-xs sm:text-sm font-mono text-white placeholder:text-[#52524c] focus:ring-0" placeholder="github.com/your-handle or linkedin.com/in/your-profile" spellCheck="false" type="text" value={link} onChange={e => setLink(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); synthesize(); } }} />
</div>
<button className="bg-[#7b72e9] hover:bg-[#a78bfa] text-black font-mono font-bold text-xs sm:text-sm py-3.5 px-6 rounded-xl transition-all flex items-center justify-center gap-2 active:scale-95 shrink-0" type="button" onClick={synthesize}>
<span className="">Synthesize Living Profile</span>
<span className="text-base leading-none">→</span>
</button>
</div>
</div>
{/* 3-step footprint pills */}
<div className="grid grid-cols-1 md:grid-cols-3 gap-5 relative pt-2">
{/* Pill 1 */}
<div className="p-5 rounded-2xl bg-[#121413] border border-white/[0.08] space-y-3">
<div className="flex items-center justify-between">
<span className="text-xs font-mono text-[#7b72e9] font-bold">SOURCE FOOTPRINTS</span>
<span className="text-[10px] font-mono text-[#7d7d77]">01</span>
</div>
<div className="space-y-1.5">
<div className="px-2.5 py-1 rounded bg-[#080909] border border-white/10 text-xs font-mono text-white flex items-center justify-between">
<span className="">GitHub Traces</span>
<span className="text-[10px] text-emerald-400">Commits &amp; PRs</span>
</div>
<div className="px-2.5 py-1 rounded bg-[#080909] border border-white/10 text-xs font-mono text-white flex items-center justify-between">
<span className="">LinkedIn / Resume</span>
<span className="text-[10px] text-[#8b8b85]">Historical roles</span>
</div>
<div className="px-2.5 py-1 rounded bg-[#080909] border border-white/10 text-xs font-mono text-white flex items-center justify-between">
<span className="">X / Writing / Web</span>
<span className="text-[10px] text-[#8b8b85]">Current ideas</span>
</div>
</div>
</div>
{/* Pill 2 */}
<div className="p-5 rounded-2xl bg-[#121413] border border-[#7b72e9]/30 space-y-3 relative">
<div className="flex items-center justify-between">
<span className="text-xs font-mono text-[#7b72e9] font-bold">ZYND SYNTHESIS</span>
<span className="text-[10px] font-mono text-[#7b72e9]">02</span>
</div>
<p className="text-xs text-[#a0a09a] leading-relaxed">
            Extracts active technologies, recent architectural decisions, problem domains, and current collaboration intent automatically.
          </p>
<div className="text-[11px] font-mono text-[#7b72e9] flex items-center gap-1.5 pt-1">
<span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9] animate-ping"></span>
            60s automated distillation
          </div>
</div>
{/* Pill 3 */}
<div className="p-5 rounded-2xl bg-[#121413] border border-white/[0.08] space-y-3">
<div className="flex items-center justify-between">
<span className="text-xs font-mono text-white font-bold">ONE LIVING PROFILE</span>
<span className="text-[10px] font-mono text-[#7d7d77]">03</span>
</div>
<p className="text-xs text-[#a0a09a] leading-relaxed">
            A single link ready for human peers to browse and an indexable semantic schema ready for AI search agents.
          </p>
<div className="text-xs font-mono text-[#7b72e9] pt-1">
            zynd.me/@your-name →
          </div>
</div>
</div>
{/* Transitional note */}
<div className="pt-2 border-t border-white/[0.08] text-center">
<p className="text-xs sm:text-sm font-mono text-[#8E8E88]">
          But Zynd isn&apos;t just another profile page. <span className="text-[#7b72e9]">↓</span>
</p>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 03 — LINKEDIN VS LINKTREE VS ZYND (CATEGORY SHIFT) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="category-shift" id="paradigm">
<div className="space-y-8">
<div className="max-w-3xl space-y-3">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 02 CATEGORY SHIFT"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          The internet has profiles. It doesn&apos;t have living identities.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a] leading-relaxed">
          Why add another link when you already have three? Because existing profiles were built for an era before real-time momentum and autonomous discovery agents.
        </p>
</div>
{/* 3-column structured comparative matrix */}
<div className="grid grid-cols-1 md:grid-cols-3 gap-6">
{/* LinkedIn */}
<div className="p-6 sm:p-7 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-4 opacity-55">
<div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
<h3 className="text-xl font-bold text-white">LinkedIn</h3>
<span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/5 text-[#7d7d77] border border-white/10">CAREER ARCHIVE</span>
</div>
<div className="space-y-3 text-xs font-mono">
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Core focus</div>
<div className="text-white font-medium">Who you were</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Format</div>
<div className="text-[#a0a09a]">Retrospective career history</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Audience</div>
<div className="text-[#a0a09a]">Written for recruiters &amp; humans</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Maintenance</div>
<div className="text-rose-400">Manually maintained (chronically stale)</div>
</div>
</div>
</div>
{/* Linktree */}
<div className="p-6 sm:p-7 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-4 opacity-55">
<div className="flex items-center justify-between border-b border-white/[0.08] pb-3">
<h3 className="text-xl font-bold text-white">Linktree</h3>
<span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/5 text-[#7d7d77] border border-white/10">LINK DIRECTORY</span>
</div>
<div className="space-y-3 text-xs font-mono">
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Core focus</div>
<div className="text-white font-medium">Where you exist</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Format</div>
<div className="text-[#a0a09a]">Flat list of external URLs</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Audience</div>
<div className="text-[#a0a09a]">Written for manual human clickers</div>
</div>
<div>
<div className="text-[10px] text-[#7d7d77] uppercase">Maintenance</div>
<div className="text-[#a0a09a]">Manual bookmark editing</div>
</div>
</div>
</div>
{/* Zynd */}
<div className="p-6 sm:p-7 rounded-2xl bg-[#121413] border-2 border-[#7b72e9] space-y-4 shadow-[0_0_30px_rgba(123,114,233,0.1)] relative">
<div className="flex items-center justify-between border-b border-[#7b72e9]/20 pb-3">
<h3 className="text-xl font-bold text-white flex items-center gap-1.5">
<span className="">Zynd</span>
<span className="text-[#7b72e9] text-sm">★</span>
</h3>
<span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#7b72e9]/20 text-[#7b72e9] font-bold border border-[#7b72e9]/30">LIVING IDENTITY</span>
</div>
<div className="space-y-3 text-xs font-mono">
<div>
<div className="text-[10px] text-[#7b72e9] uppercase">Core focus</div>
<div className="text-white font-medium text-sm">What you&apos;re doing now</div>
</div>
<div>
<div className="text-[10px] text-[#7b72e9] uppercase">Format</div>
<div className="text-[#d7d7d1]">Active momentum &amp; 3 living signals</div>
</div>
<div>
<div className="text-[10px] text-[#7b72e9] uppercase">Audience</div>
<div className="text-white">Built for humans + AI agents</div>
</div>
<div>
<div className="text-[10px] text-[#7b72e9] uppercase">Maintenance</div>
<div className="text-emerald-400">Can stay current through your AI</div>
</div>
</div>
</div>
</div>
{/* Prominent Editorial Punchline Banner */}
<div className="p-6 sm:p-7 rounded-2xl bg-[#0e1010] border border-white/10 text-center space-y-2">
<p className="font-display uppercase text-2xl sm:text-3xl text-white tracking-wide">
          &quot;LinkedIn tells people who you were. Linktree tells them where you are. <br className="hidden sm:inline" />
<span className="text-[#7b72e9]">Zynd tells them what you&apos;re doing now.</span>&quot;
        </p>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 04 — THE THREE SIGNALS (USEFUL INFORMATION) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="three-signals" id="signals">
<div className="space-y-10">
<div className="max-w-3xl space-y-3">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 03 USEFUL INFORMATION"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          A profile that actually tells people something useful.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a] leading-relaxed">
          Your profile revolves around three dynamic signals. They answer the only three questions potential collaborators, founders, and peer engineers need to know.
        </p>
</div>
{/* 3 signal cards */}
<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
{/* Signal 1 */}
<div className="p-7 rounded-3xl bg-[#0e1010] border border-white/10 space-y-4 hover:border-white/20 transition-all flex flex-col justify-between">
<div className="space-y-3">
<div className="inline-flex p-2.5 rounded-xl bg-[#7b72e9]/10 text-[#7b72e9] border border-[#7b72e9]/20">
<span className="material-symbols-outlined text-2xl">terminal</span>
</div>
<div>
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">SIGNAL 01</div>
<h3 className="text-2xl font-display uppercase tracking-wide text-white mt-0.5">WORKING ON</h3>
</div>
<p className="text-xs sm:text-sm text-[#8E8E88] leading-relaxed">
              What you&apos;re building right now. Your active repositories, current architectures, shipped PRs, and weekly focus.
            </p>
</div>
<div className="p-3.5 rounded-xl bg-black/50 border border-white/5 font-mono text-xs text-[#b6b6b0]">
<span className="text-[#7d7d77] block text-[10px] mb-1 uppercase">Live trace example</span>
            &quot;Fine-tuning 4-bit SLMs for private codebase orchestration and local CLI tooling.&quot;
          </div>
</div>
{/* Signal 2 */}
<div className="p-7 rounded-3xl bg-[#0e1010] border border-white/10 space-y-4 hover:border-white/20 transition-all flex flex-col justify-between">
<div className="space-y-3">
<div className="inline-flex p-2.5 rounded-xl bg-[#7b72e9]/10 text-[#7b72e9] border border-[#7b72e9]/20">
<span className="material-symbols-outlined text-2xl">handshake</span>
</div>
<div>
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">SIGNAL 02</div>
<h3 className="text-2xl font-display uppercase tracking-wide text-white mt-0.5">CAN HELP WITH</h3>
</div>
<p className="text-xs sm:text-sm text-[#8E8E88] leading-relaxed">
              What you know and where you can be useful. Specific technical leverage, pairing areas, GPU profiling, and advisory boundaries.
            </p>
</div>
<div className="p-3.5 rounded-xl bg-black/50 border border-white/5 font-mono text-xs text-[#b6b6b0]">
<span className="text-[#7d7d77] block text-[10px] mb-1 uppercase">Live trace example</span>
            &quot;vLLM inference optimization, CUDA memory leak debugging, distributed shard routing.&quot;
          </div>
</div>
{/* Signal 3 */}
<div className="p-7 rounded-3xl bg-[#0e1010] border border-white/10 space-y-4 hover:border-white/20 transition-all flex flex-col justify-between">
<div className="space-y-3">
<div className="inline-flex p-2.5 rounded-xl bg-[#7b72e9]/10 text-[#7b72e9] border border-[#7b72e9]/20">
<span className="material-symbols-outlined text-2xl">radar</span>
</div>
<div>
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">SIGNAL 03</div>
<h3 className="text-2xl font-display uppercase tracking-wide text-white mt-0.5">LOOKING FOR</h3>
</div>
<p className="text-xs sm:text-sm text-[#8E8E88] leading-relaxed">
              What you need, who you want to meet, or what you&apos;re trying to solve. Auto-expiring 7-day beacons for co-founders and design partners.
            </p>
</div>
<div className="p-3.5 rounded-xl bg-black/50 border border-white/5 font-mono text-xs text-[#b6b6b0]">
<span className="text-[#7d7d77] block text-[10px] mb-1 uppercase">Auto-expiring beacon</span>
            &quot;Seeking 3 design partners deploying autonomous agents into customer production workflows.&quot;
          </div>
</div>
</div>
{/* Anchor message banner */}
<div className="p-4 rounded-xl bg-[#121413] border border-white/10 text-center font-mono text-xs text-[#a0a09a]">
        ⚡ <span className="text-white font-medium">These aren&apos;t permanent profile fields.</span> They&apos;re signals that change as your work changes.
      </div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 05 — AGENT-NATIVE DISCOVERY */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="agent-discovery" id="discovery">
<div className="space-y-8">
{/* Transition Eyebrow */}
<div className="space-y-2">
<div className="text-xs font-mono text-[#a0a09a]">And once people have these profiles, something interesting happens.</div>
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 04 AGENT-NATIVE DISCOVERY"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          FIND PEOPLE iN the RIGHT MOMENT they are in</h2>
<p className="text-sm sm:text-base text-[#a0a09a] max-w-3xl leading-relaxed">
          Keyword matching tells you who listed a skill on a static resume. Zynd enables semantic intent matching that returns engineers who are active in that domain right now.
        </p>
</div>
{/* Interactive / Realistic Simulated Query Box */}
<div className="rounded-3xl bg-[#0e1010] border border-white/15 p-6 sm:p-9 space-y-6 shadow-2xl">
{/* Query prompt bar */}
<div className="space-y-2">
<div className="text-[10px] font-mono text-[#7d7d77] uppercase tracking-wider">NATURAL LANGUAGE AGENT PROMPT</div>
<div className="p-4 rounded-xl bg-[#080909] border border-[#7b72e9]/30 flex items-start gap-3 font-mono text-xs sm:text-sm text-white">
<span className="text-[#7b72e9] font-bold text-base">❯</span>
<Typewriter
  className="flex-1 min-w-0"
  text={'"Find me someone in Bangalore building AI agents who knows Rust and distributed systems."'}
/>
</div>
</div>
{/* Output parsing trace */}
<div className="space-y-3">
<div className="flex items-center justify-between text-[11px] font-mono text-[#7d7d77]">
<span className="">ZYND PROTOCOL REASONING TRACE</span>
<span className="text-emerald-400 flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> 2 EXACT MATCHES LOCATED</span>
</div>
{/* Matched candidates */}
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
{/* Candidate 1 */}
<div className="p-5 rounded-2xl bg-[#121413] border border-white/10 space-y-3">
<div className="flex items-center justify-between">
<div>
<div className="font-bold text-white text-sm">Ananya Rao</div>
<div className="text-[11px] font-mono text-[#7b72e9]">zynd.me/@ananya · Bangalore</div>
</div>
<span className="text-[10px] font-mono text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded">Active today</span>
</div>
<div className="text-xs text-[#d7d7d1] space-y-1">
<div className="text-[11px] font-mono text-[#7d7d77] uppercase">Why Zynd matched:</div>
<p className="leading-relaxed">Building local LLM quantization runtimes in Rust. Actively looking for distributed benchmarking pairing.</p>
</div>
<div className="pt-2 border-t border-white/[0.06] flex items-center justify-between">
<span className="text-[10px] font-mono text-[#7d7d77]">GitHub verified</span>
<span className="text-xs font-mono text-[#7b72e9] hover:underline cursor-pointer">📅 Book 20m Intro →</span>
</div>
</div>
{/* Candidate 2 */}
<div className="p-5 rounded-2xl bg-[#121413] border border-white/10 space-y-3">
<div className="flex items-center justify-between">
<div>
<div className="font-bold text-white text-sm">Karthik Dev</div>
<div className="text-[11px] font-mono text-[#7b72e9]">zynd.me/@karthik · Bangalore</div>
</div>
<span className="text-[10px] font-mono text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded">Active 2h ago</span>
</div>
<div className="text-xs text-[#d7d7d1] space-y-1">
<div className="text-[11px] font-mono text-[#7d7d77] uppercase">Why Zynd matched:</div>
<p className="leading-relaxed">Architecting distributed GPU clusters for agent harnesses. Offers help with memory-mapped tensor streaming.</p>
</div>
<div className="pt-2 border-t border-white/[0.06] flex items-center justify-between">
<span className="text-[10px] font-mono text-[#7d7d77]">Verified repositories</span>
<span className="text-xs font-mono text-[#7b72e9] hover:underline cursor-pointer">📅 Book 20m Intro →</span>
</div>
</div>
</div>
</div>
{/* Transition caption */}
<div className="pt-3 border-t border-white/[0.08] flex items-center justify-between text-xs font-mono text-[#a0a09a]">
<span className="">Oh. Zynd isn&apos;t just your profile. <span className="text-white font-bold">It&apos;s a network.</span></span>
<a className="text-[#7b72e9] hover:underline" href="#network">View the Network Layer ↓</a>
</div>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 06 — THE COMPOUNDING NETWORK */}
{/* ========================================================================= */}

{/* ========================================================================= */}
{/* SECTION 07 — ZERO MAINTENANCE DEBT (STAY CURRENT) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="zero-maintenance">
<div className="rounded-3xl bg-[#0e1010] border border-white/10 p-7 sm:p-11 lg:p-14">
<div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
{/* Left 6 cols */}
<div className="lg:col-span-6 space-y-6">
<div className="space-y-2">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 06 ZERO MAINTENANCE DEBT"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
              You shouldn&apos;t have to update your profile. Your AI already knows what you&apos;re working on.
            </h2>
<p className="text-xs sm:text-sm font-mono text-[#7b72e9]">
              Claude / ChatGPT / Cursor / GitHub → Zynd. Your work changes. Your profile changes with it.
            </p>
</div>
{/* 3 Clear Pillars */}
<div className="space-y-3.5 pt-1">
<div className="p-4 rounded-xl bg-[#121413] border border-white/[0.08] space-y-1">
<div className="text-xs font-mono text-[#7b72e9] font-bold">01 / Zero Manual Bio Writing</div>
<p className="text-xs text-[#8E8E88]">Shipped work becomes the signal. No drafting intros or updating skill badges every six months.</p>
</div>
<div className="p-4 rounded-xl bg-[#121413] border border-white/[0.08] space-y-1">
<div className="text-xs font-mono text-[#7b72e9] font-bold">02 / Auto-Expiring Requests</div>
<p className="text-xs text-[#8E8E88]">Needs and beacons automatically expire after 7 days, eliminating stale ghost requests from previous quarters.</p>
</div>
<div className="p-4 rounded-xl bg-[#121413] border border-white/[0.08] space-y-1">
<div className="text-xs font-mono text-[#7b72e9] font-bold">03 / 100% First-Party Control</div>
<p className="text-xs text-[#8E8E88]">You approve what gets published. Private code, private repos, and local context never leave your sovereignty.</p>
</div>
</div>
</div>
{/* Right 6 cols: Live Telemetry Feed */}
<div className="lg:col-span-6">
<div className="p-6 rounded-2xl bg-[#080909] border border-white/10 font-mono text-xs space-y-4 shadow-xl">
<div className="flex items-center justify-between text-[11px] text-[#7d7d77] border-b border-white/[0.08] pb-3">
<span className="flex items-center gap-2 text-white font-medium">
<span className="w-2 h-2 rounded-full bg-emerald-400"></span>
                ACTIVE TELEMETRY STREAM
              </span>
<span className="text-[#7b72e9]">VERIFIED SYNC</span>
</div>
<div className="space-y-3">
{/* Event 1 */}
<div className="p-3.5 rounded-lg bg-[#121413] border border-white/[0.05] space-y-1">
<div className="flex items-center justify-between text-[10px] text-[#7d7d77]">
<span className="">CURSOR / GIT COMMIT · 12m ago</span>
<span className="text-[#7b72e9]">SIGNAL EXTRACTED</span>
</div>
<div className="text-white text-xs">chandan/agent-protocol: added multi-model router tests</div>
<div className="text-[10px] text-emerald-400">✓ Signal updated: Working On</div>
</div>
{/* Event 2 */}
<div className="p-3.5 rounded-lg bg-[#121413] border border-white/[0.05] space-y-1">
<div className="flex items-center justify-between text-[10px] text-[#7d7d77]">
<span className="">GITHUB PR #42 · 1d ago</span>
<span className="text-emerald-400">MERGED</span>
</div>
<div className="text-white text-xs">&quot;GPU memory profiling under heavy context workloads&quot;</div>
<div className="text-[10px] text-[#8b8b85]">✓ Signal refreshed: Can Help With</div>
</div>
{/* Event 3 */}
<div className="p-3.5 rounded-lg bg-[#121413] border border-white/[0.05] space-y-1">
<div className="flex items-center justify-between text-[10px] text-[#7d7d77]">
<span className="">7-DAY BEACON TIMEOUT · 7d reached</span>
<span className="text-amber-400">EXPIRED</span>
</div>
<div className="text-white text-xs">Request &quot;Looking for Redis pairing&quot; auto-retired</div>
<div className="text-[10px] text-[#8b8b85]">✓ Beacon cleared: Stale request avoided</div>
</div>
</div>
</div>
</div>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 08 — DUAL INTERFACE (HUMAN <-> AGENT) */}
  {/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="dual-interface" id="dual-view">
<div className="space-y-10">
<div className="text-center max-w-2xl mx-auto space-y-3">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 07 DUAL INTERFACE"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          One identity. Two audiences.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a]">
          Built for people to read. Structured for agents to understand.
        </p>
</div>
{/* Side-by-Side Split View */}
<div className="grid grid-cols-1 lg:grid-cols-2 gap-7">
{/* Left: Human View */}
<div className="p-6 sm:p-8 rounded-3xl bg-[#0e1010] border border-white/15 space-y-5">
<div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
<span className="text-xs font-mono font-bold text-white flex items-center gap-2">
<span className="material-symbols-outlined text-sm text-[#7b72e9]">person</span>
              HUMAN INTERFACE
            </span>
<span className="text-[10px] font-mono text-[#8b8b85]">zynd.me/@chandan</span>
</div>
{/* Editorial card */}
<div className="p-5 rounded-2xl bg-[#121413] border border-white/[0.08] space-y-4">
<div className="flex items-center justify-between">
<div>
<h4 className="font-bold text-white text-base">Chandan Kumar</h4>
<div className="text-xs text-[#a0a09a]">Founding Engineer &amp; Distributed Systems</div>
</div>
<span className="text-xs font-mono bg-[#7b72e9] text-black font-semibold px-3 py-1 rounded-full cursor-pointer">Book Intro</span>
</div>
<div className="space-y-2 text-xs">
<div className="text-[#d7d7d1]">
<span className="text-[#7b72e9] font-mono text-[10px] uppercase block">Working On:</span>
                &quot;Agent-native discovery protocols and schema validators.&quot;
              </div>
<div className="text-[#8E8E88]">
<span className="text-[#9c9c96] font-mono text-[10px] uppercase block">Can Help With:</span>
                &quot;AI agent architecture · Distributed systems · Rust concurrency&quot;
              </div>
</div>
<div className="flex flex-wrap gap-2 text-[10px] font-mono text-[#7d7d77] pt-1">
<span className="bg-black/50 px-2 py-0.5 rounded border border-white/5">Rust</span>
<span className="bg-black/50 px-2 py-0.5 rounded border border-white/5">Python</span>
<span className="bg-black/50 px-2 py-0.5 rounded border border-white/5">Distributed Systems</span>
</div>
</div>
<p className="text-xs text-[#8E8E88] font-mono">
            Designed for scanability: human founders, collaborators, and hiring leads instantly understand active momentum.
          </p>
</div>
{/* Right: Agent View */}
<div className="p-6 sm:p-8 rounded-3xl bg-[#080909] border border-white/15 space-y-5">
<div className="flex items-center justify-between border-b border-white/[0.08] pb-4">
<span className="text-xs font-mono font-bold text-[#7b72e9] flex items-center gap-2">
<span className="material-symbols-outlined text-sm">terminal</span>
              AGENT INTERFACE (JSON-LD / LLMS.TXT)
            </span>
<span className="text-[10px] font-mono text-[#8b8b85]">application/json</span>
</div>
{/* JSON schema format */}
<pre className="p-4 rounded-2xl bg-[#0e1010] border border-white/10 text-[11px] font-mono text-[#bfbfb9] overflow-x-auto leading-relaxed"><code>{`{
  "@context": "https://schema.org",
  "@type": "LivingProfile",
  "handle": "chandan",
  "status": "active_this_week",
  "signals": {
    "working_on": "Agent-native discovery protocol",
    "can_help_with": [
      "AI agent architecture",
      "Distributed systems"
    ],
    "looking_for": "Local LLM harness engineers",
    "beacon_expires_at": "2026-04-01T00:00:00Z"
  },
  "verified_sources": ["github", "linkedin", "x"]
}`}</code></pre>
<p className="text-xs text-[#8E8E88] font-mono">
            Exposes semantic vectors indexable by Claude, OpenAI, and custom autonomous agents matching high-leverage opportunities.
          </p>
</div>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 09 — PRIVACY & SOVEREIGN CONTROL */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="privacy-boundaries" id="privacy">
<div className="space-y-8">
<div className="max-w-3xl space-y-2">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 08 SOVEREIGN CONTROL"}</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          You control what your identity says.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a]">
          Clear, unbreakable boundaries. Your work remains 100% your own.
        </p>
</div>
{/* 4-point card grid */}
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
{/* Card 1 */}
<div className="p-6 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-3">
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">01 // PUBLISHED</div>
<h3 className="font-bold text-white text-base">What Gets Published</h3>
<p className="text-xs text-[#8E8E88] leading-relaxed">
            Your 3 active living signals, your public handle, and links to your verified public traces.
          </p>
<ul className="text-[11px] font-mono text-[#a0a09a] space-y-1 pt-1">
<li className="">• Working on signal</li>
<li className="">• Can help with topics</li>
<li className="">• 7-day beacons</li>
</ul>
</div>
{/* Card 2 */}
<div className="p-6 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-3">
<div className="text-[10px] font-mono text-rose-400 uppercase tracking-wider">02 // PRIVATE</div>
<h3 className="font-bold text-white text-base">What Stays Private</h3>
<p className="text-xs text-[#8E8E88] leading-relaxed">
            Raw source code, private repositories, local prompt logs, and personal contact details are never exposed.
          </p>
<ul className="text-[11px] font-mono text-[#a0a09a] space-y-1 pt-1">
<li className="">• Private repositories</li>
<li className="">• Editor &amp; prompt logs</li>
<li className="">• Phone &amp; private email</li>
</ul>
</div>
{/* Card 3 */}
<div className="p-6 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-3">
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">03 // AI SYNC</div>
<h3 className="font-bold text-white text-base">What Your AI Updates</h3>
<p className="text-xs text-[#8E8E88] leading-relaxed">
            Only explicitly authorized contexts. Changes appear in preview first; revoke authorization in one click.
          </p>
<ul className="text-[11px] font-mono text-[#a0a09a] space-y-1 pt-1">
<li className="">• Shipped release notes</li>
<li className="">• Public PR summaries</li>
<li className="">• 1-click token revoke</li>
</ul>
</div>
{/* Card 4 */}
<div className="p-6 rounded-2xl bg-[#0e1010] border border-white/[0.08] space-y-3">
<div className="text-[10px] font-mono text-[#7b72e9] uppercase tracking-wider">04 // DISCOVERY</div>
<h3 className="font-bold text-white text-base">What Agents Discover</h3>
<p className="text-xs text-[#8E8E88] leading-relaxed">
            Controlled semantic metadata only. Agents can match relevance and request an intro without bulk scraping.
          </p>
<ul className="text-[11px] font-mono text-[#a0a09a] space-y-1 pt-1">
<li className="">• Structured intent signals</li>
<li className="">• Relevance explanations</li>
<li className="">• Rate-limited queries</li>
</ul>
</div>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 10 — FOUNDING 25 (EARLY NETWORK FORMATION) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="founding-network">
<div className="p-8 sm:p-12 lg:p-14 rounded-3xl bg-[#0e1010] border border-[#7b72e9]/40 space-y-8 text-center relative overflow-hidden shadow-[0_0_40px_rgba(123,114,233,0.08)]">
<div className="inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-[#7b72e9] bg-[#7b72e9]/10 border border-[#7b72e9]/25 px-4 py-1.5 rounded-full">
<span className="">BATCH 01 // EARLY NETWORK FORMATION</span>
</div>
<div className="space-y-4 max-w-2xl mx-auto">
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
          We&apos;re building the first layer of the network with 25 people.
        </h2>
<p className="text-sm sm:text-base text-[#a0a09a] leading-relaxed">
          We&apos;re not trying to create another directory with 10 million empty profiles. We&apos;re starting with people who are actually building.
        </p>
</div>
{/* Scarcity indicator & Member initials */}
<div className="max-w-md mx-auto space-y-4">
<div className="p-4 rounded-xl bg-black/60 border border-white/10 flex items-center justify-between text-xs font-mono">
<span className="text-[#a0a09a]">Founding Network Status:</span>
<span className="text-[#7b72e9] font-bold">17 / 25 spots claimed</span>
</div>
{/* Micro avatars of claimed spots */}
<div className="flex items-center justify-center -space-x-2 pt-1">
<span className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-[#080909] text-white flex items-center justify-center text-[10px] font-mono font-bold">CK</span>
<span className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-[#080909] text-white flex items-center justify-center text-[10px] font-mono font-bold">AR</span>
<span className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-[#080909] text-white flex items-center justify-center text-[10px] font-mono font-bold">KD</span>
<span className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-[#080909] text-white flex items-center justify-center text-[10px] font-mono font-bold">SB</span>
<span className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-[#080909] text-white flex items-center justify-center text-[10px] font-mono font-bold">LN</span>
<span className="w-8 h-8 rounded-full bg-[#1c2214] border-2 border-[#080909] text-[#7b72e9] flex items-center justify-center text-[10px] font-mono font-bold">+12</span>
</div>
</div>
<div>
<a className="inline-flex items-center gap-2 bg-[#7b72e9] hover:bg-[#a78bfa] text-black font-mono font-bold text-sm py-4 px-8 rounded-xl active:scale-95 transition-all shadow-[0_0_25px_rgba(123,114,233,0.35)]" href="#ingestion">
<span className="">Apply for Founding Network</span>
<span className="text-base leading-none">→</span>
</a>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 11 — FAQ (6 DIRECT QUESTIONS) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8" data-purpose="faq">
<div className="space-y-8">
<div className="text-center max-w-xl mx-auto space-y-2">
<div className="text-xs font-mono text-[#7b72e9] tracking-widest uppercase">{"// 10 KNOWLEDGE BASE"}</div>
<h2 className="font-display uppercase text-3xl sm:text-4xl font-normal text-white">
          Clear, honest answers.
        </h2>
</div>
<div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
{/* Q1 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">What is a Zynd profile?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            A Zynd profile is a living identity card built for modern technical builders. Instead of a static resume or list of links, it distills what you are working on right now, what you can help with, and what you are looking for—legible to both people and AI agents.
          </p>
</details>
{/* Q2 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">Do I need to manually create it?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            No. You paste your GitHub handle or LinkedIn URL. Zynd ingests the public evidence, parses your technical focus in 60 seconds, and presents a completed living draft for you to review or edit.
          </p>
</details>
{/* Q3 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">Can AI agents actually search my profile?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            Yes. Zynd exposes structured JSON-LD and semantic llms.txt endpoints. When someone asks their AI &quot;who is building local quantization runtimes in Rust?&quot;, the agent can query Zynd&apos;s protocol and surface you with exact reasoning.
          </p>
</details>
{/* Q4 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">What can my AI update?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            Only what you authorize. When you link Cursor, GitHub, or an LLM harness, Zynd refreshes your active tags and project summaries based on real commits and public releases. You retain full preview and 1-click revocation at all times.
          </p>
</details>
{/* Q5 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">Is my profile public?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            Your living signals and public links are accessible via your custom handle (zynd.me/@you). However, your private code, local IDE buffers, and personal contact details remain private and are never indexed.
          </p>
</details>
{/* Q6 */}
<details className="group p-5 rounded-2xl bg-[#0e1010] border border-white/[0.08] transition-all open:border-white/20">
<summary className="font-semibold text-white text-sm sm:text-base flex items-center justify-between cursor-pointer list-none">
<span className="">Who is Zynd for?</span>
<span className="text-[#7b72e9] transition-transform group-open:rotate-45 font-mono text-xl">+</span>
</summary>
<p className="text-xs sm:text-sm leading-relaxed text-[#8E8E88] pt-3 border-t border-white/[0.06] mt-3">
            Engineers, researchers, technical founders, and builders who ship active code. If your career moves faster than a yearly resume update, Zynd keeps the world in sync with your real work.
          </p>
</details>
</div>
</div>
</section>
{/* ========================================================================= */}
{/* SECTION 12 — FINAL CALL TO ACTION (THE COMPLETE LOOP) */}
{/* ========================================================================= */}
<section className="max-w-[1200px] mx-auto px-4 sm:px-6 lg:px-8 pt-4" data-purpose="final-cta">
<div className="p-8 sm:p-14 rounded-3xl bg-gradient-to-b from-[#121413] to-[#080909] border border-white/15 space-y-6 text-center shadow-2xl">
<div className="text-xs font-mono text-[#7b72e9] uppercase tracking-widest">CLAIM YOUR LIVING HANDLE</div>
<h2 className="font-display uppercase text-3xl sm:text-5xl font-normal text-white leading-tight">
        Your AI knows what you&apos;re building. <br />
<span className="text-[#7b72e9]">Make it discoverable.</span>
</h2>
<p className="text-xs sm:text-sm font-mono text-[#a0a09a] max-w-lg mx-auto">
        Create → become discoverable → discover others → stay current.
      </p>
{/* Input field + CTA */}
<div className="max-w-md mx-auto space-y-3 pt-2">
<div className={`flex items-center bg-[#080909] border rounded-xl px-4 py-3.5 transition-colors ${
  handleStatus === "available" ? "border-emerald-500" :
  handleStatus === "taken" ? "border-red-500" :
  handleStatus === "error" ? "border-amber-500/60" :
  "border-white/20 focus-within:border-[#7b72e9]"
}`}>
<span className="text-xs font-mono text-[#7d7d77] select-none pr-1 whitespace-nowrap">zynd.ai/p/</span>
<input
  className="w-full bg-transparent border-none p-0 text-sm font-mono text-white placeholder:text-[#52524c] focus:ring-0 focus:outline-none"
  placeholder="your-handle"
  type="text"
  value={handle}
  onChange={e => onHandleInput(e.target.value)}
  onKeyDown={e => { if (e.key === "Enter") claimHandle(); }}
  autoComplete="off"
  spellCheck="false"
/>
{handleStatus === "checking" && <span className="text-[10px] font-mono text-[#7d7d77] ml-2 shrink-0">checking…</span>}
{handleStatus === "available" && <span className="text-[10px] font-mono text-emerald-400 ml-2 shrink-0">✓ available</span>}
{handleStatus === "taken" && <span className="text-[10px] font-mono text-red-400 ml-2 shrink-0">✗ taken</span>}
{handleStatus === "error" && <span className="text-[10px] font-mono text-amber-400 ml-2 shrink-0">can&apos;t verify</span>}
</div>
{handleStatus === "taken" ? (
  <div className="text-center text-xs font-mono text-red-400 py-1">That handle is taken — try another one.</div>
) : (
  <button
    type="button"
    disabled={handle.length < 2 || handleStatus === "checking"}
    onClick={claimHandle}
    className="block w-full bg-[#7b72e9] hover:bg-[#a78bfa] disabled:opacity-40 disabled:cursor-not-allowed text-black font-mono font-bold text-sm py-4 px-6 rounded-xl active:scale-95 transition-all shadow-[0_0_25px_rgba(123,114,233,0.3)]"
  >
    {handle.length >= 2 && handleStatus === "available"
      ? `Claim zynd.ai/p/${handle} →`
      : handle.length >= 2 && handleStatus === "error"
      ? `Claim zynd.ai/p/${handle} →`
      : "Create your Living Profile →"}
  </button>
)}
</div>
{/* Trust items */}
<div className="flex flex-wrap items-center justify-center gap-6 text-xs font-mono text-[#7d7d77] pt-3">
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">●</span> Free to create</span>
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">●</span> Own your identity</span>
<span className="flex items-center gap-1.5"><span className="text-[#7b72e9]">●</span> Full privacy control</span>
</div>
</div>
</section>
</main>
{/* BEGIN: Footer */}
<footer className="border-t border-white/[0.08] bg-[#060707] py-14 px-4 sm:px-6 lg:px-8" data-purpose="site-footer">
<div className="max-w-[1200px] mx-auto space-y-10">
<div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
<div className="space-y-2">
<div className="flex items-center gap-2.5">
<img src="/assets/zynd-logo.png" alt="Zynd" className="h-6 w-auto opacity-70" style={{filter: "brightness(0) invert(1)"}} />
<span className="text-sm font-semibold text-white opacity-70">Zynd</span>
</div>
<p className="text-xs text-[#7d7d77] font-mono max-w-md">
          The living professional identity for technical builders and AI agents. Synthesizing digital footprints into sovereign, discoverable assets.
        </p>
</div>
{/* Footer navigation links */}
<div className="flex flex-wrap gap-7 text-xs font-mono text-[#8E8E88]">
<a className="hover:text-white transition-colors" href="#">Manifesto</a>
<a className="hover:text-white transition-colors" href="#">Discovery Index</a>
<a className="hover:text-white transition-colors" href="#">Agent Specs</a>
<a className="hover:text-white transition-colors" href="#">Privacy</a>
<a className="hover:text-white transition-colors" href="#">Terms</a>
</div>
</div>
{/* Copyright and status bar */}
<div className="border-t border-white/[0.06] pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-mono text-[#6b6b65]">
<div className="">© 2026 ZYND INC. ALL RIGHTS RESERVED.</div>
<div className="flex items-center gap-2 text-emerald-400">
<span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
<span className="">NETWORK OPERATIONAL</span>
</div>
</div>
</div>
</footer>
{/* END: Footer */}
    </>
  );
}
