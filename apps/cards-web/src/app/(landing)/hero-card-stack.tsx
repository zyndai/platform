"use client";

import { useEffect, useState } from "react";

/**
 * Hero card stack — ported from the `Zynd Hero.dc.html` design canvas.
 *
 * A stack of living-profile cards deals itself off to the right one at a
 * time; once the stage is empty the whole stack reassembles with a staggered
 * delay and the loop restarts. Hovering holds the current frame.
 *
 * Card visuals follow this page's palette (#7b72e9 accent) rather than the
 * canvas file's, so the stack reads as part of the hero.
 */

type Profile = {
  initials: string;
  name: string;
  handle: string;
  working: string;
  help: string;
  looking: string;
  expires: string;
  updated: string;
};

const PROFILES: Profile[] = [
  {
    initials: "CK", name: "Chandan Kumar", handle: "zynd.me/@chandan",
    working: "Agent-native professional discovery protocol & schema parser in Rust",
    help: "AI agent architectures · Distributed systems · High-throughput vector search",
    looking: "Engineers building local LLM harnesses & early design partners",
    expires: "Expires in 5d", updated: "Updated 8m ago via GitHub traces",
  },
  {
    initials: "MO", name: "Maya Okafor", handle: "zynd.me/@maya",
    working: "Conflict-free replication engine for multiplayer design tools",
    help: "Rust · WASM · CRDTs · Realtime sync",
    looking: "Teams shipping collaborative editors this quarter",
    expires: "Expires in 9d", updated: "Updated 12m ago via commit traces",
  },
  {
    initials: "DM", name: "Diego Marín", handle: "zynd.me/@diego",
    working: "Open evaluation harness for retrieval pipelines",
    help: "Eval design · Retrieval · Python · Benchmarking",
    looking: "Teams with messy internal search to benchmark against",
    expires: "Expires in 4d", updated: "Updated 3m ago via paper traces",
  },
  {
    initials: "AR", name: "Aisha Rahman", handle: "zynd.me/@aisha",
    working: "Latency budgets for on-device speech models",
    help: "Edge inference · CoreML · Audio DSP",
    looking: "Hardware partners for a wearable listening prototype",
    expires: "Expires in 12d", updated: "Updated 21m ago via LinkedIn traces",
  },
  {
    initials: "TF", name: "Tomás Feliu", handle: "zynd.me/@tomas",
    working: "A type system for agent tool schemas",
    help: "TypeScript · Compilers · Developer tooling",
    looking: "Maintainers who want typed, verifiable tool specs",
    expires: "Expires in 7d", updated: "Updated 1h ago via GitHub traces",
  },
];

const N = PROFILES.length;
const DWELL = 1900;        // how long each card holds the front
const SPREAD = 14;         // vertical px between stacked sheets
const EMPTY_HOLD = 850;    // beat on the empty stage before reassembling
const REASSEMBLE_EXTRA = 900;

// Hand-stacked look: each sheet below sits a little off-square.
const SKEW = [0, -1.15, 0.9, -0.7, 1.3, -0.5];
const SHIFT = [0, 7, -9, 5, -6, 8];

function cardStyle(i: number, step: number, reassembling: boolean): React.CSSProperties {
  const d = i - step;
  const base: React.CSSProperties = {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    height: "510px",
    transformOrigin: "50% 100%",
    willChange: "transform, opacity",
    transition:
      "transform 900ms cubic-bezier(.22,.9,.24,1), opacity 700ms ease, filter 900ms ease",
  };

  // Already dealt away — off to the right.
  if (d < 0) {
    return {
      ...base,
      transform: "translate3d(125%, -6%, 0) rotate(7deg) scale(0.96)",
      opacity: 0,
      zIndex: 200 + i,
      filter: "brightness(1)",
      transitionDelay: "0ms",
    };
  }

  return {
    ...base,
    transform:
      `translate3d(${SHIFT[d % SHIFT.length] * (d ? 1 : 0)}px, ${d * SPREAD}px, 0)` +
      ` rotate(${SKEW[d % SKEW.length]}deg)` +
      ` scale(${1 - d * 0.012})`,
    opacity: d > 4 ? 0 : 1,
    zIndex: 100 - d,
    // The wrapper peeks out below the card above it: that sliver is the "page edge".
    borderRadius: "20px",
    background: d === 0 ? "transparent" : "#20202a",
    boxShadow: d === 0 ? "none" : "0 0 0 1px #3d3d49, 0 20px 30px -22px rgba(0,0,0,0.95)",
    filter: `brightness(${1 - Math.min(d, 4) * 0.07})`,
    transitionDelay: reassembling ? `${(N - 1 - d) * 90}ms` : "0ms",
  };
}

