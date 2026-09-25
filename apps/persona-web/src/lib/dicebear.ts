import { createAvatar } from "@dicebear/core";
import {
  botttsNeutral,
  lorelei,
  notionistsNeutral,
  funEmoji,
  personas,
  shapes,
  rings,
  identicon,
  pixelArtNeutral,
  thumbs,
} from "@dicebear/collection";

export type PersonaStyleId =
  | "botttsNeutral"
  | "lorelei"
  | "notionistsNeutral"
  | "funEmoji"
  | "personas";

export type GroupStyleId =
  | "shapes"
  | "rings"
  | "identicon"
  | "pixelArtNeutral"
  | "thumbs";

export type DiceBearStyleId = PersonaStyleId | GroupStyleId;

const STYLE_SCHEMAS: Record<DiceBearStyleId, object> = {
  botttsNeutral,
  lorelei,
  notionistsNeutral,
  funEmoji,
  personas,
  shapes,
  rings,
  identicon,
  pixelArtNeutral,
  thumbs,
};

export const PERSONA_STYLES: { id: PersonaStyleId; label: string }[] = [
  { id: "botttsNeutral", label: "Robot" },
  { id: "lorelei", label: "Lorelei" },
  { id: "notionistsNeutral", label: "Notion" },
  { id: "funEmoji", label: "Emoji" },
  { id: "personas", label: "Person" },
];

export const GROUP_STYLES: { id: GroupStyleId; label: string }[] = [
  { id: "shapes", label: "Shapes" },
  { id: "rings", label: "Rings" },
  { id: "identicon", label: "Grid" },
  { id: "pixelArtNeutral", label: "Pixel" },
  { id: "thumbs", label: "Thumbs" },
];

export function generateAvatarDataUri(style: DiceBearStyleId, seed: string): string {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return createAvatar(STYLE_SCHEMAS[style] as any, { seed }).toDataUri();
}

export function defaultPersonaStyle(): PersonaStyleId {
  return "botttsNeutral";
}

export function defaultGroupStyle(): GroupStyleId {
  return "shapes";
}

export function isDiceBearUri(url: string | null | undefined): boolean {
  if (!url) return false;
  return url.startsWith("data:image/svg+xml");
}
