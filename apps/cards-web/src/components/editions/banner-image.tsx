import type { CSSProperties } from "react";
import type { EditionBanner } from "@/lib/editions";

/* The Mumbai Builder Week artwork as a responsive image. Both pieces are wide
 * (waterfront 2172 x 724; gateway 1620 x 724, cropped clear of the Devcon
 * lettering in the source file) and always drawn with object-fit: cover, so
 * `sizes` gives the width they are actually drawn at: on phones the banner's
 * height decides that (cover scales by height), not the viewport width. */
const ART: Record<EditionBanner, { base: string; widths: number[]; size: [number, number] }> = {
  waterfront: { base: "/editions/mumbai-26/banner", widths: [800, 1400, 2172], size: [2172, 724] },
  gateway: { base: "/editions/mumbai-26/gateway", widths: [800, 1400, 1620], size: [1620, 724] },
};

export function EditionBannerImage({ banner, className, sizes, priority = false, style }: {
  banner: EditionBanner;
  className?: string;
  /** The rendered width of the image (see above). */
  sizes: string;
  /** The page's main banner: fetch it first, as it is the largest paint. */
  priority?: boolean;
  style?: CSSProperties;
}) {
  const art = ART[banner];
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      src={`${art.base}-1400.webp`}
      srcSet={art.widths.map((w) => `${art.base}-${w}.webp ${w}w`).join(", ")}
      sizes={sizes}
      width={art.size[0]}
      height={art.size[1]}
      alt=""
      decoding="async"
      fetchPriority={priority ? "high" : "auto"}
      loading={priority ? "eager" : "lazy"}
      style={style}
    />
  );
}