export function HeroCardStack() {
  // step === N means every card has been dealt away (empty stage).
  const [step, setStep] = useState(0);
  const [reassembling, setReassembling] = useState(false);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const delay =
      step === N ? EMPTY_HOLD
      : step === 0 && reassembling ? DWELL + REASSEMBLE_EXTRA
      : DWELL;
    const t = setTimeout(() => {
      const next = step >= N ? 0 : step + 1;
      setReassembling(next === 0);
      setStep(next);
    }, delay);
    return () => clearTimeout(t);
  }, [step, reassembling, paused]);

  const active = Math.min(step, N - 1);
  const front = step >= N ? N : step + 1;

  return (
    <div className="flex flex-col gap-5 min-w-0">
      <div
        className="relative"
        style={{ height: "570px", perspective: "1400px" }}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {PROFILES.map((p, i) => (
          <div key={p.handle} style={cardStyle(i, step, reassembling)}>
            <ProfileCard profile={p} />
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-4 px-1">
        <span className="font-mono text-[11px] tracking-widest uppercase text-[#6e6e78]">
          {String(front).padStart(2, "0")} / {String(N).padStart(2, "0")} living profiles
        </span>
        <div className="flex gap-1.5">
          {PROFILES.map((p, i) => (
            <span
              key={p.handle}
              className="block h-[7px] rounded-full"
              style={{
                width: i === active ? "18px" : "7px",
                background: i === active ? "#7b72e9" : "#2c2c33",
                transition: "width 400ms ease, background 400ms ease",
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function ProfileCard({ profile }: { profile: Profile }) {
  return (
    <div className="absolute inset-0 rounded-2xl bg-[#0e1010] border border-white/15 p-6 sm:p-7 flex flex-col gap-5 shadow-2xl overflow-hidden">
      {/* Card Header */}
      <div className="flex items-start justify-between border-b border-white/[0.08] pb-4">
        <div className="flex items-center gap-3.5 min-w-0">
          <div className="w-12 h-12 shrink-0 rounded-xl bg-gradient-to-br from-zinc-800 to-zinc-900 border border-white/15 flex items-center justify-center text-white font-mono font-bold text-lg shadow-inner">
            {profile.initials}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h3 className="font-sans font-bold text-white text-base whitespace-nowrap">{profile.name}</h3>
              <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" title="Active this week"></span>
            </div>
            <div className="text-xs font-mono text-[#7b72e9]">{profile.handle}</div>
          </div>
        </div>
        <span className="shrink-0 text-[10px] font-mono px-2.5 py-1 rounded-full bg-white/[0.06] text-[#b6b6b0] border border-white/10">
          LIVING PROFILE
        </span>
      </div>

      {/* Dynamic 3 Signals Inside Card */}
      <div className="flex flex-col gap-3 flex-1 text-xs font-sans">
        <div className="p-3 rounded-xl bg-[#121413] border border-white/[0.07] space-y-1">
          <div className="font-mono text-[10px] text-[#7b72e9] uppercase tracking-wider flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9]"></span>
            Working On
          </div>
          <p className="text-white font-medium text-xs leading-relaxed">{profile.working}</p>
        </div>
        <div className="p-3 rounded-xl bg-[#121413] border border-white/[0.07] space-y-1">
          <div className="font-mono text-[10px] text-[#9c9c96] uppercase tracking-wider flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#9c9c96]"></span>
            Can Help With
          </div>
          <p className="text-[#d7d7d1] text-xs leading-relaxed">{profile.help}</p>
        </div>
        <div className="p-3 rounded-xl bg-[#121413] border border-[#7b72e9]/30 space-y-1 bg-gradient-to-r from-[#121413] to-[#161c12]">
          <div className="font-mono text-[10px] text-[#7b72e9] uppercase tracking-wider flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#7b72e9] animate-ping"></span>
              Looking For
            </span>
            <span className="text-[9px] text-[#8b8b85] font-mono">{profile.expires}</span>
          </div>
          <p className="text-white font-medium text-xs leading-relaxed">{profile.looking}</p>
        </div>
      </div>

      {/* Card Footer Status */}
      <div className="pt-2 border-t border-white/[0.08] flex items-center justify-between text-[11px] font-mono">
        <span className="text-[#7d7d77] flex items-center gap-1.5">
          <span className="text-[#7b72e9]">●</span> {profile.updated}
        </span>
        <span className="text-white font-medium flex items-center gap-1 text-xs">
          📅 Book 20m Intro
        </span>
      </div>
    </div>
  );
}
