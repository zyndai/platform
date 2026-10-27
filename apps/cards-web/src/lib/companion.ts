import { ownerRequest } from "@/lib/owner-home";

/**
 * Zynd Companion (browser extension) pairing. docs/plans/ZYND_COMPANION_PLAN.md.
 *
 * The extension opens /companion/connect?state=<32 hex>. The page tells it apart from a
 * stranger's link by talking to the extension's content script over window.postMessage:
 * nothing is minted unless the extension answered with that same state. The messages are
 * mirrored in apps/zynd-companion/src/protocol.ts.
 */
export const COMPANION_STATE = /^[a-f0-9]{32}$/;

export const BRIDGE_FROM_PAGE = "zynd-cards";
export const BRIDGE_FROM_EXTENSION = "zynd-companion";

export type FromExtension =
  | { source: typeof BRIDGE_FROM_EXTENSION; type: "ready"; state: string | null }
  | { source: typeof BRIDGE_FROM_EXTENSION; type: "paired"; state: string }
  | { source: typeof BRIDGE_FROM_EXTENSION; type: "rejected"; state: string; reason: string };

export interface CompanionDevice {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string;
}

export interface CompanionProfile {
  handle: string;
  name: string;
  headline: string;
  avatar_url: string;
  card_url: string;
  published: boolean;
  working_on: string[];
  exploring: unknown[];
}

export function pairCompanion(token: string, label: string) {
  return ownerRequest<{ token: string; device: CompanionDevice; profile: CompanionProfile }>(
    "companion/pair", token, "POST", { label },
  );
}

export async function listCompanionDevices(token: string): Promise<CompanionDevice[]> {
  return (await ownerRequest<{ devices: CompanionDevice[] }>("companion/devices", token)).devices;
}

export function revokeCompanionDevice(token: string, id: string) {
  return ownerRequest<null>(`companion/devices/${encodeURIComponent(id)}`, token, "DELETE");
}

/** "Chrome on Linux": enough for the person to recognise this browser in their device list. */
export function browserLabel(userAgent: string): string {
  const browser = /Edg\//.test(userAgent) ? "Edge" : /Brave/.test(userAgent) ? "Brave" : /Chrome\//.test(userAgent) ? "Chrome" : "Browser";
  const system = /Windows/.test(userAgent) ? "Windows" : /Mac OS X/.test(userAgent) ? "macOS" : /Android/.test(userAgent) ? "Android" : /Linux/.test(userAgent) ? "Linux" : "";
  return system ? `${browser} on ${system}` : browser;
}
