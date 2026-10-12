/** S08 onboarding v2 rollout: env flag + sticky cookie % bucket + force escape. */

export const S08_COOKIE = "zynd_s08";
const MAX_AGE = 60 * 60 * 24 * 30; // 30 days

function envOn(): boolean {
  return process.env.NEXT_PUBLIC_FEATURE_S08_ONBOARDING_V2 === "true";
}

function envPct(): number {
  const raw = process.env.NEXT_PUBLIC_FEATURE_S08_PCT;
  if (raw === undefined || raw === "") return envOn() ? 100 : 0;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, n));
}

function readCookie(): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${S08_COOKIE}=`));
  return hit ? decodeURIComponent(hit.split("=").slice(1).join("=")) : null;
}

function writeCookie(value: "0" | "1"): void {
  if (typeof document === "undefined") return;
  const secure = typeof location !== "undefined" && location.protocol === "https:" ? "; secure" : "";
  document.cookie = `${S08_COOKIE}=${value}; path=/; max-age=${MAX_AGE}; samesite=lax${secure}`;
}

/**
 * Whether this visitor gets onboarding v2 (live preview, no 6-step quiz).
 *
 * Escape hatches (cookie wins over %):
 *   zynd_s08=0|v1|off  → force v1 quiz path
 *   zynd_s08=1|v2|on   → force v2
 *
 * When unset, assign a sticky random bucket against NEXT_PUBLIC_FEATURE_S08_PCT
 * (requires NEXT_PUBLIC_FEATURE_S08_ONBOARDING_V2=true).
 */
export function featureS08OnboardingV2(): boolean {
  const cookie = readCookie();
  if (cookie === "0" || cookie === "v1" || cookie === "off") return false;
  if (cookie === "1" || cookie === "v2" || cookie === "on") return true;

  if (!envOn()) {
    writeCookie("0");
    return false;
  }

  const pct = envPct();
  if (pct <= 0) {
    writeCookie("0");
    return false;
  }
  if (pct >= 100) {
    writeCookie("1");
    return true;
  }

  const on = Math.floor(Math.random() * 100) < pct;
  writeCookie(on ? "1" : "0");
  return on;
}
