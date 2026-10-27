import { PAIRING_WINDOW_MS } from "./config";
import type { GrantProfile } from "./protocol";

/** What the extension keeps about the person: a device token and the header profile. Nothing else. */
export type Account = GrantProfile;

export interface Stored {
  token?: string;
  account?: Account;
  /** When the person last changed their card from here (or confirmed it is still right). */
  touchedAt?: number;
}

export interface Pending {
  state: string;
  expiresAt: number;
}

/** A clip started from the right-click menu, waiting for the person to check it in the popup. */
export interface Draft {
  url: string;
  title: string;
  note: string;
}

export async function getStored(): Promise<Stored> {
  return (await chrome.storage.local.get(["token", "account", "touchedAt"])) as Stored;
}

export async function setPaired(token: string, account: Account): Promise<void> {
  await chrome.storage.local.set({ token, account, touchedAt: Date.now() });
}

export async function updateAccount(account: Account): Promise<void> {
  await chrome.storage.local.set({ account });
}

export async function clearPaired(): Promise<void> {
  await chrome.storage.local.remove(["token", "account", "touchedAt"]);
  await chrome.storage.session.remove(["pending", "draft"]);
}

export async function touch(): Promise<void> {
  await chrome.storage.local.set({ touchedAt: Date.now() });
}

// Pairing state and drafts live in session storage: gone when the browser closes, and never readable
// from a web page's content script.

export async function beginPairing(state: string): Promise<void> {
  const pending: Pending = { state, expiresAt: Date.now() + PAIRING_WINDOW_MS };
  await chrome.storage.session.set({ pending });
}

export async function getPending(): Promise<Pending | null> {
  const { pending } = (await chrome.storage.session.get("pending")) as { pending?: Pending };
  return pending && pending.expiresAt > Date.now() ? pending : null;
}

export async function clearPending(): Promise<void> {
  await chrome.storage.session.remove("pending");
}

export async function setDraft(draft: Draft): Promise<void> {
  await chrome.storage.session.set({ draft });
}

export async function takeDraft(): Promise<Draft | null> {
  const { draft } = (await chrome.storage.session.get("draft")) as { draft?: Draft };
  if (draft) await chrome.storage.session.remove("draft");
  return draft ?? null;
}
