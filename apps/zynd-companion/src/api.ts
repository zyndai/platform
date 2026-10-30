import type { Kind } from "./classify";
import { COMPANION_API } from "./config";
import { clearPaired, getStored } from "./storage";

export interface ExploringItem {
  url: string;
  title: string;
  kind: Kind;
  note: string;
  added_at: string;
}

export interface Lists {
  working_on: string[];
  exploring: ExploringItem[];
}

export interface Profile extends Lists {
  handle: string;
  name: string;
  headline: string;
  avatar_url: string;
  card_url: string;
  published: boolean;
}

/** `unpaired` means the token is no longer good (revoked, expired): the person must connect again. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly unpaired = false) {
    super(message);
  }
}

const TIMEOUT_MS = 10_000;

function explain(status: number, detail: string): string {
  if (status === 503) return "Zynd Companion is not available yet. Try again later.";
  if (status === 409) return "Your card changed at the same moment. Try again.";
  if (status === 404) return detail || "Create your card first, then try again.";
  if (status === 429) return "Too many changes at once. Wait a moment.";
  if (status >= 500) return "Zynd had a problem. Try again in a moment.";
  return detail || "That did not work.";
}

async function request<T>(path: string, method: string, body?: unknown, token?: string): Promise<T> {
  const auth = token ?? (await getStored()).token;
  if (!auth) throw new ApiError("Connect your Zynd account first.", 401, true);
  let res: Response;
  try {
    res = await fetch(`${COMPANION_API}${path}`, {
      method,
      headers: { Authorization: `Bearer ${auth}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Cannot reach Zynd. Check your connection.", 0);
  }
  if (res.status === 401) {
    if (token === undefined) await clearPaired();
    throw new ApiError("This browser is no longer connected to Zynd. Connect again.", 401, true);
  }
  if (!res.ok) {
    let detail = "";
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = typeof data.detail === "string" ? data.detail : "";
    } catch {
      /* The status says enough. */
    }
    throw new ApiError(explain(res.status, detail), res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** `token` is only passed while pairing, to check a token before it is kept. */
export const fetchProfile = (token?: string) => request<Profile>("/me", "GET", undefined, token);
export const addWorkingOn = (text: string) => request<Lists>("/working-on", "POST", { text });
export const removeWorkingOn = (text: string) => request<Lists>("/working-on/remove", "POST", { text });
export const addExploring = (item: { url: string; title: string; kind: Kind; note: string }) =>
  request<Lists>("/exploring", "POST", item);
export const removeExploring = (url: string) => request<Lists>("/exploring/remove", "POST", { url });
/** The card's own "Still working on this": resets the freshness visitors see, without changing the list. */
export const confirmWorkingOn = () => request<{ working_on_updated_at: string }>("/working-on/confirm", "POST");
export const disconnect = () => request<void>("/disconnect", "POST");
