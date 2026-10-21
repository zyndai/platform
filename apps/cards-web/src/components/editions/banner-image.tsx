import type { CSSProperties } from "react";

/* The Mumbai Builder Week artwork as a responsive image. It is 3:1
 * (2172 x 724) and is always cropped with object-fit: cover, so `sizes` gives
 * the width it is actually drawn at: on phones the banner's height decides
 * that (cover scales by height), not the viewport width. */
const BASE = "/editions/mumbai-26/banner";
const SRC_SET = `${BASE}-800.webp 800w, ${BASE}-1400.webp 1400w, ${BASE}-2172.webp 2172w`;

export function EditionBannerImage({ className, sizes, priority = false, style }: {
  className?: string;
  /** The rendered width of the image (see above). */
  sizes: string;
  /** The page's main banner: fetch it first, as it is the largest paint. */
  priority?: boolean;
  style?: CSSProperties;
}) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className={className}
      src={`${BASE}-1400.webp`}
      srcSet={SRC_SET}
      sizes={sizes}
      width={2172}
      height={724}
      alt=""
      decoding="async"
      fetchPriority={priority ? "high" : "auto"}
      loading={priority ? "eager" : "lazy"}
      style={style}
    />
  );
}
