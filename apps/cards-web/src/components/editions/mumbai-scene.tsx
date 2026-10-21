import type { CSSProperties } from "react";
import type { EditionMood } from "@/lib/editions";

/* The Mumbai Builder Week '26 artwork, drawn as SVG so it stays sharp on any
 * screen, recolours per mood without extra image downloads, and is Zynd's own
 * drawing rather than a copy of anyone's event art. Coordinates are in a
 * 1600 x 640 box; the waterline is at y = 520. */

const W = 1600;
const H = 640;
const WATER_Y = 520;
const MOON = { x: 800, y: 228, r: 112 };

interface Palette {
  sky: [string, string, string, string];
  moon: [string, string, string];
  glow: string;
  line: string;
  lineSoft: string;
  skyline: string;
  skylineFar: string;
  windows: string;
  stone: [string, string];
  arch: [string, string];
  water: [string, string];
  crystal: [string, string, string];
}

const PALETTES: Record<EditionMood, Palette> = {
  night: {
    sky: ["#090B2A", "#191B57", "#3A2C86", "#6E4FB8"],
    moon: ["#F2FFFD", "#A9F4EC", "#5FE3D6"],
    glow: "#5FE3D6",
    line: "#7FE9DF",
    lineSoft: "#B59CF2",
    skyline: "#191744",
    skylineFar: "#2C2770",
    windows: "#FFD59A",
    stone: ["#FFE1CC", "#C98FC0"],
    arch: ["#7CF0E4", "#221C5C"],
    water: ["#1E2266", "#080A26"],
    crystal: ["#F4E9FF", "#B59CF2", "#5FE3D6"],
  },
  dusk: {
    sky: ["#1B1347", "#5A2F86", "#C0588F", "#F6A067"],
    moon: ["#FFF8EC", "#FFD6A8", "#F6A067"],
    glow: "#F6A067",
    line: "#FFC59A",
    lineSoft: "#F3A6D0",
    skyline: "#241338",
    skylineFar: "#4A2463",
    windows: "#FFE3A3",
    stone: ["#FFE8D6", "#D98C9E"],
    arch: ["#FFC48F", "#2A1440"],
    water: ["#3A1D57", "#120A26"],
    crystal: ["#FFF1E6", "#F3A6D0", "#F6A067"],
  },
  monsoon: {
    sky: ["#041A24", "#0B3B4B", "#14666E", "#3FA39B"],
    moon: ["#F1FFFC", "#BFF5EA", "#7CE0CF"],
    glow: "#7CE0CF",
    line: "#9FF0E2",
    lineSoft: "#9CC8F2",
    skyline: "#06222C",
    skylineFar: "#0F3E4A",
    windows: "#FFE7B0",
    stone: ["#E7F4EF", "#8FB8C2"],
    arch: ["#A6F5E9", "#08303A"],
    water: ["#0B3A48", "#03141B"],
    crystal: ["#EFFFFB", "#9CC8F2", "#5FE3D6"],
  },
};

/** Colours at the very top of the sky and bottom of the water, for extending
 *  the art past its edges (e.g. a tall phone wallpaper). */
export function sceneEdgeColors(mood: EditionMood): { sky: string; water: string } {
  return { sky: PALETTES[mood].sky[0], water: PALETTES[mood].water[1] };
}

/** Deterministic pseudo-random numbers, so the server and every client draw
 *  the same stars and towers (no hydration mismatch). */
