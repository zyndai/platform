import type { CSSProperties } from "react";

/* Mumbai Builder Week '26 artwork: Mumbai's skyline and the Bandra-Worli Sea
 * Link at sunrise, palms in the foreground, prism crystals in the sky. Drawn
 * as SVG in code so it stays sharp at any size and is Zynd's own drawing.
 * Coordinates are in a 1600 x 500 box; the waterline is at y = 400. */

const W = 1600;
const H = 500;
const WATER_Y = 400;

export type SkylineTheme = "light" | "dark";

/** Colours of the city, water and foreground for each theme. The light theme
 *  is the sunrise of the card banner; dark is the same city at night. */
const PALETTES = {
  light: {
    far: ["#B7B2EA", "#C9BFEE"], near: ["#8E8FD9", "#A49CDD"], windows: "#FFF1DE",
    water: ["#D7CBF2", "#A6A3E2"], glints: "#FFF0DC", cityGlints: "#FFFFFF",
    deck: "#6E70C2", deckEdge: "#9EA0E0", cables: "#8D8FD8", pylon: "#5A5CB2", piers: "#7577C6",
    palm: "#5B58A8", palmCrown: "#4A4795", boat: "#5B58A8", cabin: "#6C6AB8",
  },
  dark: {
    far: ["#2E2A72", "#25215E"], near: ["#3D3891", "#2C2878"], windows: "#FFD58A",
    water: ["#1C1952", "#0D0B2B"], glints: "#FFD58A", cityGlints: "#FFD58A",
    deck: "#4B47A8", deckEdge: "#6C67C9", cables: "#5D58B8", pylon: "#6F6AD0", piers: "#3B378E",
    palm: "#0E0C2E", palmCrown: "#0A0824", boat: "#0E0C2E", cabin: "#1A1748",
  },
} as const;
type Palette = (typeof PALETTES)[SkylineTheme];

/** Deterministic pseudo-random numbers, so the server and every client draw
 *  the same towers (no hydration mismatch). */
