import { unstable_rethrow } from "next/navigation";
import { LINKEDIN_ONLY, parseSignInSettings, type SignInMethods } from "@/lib/auth/providers";

/** Provider toggles change rarely, and a few minutes' lag after one is flipped in Supabase is fine. */
const SETTINGS_TTL_MS = 5 * 60_000;
/** After a failed read, retry soon rather than hide the buttons for a full TTL. */
const FAILURE_TTL_MS = 30_000;
/** Every page's layout awaits this on a cold cache; a slow Supabase must not hold the page. */
const SETTINGS_TIMEOUT_MS = 3_000;

let cached: { expiresAt: number; methods: SignInMethods } | null = null;
let inflight: Promise<SignInMethods> | null = null;

/**
 * The sign-in methods the Supabase project has enabled (lib/auth/providers.ts),
 * for server components and route handlers.
 *
 * Memoized in process rather than with fetch's `next.revalidate`: the layouts
 * that call this also wrap force-dynamic pages (/home, /directory, …), where
 * Next skips its data cache and every render would ask Supabase again.
 */
export function getSignInMethods(): Promise<SignInMethods> {
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.methods);
  inflight ??= loadSignInMethods().finally(() => {
    inflight = null;
  });
  return inflight;
}

async function loadSignInMethods(): Promise<SignInMethods> {
  const methods = await readSettings();
  if (methods) {
    cached = { expiresAt: Date.now() + SETTINGS_TTL_MS, methods };
    return methods;
  }
  // Keep the last good answer through a blip; with none, LinkedIn only.
  const fallback = cached?.methods ?? LINKEDIN_ONLY;
  cached = { expiresAt: Date.now() + FAILURE_TTL_MS, methods: fallback };
  return fallback;
}

async function readSettings(): Promise<SignInMethods | null> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;
  try {
    const res = await fetch(`${url.replace(/\/+$/, "")}/auth/v1/settings`, {
      headers: { apikey: anonKey },
      cache: "no-store",
      signal: AbortSignal.timeout(SETTINGS_TIMEOUT_MS),
    });
    if (!res.ok) {
      console.warn("Supabase auth settings unavailable; offering LinkedIn only", { status: res.status });
      return null;
    }
    return parseSignInSettings(await res.json());
  } catch (error) {
    // While prerendering, Next signals "this route is dynamic" by throwing from fetch; that is
    // not a failed read and must reach Next.
    unstable_rethrow(error);
    console.warn("Supabase auth settings unreadable; offering LinkedIn only", error);
    return null;
  }
}