function seeded(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

const STARS = (() => {
  const rand = seeded(26);
  return Array.from({ length: 110 }, (_, i) => ({
    x: rand() * W,
    y: rand() * (WATER_Y - 140),
    r: 0.6 + rand() * 1.5,
    o: 0.35 + rand() * 0.6,
    twinkle: i % 9 === 0,
  }));
})();

interface Tower { x: number; w: number; h: number; far: boolean }

const TOWERS: Tower[] = (() => {
  const rand = seeded(1611);
  const towers: Tower[] = [];
  // Leave the middle open for the Gateway; the far row runs behind it.
  for (const [from, to] of [[0, 610], [990, 1600]] as const) {
    for (let x = from; x < to; ) {
      const w = 18 + rand() * 30;
      const nearGateway = Math.min(Math.abs(x - 610), Math.abs(x - 990)) < 120;
      towers.push({ x, w, h: (nearGateway ? 50 : 70) + rand() * (nearGateway ? 70 : 170), far: false });
      x += w + 4 + rand() * 10;
    }
  }
  for (let x = 0; x < W; ) {
    const w = 22 + rand() * 40;
    towers.push({ x, w, h: 90 + rand() * 150, far: true });
    x += w + rand() * 8;
  }
  return towers;
})();

const CRYSTALS = [
  { x: 190, y: 170, s: 34, d: 0 },
  { x: 330, y: 300, s: 20, d: 1.4 },
  { x: 560, y: 390, s: 13, d: 2.2 },
  { x: 1040, y: 390, s: 13, d: 0.8 },
  { x: 1270, y: 300, s: 22, d: 2.8 },
  { x: 1410, y: 158, s: 38, d: 1.1 },
];

function PetalRing({ count, inner, outer, width }: { count: number; inner: number; outer: number; width: number }) {
  const mid = (inner + outer) / 2;
  const petal = `M0,${-inner} Q${width},${-mid} 0,${-outer} Q${-width},${-mid} 0,${-inner}Z`;
  return (
    <>
      {Array.from({ length: count }, (_, i) => <path key={i} d={petal} transform={`rotate(${(360 / count) * i})`} />)}
    </>
  );
}

function Gateway({ id }: { id: string }) {
  const cx = 800;
  const pointedArch = (left: number, right: number, spring: number, apex: number) => {
    const mid = (left + right) / 2;
    return `M${left},${WATER_Y} V${spring} Q${left},${apex + 10} ${mid},${apex} Q${right},${apex + 10} ${right},${spring} V${WATER_Y}Z`;
  };
  return (
    <g>
      {/* wings, central block and attic */}
      <rect x={cx - 170} y={372} width={340} height={WATER_Y - 372} fill={`url(#${id}-stone)`} />
      <rect x={cx - 92} y={318} width={184} height={60} fill={`url(#${id}-stone)`} />
      <rect x={cx - 100} y={312} width={200} height={8} rx={2} fill={`url(#${id}-stone)`} opacity={0.9} />
      <rect x={cx - 176} y={366} width={352} height={8} rx={2} fill={`url(#${id}-stone)`} opacity={0.9} />
      {/* four turrets with domes */}
      {[-88, -48, 48, 88].map((dx) => (
        <g key={dx}>
          <rect x={cx + dx - 11} y={276} width={22} height={40} fill={`url(#${id}-stone)`} />
          <path d={`M${cx + dx - 14},${278} Q${cx + dx},${246} ${cx + dx + 14},${278}Z`} fill={`url(#${id}-stone)`} />
          <rect x={cx + dx - 1} y={240} width={2} height={10} fill={`url(#${id}-stone)`} />
        </g>
      ))}
      {/* corner pinnacles on the wings */}
      {[-166, 166].map((dx) => (
        <path key={dx} d={`M${cx + dx - 8},${368} L${cx + dx},${340} L${cx + dx + 8},${368}Z`} fill={`url(#${id}-stone)`} />
      ))}
      {/* the arches, lit from the moon behind */}
      <path d={pointedArch(cx - 40, cx + 40, 420, 384)} fill={`url(#${id}-arch)`} />
      <path d={pointedArch(cx - 140, cx - 92, 452, 426)} fill={`url(#${id}-arch)`} />
      <path d={pointedArch(cx + 92, cx + 140, 452, 426)} fill={`url(#${id}-arch)`} />
      {/* attic windows */}
      {[-60, -30, 0, 30, 60].map((dx) => (
        <rect key={dx} x={cx + dx - 6} y={334} width={12} height={22} rx={6} fill={`url(#${id}-arch)`} opacity={0.75} />
      ))}
    </g>
  );
}

function Crystal({ x, y, s, d, id }: { x: number; y: number; s: number; d: number; id: string }) {
  const tall = s * 1.45;
  return (
    <g className="ed-float" style={{ animationDelay: `${-d}s` } as CSSProperties} transform={`translate(${x} ${y})`}>
      <ellipse cx={0} cy={0} rx={s * 1.8} ry={s * 1.8} fill={`url(#${id}-crystal-glow)`} />
      <path d={`M0,${-tall} L${s},0 L0,${tall} L${-s},0Z`} fill={`url(#${id}-crystal)`} />
      <path d={`M0,${-tall} L${-s},0 L0,${tall}Z`} fill="#fff" opacity={0.28} />
      <path d={`M${-s},0 L${s},0`} stroke="#fff" strokeOpacity={0.55} strokeWidth={1} />
      <path d={`M0,${-tall} L0,${tall}`} stroke="#fff" strokeOpacity={0.35} strokeWidth={1} />
    </g>
  );
}

function SeaLink({ color }: { color: string }) {
  const deck = 498;
  const pylons = [1300, 1450];
  return (
    <g stroke={color} strokeLinecap="round" fill="none" opacity={0.75}>
      <path d={`M1170,${deck} L1600,${deck - 6}`} strokeWidth={3} />
      {pylons.map((px) => (
        <g key={px}>
          <path d={`M${px - 10},${deck + 10} L${px},${deck - 108} L${px + 10},${deck + 10}`} strokeWidth={3} />
          {[-1, 1].flatMap((side) =>
            [26, 52, 78, 104].map((dx) => (
              <path key={`${side}-${dx}`} d={`M${px},${deck - 100} L${px + side * dx},${deck - (px - 1170) * 0.014}`} strokeWidth={0.9} strokeOpacity={0.8} />
            )),
          )}
        </g>
      ))}
    </g>
  );
}

export interface MumbaiSceneProps {
  mood: EditionMood;
  /** Unique per scene on the page: gradient and pattern ids are scoped by it. */
  idPrefix: string;
  className?: string;
  style?: CSSProperties;
  /** Crop anchor when the box is a different shape than the art. */
  focus?: "center" | "bottom";
  /** Vertical slice of the art to fit, [top, bottom] in art units; wide
   *  banners use it to keep the whole moon in view. */
  crop?: [number, number];
}

export function MumbaiScene({ mood, idPrefix: id, className, style, focus = "bottom", crop = [0, H] }: MumbaiSceneProps) {
  const p = PALETTES[mood];
  return (
    <svg
      viewBox={`0 ${crop[0]} ${W} ${crop[1] - crop[0]}`}
      preserveAspectRatio={focus === "bottom" ? "xMidYMax slice" : "xMidYMid slice"}
      className={className}
      style={style}
      role="img"
      aria-label="Illustration: Mumbai's skyline and the Gateway of India under a full moon"
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.sky[0]} />
          <stop offset="0.38" stopColor={p.sky[1]} />
          <stop offset="0.7" stopColor={p.sky[2]} />
          <stop offset="0.82" stopColor={p.sky[3]} />
        </linearGradient>
        <radialGradient id={`${id}-moon`} cx="0.42" cy="0.38" r="0.7">
          <stop offset="0" stopColor={p.moon[0]} />
          <stop offset="0.55" stopColor={p.moon[1]} />
          <stop offset="1" stopColor={p.moon[2]} />
        </radialGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0" stopColor={p.glow} stopOpacity="0.55" />
          <stop offset="0.45" stopColor={p.glow} stopOpacity="0.16" />
          <stop offset="1" stopColor={p.glow} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-stone`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.stone[0]} />
          <stop offset="1" stopColor={p.stone[1]} />
        </linearGradient>
        <linearGradient id={`${id}-arch`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.arch[0]} />
          <stop offset="1" stopColor={p.arch[1]} />
        </linearGradient>
        <linearGradient id={`${id}-water`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.water[0]} />
          <stop offset="1" stopColor={p.water[1]} />
        </linearGradient>
        <linearGradient id={`${id}-crystal`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={p.crystal[0]} />
          <stop offset="0.5" stopColor={p.crystal[1]} />
          <stop offset="1" stopColor={p.crystal[2]} />
        </linearGradient>
        <radialGradient id={`${id}-crystal-glow`}>
          <stop offset="0" stopColor={p.crystal[1]} stopOpacity="0.45" />
          <stop offset="1" stopColor={p.crystal[1]} stopOpacity="0" />
        </radialGradient>
        <pattern id={`${id}-windows`} width="9" height="12" patternUnits="userSpaceOnUse">
          <rect x="2" y="3" width="2.4" height="3.2" fill={p.windows} opacity="0.85" />
          <rect x="6" y="8" width="2.4" height="3.2" fill={p.windows} opacity="0.4" />
        </pattern>
      </defs>
      <style>{`
        .ed-float { animation: ed-float 7s ease-in-out infinite; transform-box: fill-box; }
        .ed-twinkle { animation: ed-twinkle 3.6s ease-in-out infinite; }
        @keyframes ed-float { 0%, 100% { translate: 0 0; } 50% { translate: 0 -7px; } }
        @keyframes ed-twinkle { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
        @media (prefers-reduced-motion: reduce) { .ed-float, .ed-twinkle { animation: none; } }
      `}</style>

      <rect width={W} height={WATER_Y} fill={`url(#${id}-sky)`} />
      {STARS.map((s, i) => (
        <circle key={i} cx={s.x} cy={s.y} r={s.r} fill="#fff" opacity={s.o} className={s.twinkle ? "ed-twinkle" : undefined}
          style={s.twinkle ? { animationDelay: `${-(i % 5) * 0.7}s` } : undefined} />
      ))}

      <circle cx={MOON.x} cy={MOON.y} r={MOON.r * 3.4} fill={`url(#${id}-glow)`} />
      <g transform={`translate(${MOON.x} ${MOON.y})`} fill="none" stroke={p.line} strokeWidth={1.3} strokeOpacity={0.5}>
        <PetalRing count={24} inner={128} outer={176} width={14} />
        <g stroke={p.lineSoft} strokeOpacity={0.45}><PetalRing count={36} inner={186} outer={226} width={9} /></g>
        <g strokeOpacity={0.3}><PetalRing count={12} inner={236} outer={296} width={22} /></g>
        <circle r={122} strokeOpacity={0.6} />
        <circle r={181} strokeOpacity={0.35} />
        <circle r={306} strokeDasharray="1.5 9" strokeLinecap="round" strokeWidth={2.2} strokeOpacity={0.55} />
      </g>
      <circle cx={MOON.x} cy={MOON.y} r={MOON.r} fill={`url(#${id}-moon)`} />
      <g fill={p.moon[2]} opacity={0.22}>
        <circle cx={MOON.x - 34} cy={MOON.y - 20} r={16} />
        <circle cx={MOON.x + 28} cy={MOON.y + 30} r={11} />
        <circle cx={MOON.x + 40} cy={MOON.y - 38} r={7} />
      </g>

      {CRYSTALS.map((c) => <Crystal key={`${c.x}-${c.y}`} {...c} id={id} />)}

      {TOWERS.filter((t) => t.far).map((t) => (
        <rect key={`f${t.x}`} x={t.x} y={WATER_Y - t.h} width={t.w} height={t.h} fill={p.skylineFar} opacity={0.55} />
      ))}
      {TOWERS.filter((t) => !t.far).map((t) => (
        <g key={`n${t.x}`}>
          <rect x={t.x} y={WATER_Y - t.h} width={t.w} height={t.h} fill={p.skyline} />
          <rect x={t.x + 3} y={WATER_Y - t.h + 8} width={Math.max(0, t.w - 6)} height={Math.max(0, t.h - 14)} fill={`url(#${id}-windows)`} />
        </g>
      ))}
      <SeaLink color={p.line} />
      <Gateway id={id} />

      <rect y={WATER_Y} width={W} height={H - WATER_Y} fill={`url(#${id}-water)`} />
      {/* moonlight and city lights on the water */}
      <g fill={p.moon[1]}>
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <rect key={i} x={MOON.x - 70 + i * 6} y={WATER_Y + 10 + i * 15} width={140 - i * 12} height={3} rx={1.5} opacity={0.5 - i * 0.06} />
        ))}
      </g>
      <g fill={p.windows} opacity={0.35}>
        {TOWERS.filter((t) => !t.far && t.h > 150).map((t, i) => (
          <rect key={t.x} x={t.x + 2} y={WATER_Y + 8 + (i % 3) * 9} width={t.w * 0.6} height={2} rx={1} />
        ))}
      </g>
    </svg>
  );
}
