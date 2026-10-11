import {
  OG_ALT,
  OG_CONTENT_TYPE,
  OG_REVALIDATE,
  OG_SIZE,
  buildCardOgImage,
} from "./og-card-image";

export const revalidate = OG_REVALIDATE;
export const alt = OG_ALT;
export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

interface ImageProps {
  params: Promise<{ handle: string }>;
}

export default async function Image({ params }: ImageProps) {
  const { handle } = await params;
  return buildCardOgImage(handle);
}
