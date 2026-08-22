/**
 * Silent signup-metadata capture.
 *
 * Fires once per user (guarded by localStorage) right after sign-in: sends
 * a handful of client-only facts (language, timezone, screen, platform,
 * touch, referrer) to `POST /api/auth/signup-meta`. The backend adds the
 * client IP, parsed User-Agent, and IP geolocation, and stores the merged
 * record in `user_metadata.signup_meta`. No prompts, no extra steps —
 * best-effort, and any failure is swallowed so signup/onboarding is
 * never affected.
 */
import { getSupabase } from "./supabase";
import type { User } from "@supabase/supabase-js";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const doneKey = (userId: string) => `zynd:signup-meta:${userId}`;

function isAlreadyCaptured(user: User): boolean {
  try {
    const meta = (user.user_metadata as Record<string, unknown> | null)
      ?.signup_meta;
    if (meta && typeof meta === "object") return true;
    return window.localStorage.getItem(doneKey(user.id)) === "1";
  } catch {
    return false;
  }
}

export async function captureSignupMeta(user: User | null): Promise<void> {
  if (!user || isAlreadyCaptured(user)) return;

  const payload: Record<string, unknown> = {};
  try {
    payload.language = navigator.language || undefined;
    payload.platform = (navigator as unknown as { userAgentData?: { platform?: string } })
      .userAgentData?.platform || navigator.platform || undefined;
    payload.touch = navigator.maxTouchPoints > 0;
    payload.screen = {
      w: window.screen?.width ?? undefined,
      h: window.screen?.height ?? undefined,
      dpr: window.devicePixelRatio || undefined,
    };
    payload.referrer = document.referrer || undefined;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    payload.timezone = tz || undefined;
  } catch {
    /* individual fields are best-effort */
  }

  try {
    const sb = getSupabase();
    const {
      data: { session },
    } = await sb.auth.getSession();
    const res = await fetch(`${API_BASE}/api/auth/signup-meta`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(session?.access_token
          ? { Authorization: `Bearer ${session.access_token}` }
          : {}),
      },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      try {
        window.localStorage.setItem(doneKey(user.id), "1");
      } catch {
        /* localStorage unavailable */
      }
    }
  } catch {
    /* never block the app on telemetry */
  }
}