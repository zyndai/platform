/**
 * API helper — wraps fetch calls to the Python backend.
 * Automatically attaches the Supabase JWT as a Bearer token.
 *
 * GETs are wrapped in a stale-while-revalidate cache so navigating
 * between pages renders instantly from the last response and refetches
 * fresh data in the background. Mutations (POST/PATCH/DELETE) bypass
 * the cache and call `invalidate(prefix)` for affected paths so the
 * next read pulls fresh state.
 */
import { getSupabase } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAuthHeaders(): Promise<Record<string, string>> {
  const sb = getSupabase();
  const {
    data: { session },
  } = await sb.auth.getSession();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }
  return headers;
}

// ── SWR cache for GET responses ─────────────────────────────────────
// Tiny in-memory cache keyed on the request path. We don't bucket by
// user — Supabase signs the user out via a hard navigation that drops
// the module-level Map, and tokens rotate the JWT, so cross-user
// leakage can't happen in practice. The cache survives client-side
// route changes (the most common navigation), which is the whole point.
interface CacheEntry<T = unknown> {
  value: T;
  freshUntil: number; // ms epoch — past this we still serve but kick a refetch
  hardUntil: number;  // ms epoch — past this we wait for the network
}

const CACHE = new Map<string, CacheEntry>();
const INFLIGHT = new Map<string, Promise<unknown>>();
const DEFAULT_FRESH_MS = 5_000;   // 5 s — instant nav-back without a flicker
const DEFAULT_HARD_MS  = 60_000;  // 60 s — serve stale if the network is slow

async function rawGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, { headers, signal });
  if (!res.ok) throw new Error(await res.text());
  return res.json() as Promise<T>;
}

export interface ApiGetOptions {
  /** Bypass the cache entirely. */
  noCache?: boolean;
  /** Override the fresh window (ms). Default 5 s. */
  freshMs?: number;
  /** Optional abort signal for uncached reads. */
  signal?: AbortSignal;
}

export async function apiGet<T = unknown>(
  path: string,
  opts: ApiGetOptions = {},
): Promise<T> {
  if (opts.noCache) return rawGet<T>(path, opts.signal);

  const now = Date.now();
  const cached = CACHE.get(path) as CacheEntry<T> | undefined;

  // Within the hard window → return cached. If stale (past freshUntil),
  // also kick a background refresh so the next reader gets newer data.
  if (cached && now < cached.hardUntil) {
    if (now >= cached.freshUntil && !INFLIGHT.has(path)) {
      const p = rawGet<T>(path)
        .then((value) => {
          const fresh = opts.freshMs ?? DEFAULT_FRESH_MS;
          CACHE.set(path, {
            value,
            freshUntil: Date.now() + fresh,
            hardUntil: Date.now() + DEFAULT_HARD_MS,
          });
          return value;
        })
        .finally(() => INFLIGHT.delete(path));
      INFLIGHT.set(path, p);
    }
    return cached.value;
  }

  // Cold or past-hard. Dedupe concurrent first-loads on the same path
  // so a page hitting /api/groups/ three times in quick succession only
  // fires one network request.
  const inflight = INFLIGHT.get(path) as Promise<T> | undefined;
  if (inflight) return inflight;

  const p = rawGet<T>(path)
    .then((value) => {
      const fresh = opts.freshMs ?? DEFAULT_FRESH_MS;
      CACHE.set(path, {
        value,
        freshUntil: Date.now() + fresh,
        hardUntil: Date.now() + DEFAULT_HARD_MS,
      });
      return value;
    })
    .finally(() => INFLIGHT.delete(path));
  INFLIGHT.set(path, p);
  return p;
}

/**
 * Drop cache entries whose paths START WITH the prefix. Call after
 * mutations so the next GET pulls fresh state — e.g.
 * `invalidate("/api/groups/")` after creating, leaving, or archiving
 * a group.
 */
export function invalidate(prefix: string): void {
  for (const k of Array.from(CACHE.keys())) {
    if (k.startsWith(prefix)) CACHE.delete(k);
  }
}

export async function apiPost<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiPatch<T = unknown>(
  path: string,
  body: unknown,
): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