function seeded(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

interface Tower { x: number; w: number; h: number }

function towers(seed: number, from: number, to: number, minH: number, maxH: number, minW: number, maxW: number, gap: number): Tower[] {
  const rand = seeded(seed);
  const list: Tower[] = [];
  for (let x = from; x < to; ) {
    const w = minW + rand() * (maxW - minW);
    // Taller in the middle of each run, like a real skyline's centre of gravity.
    const centre = 1 - Math.abs((x - (from + to) / 2) / ((to - from) / 2));
    list.push({ x, w, h: minH + (0.35 + 0.65 * centre) * rand() * (maxH - minH) });
    x += w + rand() * gap;
  }
  return list;
}

const FAR = towers(26, 250, 1260, 70, 230, 22, 48, 6);
const NEAR = towers(1611, 300, 1180, 50, 200, 18, 40, 14);

// Kept clear of the top-left, where the card's title sits over the sky.
const CRYSTALS = [
  { x: 860, y: 150, s: 20, d: 0.8 },
  { x: 1040, y: 214, s: 16, d: 2 },
  { x: 1296, y: 120, s: 30, d: 2.4 },
  { x: 1528, y: 190, s: 22, d: 1.2 },
];

/** A prism crystal: an octahedron seen slightly from above, so the belt dips
 *  toward the viewer and each face catches the light differently. */
function Crystal({ x, y, s, d, id }: { x: number; y: number; s: number; d: number; id: string }) {
  const top = -s * 1.55;
  const bottom = s * 1.7;
  const belt = s * 0.18;
  return (
    <g className="ed-float" style={{ animationDelay: `${-d}s` }} transform={`translate(${x} ${y})`}>
      <circle r={s * 2.2} fill={`url(#${id}-crystal-glow)`} />
      <path d={`M0,${top} L${-s},0 L0,${belt}Z`} fill="#FFFFFF" />
      <path d={`M0,${top} L${s},0 L0,${belt}Z`} fill={`url(#${id}-crystal-a)`} />
      <path d={`M${-s},0 L0,${bottom} L0,${belt}Z`} fill={`url(#${id}-crystal-b)`} />
      <path d={`M${s},0 L0,${bottom} L0,${belt}Z`} fill={`url(#${id}-crystal-c)`} />
      <path d={`M0,${top} L${s},0 L0,${bottom} L${-s},0Z M${-s},0 L0,${belt} L${s},0 M0,${top} L0,${bottom}`}
        fill="none" stroke="#FFFFFF" strokeOpacity={0.85} strokeWidth={1.2} strokeLinejoin="round" />
    </g>
  );
}

function Palm({ x, scale, flip = false, p }: { x: number; scale: number; flip?: boolean; p: Palette }) {
  // Trunk leans; fronds fan from the crown. Drawn once at unit size.
  const fronds = [
    "M0,0 C-30,-12 -64,0 -88,28 C-60,14 -30,12 0,8Z",
    "M0,0 C-26,-30 -62,-34 -90,-20 C-60,-14 -30,-6 0,6Z",
    "M0,-2 C-8,-38 -30,-62 -56,-70 C-30,-46 -12,-26 4,2Z",
    "M0,-2 C12,-38 40,-58 68,-62 C42,-40 22,-20 -2,4Z",
    "M0,0 C32,-24 66,-22 94,-4 C62,-2 32,2 0,8Z",
    "M0,2 C30,0 58,22 74,52 C50,34 26,22 -2,10Z",
  ];
  return (
    <g transform={`translate(${x} ${WATER_Y + 12}) scale(${flip ? -scale : scale} ${scale})`} fill={p.palm}>
      <path d="M-4,0 C-2,-60 10,-120 30,-178 L38,-176 C20,-118 10,-58 6,0Z" />
      <g transform="translate(34 -178)">
        {fronds.map((d, i) => <path key={i} d={d} />)}
        <circle r={6} fill={p.palmCrown} />
      </g>
    </g>
  );
}

function SeaLink({ p }: { p: Palette }) {
  const deckY = (x: number) => 372 - (x - 880) * 0.03 - Math.sin(((x - 880) / 720) * Math.PI) * 10;
  const pylons = [{ x: 1150, top: 170 }, { x: 1400, top: 200 }];
  const deck = Array.from({ length: 25 }, (_, i) => 880 + i * 30).map((x) => `${x},${deckY(x).toFixed(1)}`).join(" L");
  return (
    <g fill="none" strokeLinecap="round">
      <path d={`M${deck}`} stroke={p.deck} strokeWidth={6} />
      <path d={`M${deck}`} stroke={p.deckEdge} strokeWidth={1.5} transform="translate(0 5)" />
      {pylons.map(({ x, top }) => {
        const base = deckY(x);
        return (
          <g key={x}>
            {/* Cable fans: stays to both sides, anchored along the deck. */}
            {[-1, 1].flatMap((side) =>
              Array.from({ length: 9 }, (_, i) => {
                const dx = side * (24 + i * 15);
                return (
                  <path key={`${side}-${i}`} d={`M${x},${top + 18 + i * 3} L${x + dx},${deckY(x + dx)}`}
                    stroke={p.cables} strokeWidth={1} strokeOpacity={0.9} />
                );
              }),
            )}
            {/* Inverted-Y tower: two legs meeting above the deck, one spire. */}
            <path d={`M${x - 24},${base + 30} L${x - 4},${top + 84} L${x},${top} L${x + 4},${top + 84} L${x + 24},${base + 30}`}
              stroke={p.pylon} strokeWidth={7} strokeLinejoin="round" />
            <path d={`M${x - 15},${base - 4} L${x + 15},${base - 4}`} stroke={p.pylon} strokeWidth={4} />
          </g>
        );
      })}
      {Array.from({ length: 12 }, (_, i) => 900 + i * 60).map((x) => (
        <path key={x} d={`M${x},${deckY(x) + 4} L${x},${WATER_Y + 2}`} stroke={p.piers} strokeWidth={3} />
      ))}
    </g>
  );
}

function Boat({ x, y, s, p }: { x: number; y: number; s: number; p: Palette }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${s})`} fill={p.boat}>
      <path d="M-26,0 L26,0 L19,9 L-19,9Z" />
      <path d="M-12,0 L-12,-10 L10,-10 L14,0Z" fill={p.cabin} />
      <path d="M-2,-10 L-2,-24" stroke={p.boat} strokeWidth={1.5} />
    </g>
  );
}

export interface MumbaiSkylineProps {
  /** Unique per drawing on the page: gradient and pattern ids are scoped by it. */
  idPrefix: string;
  className?: string;
  style?: CSSProperties;
  /** Crop anchor when the box is a different shape than the art. */
  focus?: "center" | "bottom";
  /** Vertical slice of the art to fit, [top, bottom] in art units. */
  crop?: [number, number];
  /** Leave out the palms and boats, e.g. for small thumbnails. */
  simple?: boolean;
  theme?: SkylineTheme;
  /** Only the city, bridge and water, with no sky: for drawing on a background of your own. */
  silhouette?: boolean;
}

export function MumbaiSkyline({ idPrefix: id, className, style, focus = "bottom", crop = [0, H], simple = false, theme = "light", silhouette = false }: MumbaiSkylineProps) {
  const p = PALETTES[theme];
  return (
    <svg
      viewBox={`0 ${crop[0]} ${W} ${crop[1] - crop[0]}`}
      preserveAspectRatio={focus === "bottom" ? "xMidYMax slice" : "xMidYMid slice"}
      className={className}
      style={style}
      role="img"
      aria-label="Illustration: Mumbai's skyline and the Sea Link at sunrise"
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#BBB5F0" />
          <stop offset="0.38" stopColor="#D8C9F3" />
          <stop offset="0.66" stopColor="#F6CADC" />
          <stop offset="0.8" stopColor="#FFD9B6" />
        </linearGradient>
        <radialGradient id={`${id}-sun`}>
          <stop offset="0" stopColor="#FFF7E8" />
          <stop offset="0.5" stopColor="#FFE2BF" stopOpacity="0.9" />
          <stop offset="1" stopColor="#FFC9A0" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-water`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.water[0]} />
          <stop offset="1" stopColor={p.water[1]} />
        </linearGradient>
        <linearGradient id={`${id}-far`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.far[0]} />
          <stop offset="1" stopColor={p.far[1]} />
        </linearGradient>
        <linearGradient id={`${id}-near`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={p.near[0]} />
          <stop offset="1" stopColor={p.near[1]} />
        </linearGradient>
        <linearGradient id={`${id}-crystal-a`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E9E6FF" />
          <stop offset="1" stopColor="#B4ACF6" />
        </linearGradient>
        <linearGradient id={`${id}-crystal-b`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#D2F3F7" />
          <stop offset="1" stopColor="#9C95EE" />
        </linearGradient>
        <linearGradient id={`${id}-crystal-c`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#A79FF2" />
          <stop offset="1" stopColor="#6E64DC" />
        </linearGradient>
        <radialGradient id={`${id}-crystal-glow`}>
          <stop offset="0" stopColor="#FFFFFF" stopOpacity="0.6" />
          <stop offset="1" stopColor="#FFFFFF" stopOpacity="0" />
        </radialGradient>
        <pattern id={`${id}-windows`} width="8" height="11" patternUnits="userSpaceOnUse">
          <rect x="2" y="3" width="2" height="3" fill={p.windows} opacity="0.75" />
          <rect x="5.5" y="7.5" width="2" height="3" fill={p.windows} opacity="0.35" />
        </pattern>
        <filter id={`${id}-soft`} x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="14" />
        </filter>
      </defs>
      <style>{`
        .ed-float { animation: ed-float 7s ease-in-out infinite; }
        @keyframes ed-float { 0%, 100% { translate: 0 0; } 50% { translate: 0 -6px; } }
        @media (prefers-reduced-motion: reduce) { .ed-float { animation: none; } }
      `}</style>

      {!silhouette && (
        <>
          <rect width={W} height={WATER_Y} fill={`url(#${id}-sky)`} />
          <circle cx={1170} cy={WATER_Y - 6} r={300} fill={`url(#${id}-sun)`} />
          <g fill="#FFFFFF" opacity={0.45} filter={`url(#${id}-soft)`}>
            <ellipse cx={380} cy={110} rx={170} ry={22} />
            <ellipse cx={860} cy={70} rx={210} ry={18} />
            <ellipse cx={1380} cy={150} rx={150} ry={16} />
          </g>
          {CRYSTALS.map((c) => <Crystal key={`${c.x}-${c.y}`} {...c} id={id} />)}
        </>
      )}

      {FAR.map((t) => (
        <rect key={`f${t.x}`} x={t.x} y={WATER_Y - t.h} width={t.w} height={t.h} fill={`url(#${id}-far)`} />
      ))}
      {/* one tall spired tower anchors the skyline */}
      <path d={`M700,${WATER_Y} V128 L716,104 L719,52 L722,104 L738,128 V${WATER_Y}Z`} fill={`url(#${id}-near)`} />
      <rect x={704} y={136} width={30} height={WATER_Y - 140} fill={`url(#${id}-windows)`} />
      {NEAR.map((t) => (
        <g key={`n${t.x}`}>
          <rect x={t.x} y={WATER_Y - t.h} width={t.w} height={t.h} fill={`url(#${id}-near)`} />
          <rect x={t.x + 3} y={WATER_Y - t.h + 6} width={Math.max(0, t.w - 6)} height={Math.max(0, t.h - 10)} fill={`url(#${id}-windows)`} />
        </g>
      ))}

      <rect y={WATER_Y} width={W} height={H - WATER_Y} fill={`url(#${id}-water)`} />
      <SeaLink p={p} />
      {/* sun and city lights on the water */}
      <g fill={p.glints}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect key={i} x={1110 + i * 9} y={WATER_Y + 10 + i * 14} width={120 - i * 18} height={3} rx={1.5} opacity={0.75 - i * 0.1} />
        ))}
      </g>
      <g fill={p.cityGlints} opacity={0.35}>
        {NEAR.filter((t) => t.h > 120).map((t, i) => (
          <rect key={t.x} x={t.x + 2} y={WATER_Y + 8 + (i % 3) * 8} width={t.w * 0.6} height={2} rx={1} />
        ))}
      </g>
      {!simple && (
        <>
          <Boat x={520} y={438} s={1} p={p} />
          <Boat x={930} y={458} s={0.8} p={p} />
          <Boat x={1290} y={446} s={0.9} p={p} />
          {/* palms stay at the edges so the title over the sky reads clearly */}
          <Palm x={18} scale={1.15} p={p} />
          <Palm x={96} scale={0.72} flip p={p} />
          <Palm x={1585} scale={1.05} flip p={p} />
        </>
      )}
    </svg>
  );
}
