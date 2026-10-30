import type { UrlKind } from "./model";

export const KIND_LABEL: Record<UrlKind, string> = {
  github: "GitHub",
  linkedin: "LinkedIn",
  x: "X",
  producthunt: "Product Hunt",
  writing: "Newsletter",
  portfolio: "Portfolio",
  website: "Website",
};

/** What a source row says while it is being read. */
export const KIND_READING: Record<UrlKind, string> = {
  github: "Reading GitHub…",
  linkedin: "Reading LinkedIn…",
  x: "Reading X…",
  producthunt: "Reading Product Hunt…",
  writing: "Reading your writing…",
  portfolio: "Reading your portfolio…",
  website: "Reading the website…",
};

const SWATCH: Record<UrlKind, string> = {
  github: "#0B0B0B",
  linkedin: "#0A66C2",
  x: "#1C1C1C",
  producthunt: "#DA552F",
  writing: "#FF6719",
  portfolio: "#1769FF",
  website: "#6C5CE7",
};

/** The source's brand mark: a small coloured square. */
export function KindIcon({ kind, size = 20 }: { kind: UrlKind; size?: number }) {
  const inner = size * 0.7;
  return (
    <span
      aria-hidden="true"
      style={{
        width: size, height: size, borderRadius: Math.max(4, Math.round(size * 0.3)), background: SWATCH[kind],
        display: "inline-flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}
    >
      <svg width={inner} height={inner} viewBox="0 0 16 16" fill="none">
        {kind === "github" && (
          <path fill="#fff" fillRule="evenodd" d="M8 .5C3.858.5.5 3.882.5 8.056a7.56 7.56 0 0 0 5.129 7.17c.374.077.51-.163.51-.363 0-.175-.012-.775-.012-1.4-2.085.45-2.52-.9-2.52-.9-.337-.875-.832-1.1-.832-1.1-.682-.463.05-.463.05-.463.757.05 1.156.775 1.156.775.67 1.15 1.75.825 2.184.625.062-.487.261-.825.473-1.012-1.664-.175-3.415-.825-3.415-3.725 0-.825.299-1.5.77-2.025-.075-.187-.336-.963.074-2 0 0 .633-.2 2.06.775A7.2 7.2 0 0 1 8 5.156c.633 0 1.28.087 1.875.25 1.428-.975 2.061-.775 2.061-.775.41 1.038.15 1.813.074 2 .473.525.77 1.2.77 2.025 0 2.9-1.752 3.538-3.428 3.725.274.238.509.688.509 1.4 0 1.013-.012 1.825-.012 2.075 0 .2.136.438.509.363A7.56 7.56 0 0 0 15.5 8.056C15.5 3.882 12.142.5 8 .5" clipRule="evenodd" />
        )}
        {kind === "linkedin" && (
          <path fill="#fff" d="M4.2 6.4h1.8V12H4.2V6.4zm.9-2.8a1.05 1.05 0 1 1 0 2.1 1.05 1.05 0 0 1 0-2.1zM7.4 6.4h1.73v.76h.02c.24-.46.83-.95 1.71-.95 1.83 0 2.17 1.2 2.17 2.77V12h-1.8V9.32c0-.67-.01-1.53-.93-1.53-.94 0-1.08.73-1.08 1.48V12H7.4V6.4z" />
        )}
        {kind === "x" && (
          <path fill="#fff" fillRule="evenodd" d="M1.5 1.5h3.9l2.28 3.24 2.67-3.24H12l-3.6 4.38L13 14.5H9.1L6.63 11l-3 3.5H2l3.87-4.5zm2.1 1.2 6.6 9.6h1.2L4.8 2.7z" clipRule="evenodd" />
        )}
        {kind === "producthunt" && (
          <path fill="#fff" fillRule="evenodd" d="M5.5 3h3.4a2.9 2.9 0 0 1 0 5.8H7.3V13H5.5V3zm1.8 1.7v2.4h1.6a1.2 1.2 0 0 0 0-2.4H7.3z" clipRule="evenodd" />
        )}
        {kind === "writing" && <path fill="#fff" d="M3 3h10v1.6H3V3zm0 3.2h10v1.6H3V6.2zM3 9.4h10V11H3V9.4zm0 3.2h6.5v1.6H3v-1.6z" />}
        {kind === "portfolio" && <path fill="#fff" d="M2.5 2.5h4.6v4.6H2.5V2.5zm6.4 0h4.6v4.6H8.9V2.5zM2.5 8.9h4.6v4.6H2.5V8.9zm6.4 0h4.6v4.6H8.9V8.9z" />}
        {kind === "website" && <circle cx="8" cy="8" r="6" stroke="#fff" strokeWidth="1.5" fill="none" />}
      </svg>
    </span>
  );
}
