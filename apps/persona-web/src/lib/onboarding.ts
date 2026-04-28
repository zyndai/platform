/**
 * Onboarding state machine.
 *
 * State lives in Supabase `auth.users.user_metadata.onboarding` so no
 * extra table is needed. The current "step" is derived on the fly from
 * a few inputs (does the user have a persona? is the calendar scope
 * granted?) plus a handful of small metadata flags that the onboarding
 * screens set as they complete. That means the flow is resumable: on
 * every dashboard load we recompute the step and route the user to the
 * screen they should be on.
 */
import { getSupabase } from "./supabase";

export type OnboardingStep =
  | "reading"
  | "you"
  | "brief"
  | "calendar"
  | "matches"
  | "done";

export interface OnboardingMeta {
  /** True after the S2 reading animation has played to completion at least once. */
  reading_seen?: boolean;
  /** True after the user's brief doc has been created in Drive. */
  brief_created?: boolean;
  /** True if the user tapped "Edit later" on the brief step. */
  skipped_brief?: boolean;
  /** True if the user tapped "Edit later" on the calendar step. */
  skipped_calendar?: boolean;
  /** True after S6 matches were shown (ends onboarding). */
  matches_shown?: boolean;
  /** Set right before redirecting to Google OAuth from the brief step.
   *  When true, the brief page on its next mount auto-creates the doc. */
  pending_brief_create?: boolean;
}

export interface OnboardingInputs {
  meta: OnboardingMeta;
  hasPersona: boolean;
  calendarConnected: boolean;
}

export function computeOnboardingStep(
  inputs: OnboardingInputs,
): OnboardingStep {
  const { meta, hasPersona, calendarConnected } = inputs;

  if (!hasPersona) {
    return meta.reading_seen ? "you" : "reading";
  }
  if (!meta.brief_created && !meta.skipped_brief) return "brief";
  if (!calendarConnected && !meta.skipped_calendar) return "calendar";
  if (!meta.matches_shown) return "matches";
  return "done";
}

export function stepToPath(step: OnboardingStep): string {
  return step === "done" ? "/dashboard/chat" : `/onboarding/${step}`;
}

/**
 * Merge a partial patch into the user's onboarding metadata. Safe to call
 * concurrently — reads the current value from the active session before
 * writing so no fields are accidentally clobbered.
 */
export async function patchOnboardingMeta(
  patch: Partial<OnboardingMeta>,
): Promise<void> {
  const sb = getSupabase();
  const {
    data: { user },
  } = await sb.auth.getUser();
  if (!user) return;

  const current =
    ((user.user_metadata as Record<string, unknown> | null)?.onboarding as
      | OnboardingMeta
      | undefined) ?? {};
  const merged = { ...current, ...patch };

  await sb.auth.updateUser({ data: { onboarding: merged } });
}

/**
 * Read `onboarding` out of the Supabase User object. Pure helper; no fetch.
 */
export function readOnboardingMeta(user: {
  user_metadata?: Record<string, unknown> | null;
}): OnboardingMeta {
  const meta = (user.user_metadata as Record<string, unknown> | null)
    ?.onboarding as OnboardingMeta | undefined;
  return meta ?? {};
}
