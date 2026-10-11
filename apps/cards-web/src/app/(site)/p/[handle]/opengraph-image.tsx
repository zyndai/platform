import { buildCardOgImage } from "./og-card-image";

export const revalidate = 3600;
export const alt = "Zynd Card profile";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

interface ImageProps {
  params: Promise<{ handle: string }>;
}

export default async function Image({ params }: ImageProps) {
  const { handle } = await params;
  return buildCardOgImage(handle);
}
