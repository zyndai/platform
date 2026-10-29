/**
 * Which sign-in methods cards.zynd.ai offers besides LinkedIn.
 *
 * LinkedIn (OIDC) is the default and is always shown (D12 in
 * docs/plans/ZYND_DB_UNIFY_PLAN.md). Google shows only when the Supabase
 * project (aafo) has its provider enabled, read from the public auth settings
 * (lib/auth/sign-in-methods.ts on the server, then hooks/useSignInMethods.tsx
 * on the client). Anything unreadable means hidden.
 */
export interface SignInMethods {
  google: boolean;
  email: boolean;
}

export const LINKEDIN_ONLY: SignInMethods = { google: false, email: false };

/**
 * The email magic link stays off until a human confirms custom SMTP is set up
 * on aafo (the built-in sender is rate-limited and for testing only) and
 * amends D12. Supabase's `external.email` can't tell us that: the Email
 * provider is on by default, and aafo shares it with persona. To enable: set
 * up SMTP in Supabase, amend D12, then set this to true.
 */
export const EMAIL_SIGN_IN_ENABLED = false;

export function hasAlternateSignIn(methods: SignInMethods): boolean {
  return methods.google || methods.email;
}

/** GoTrue's GET /auth/v1/settings body: `external` holds one boolean per provider. Only an
 *  explicit `true` turns a method on, and email also needs `emailAllowed`. */
export function parseSignInSettings(data: unknown, emailAllowed = EMAIL_SIGN_IN_ENABLED): SignInMethods {
  const external = typeof data === "object" && data !== null ? (data as { external?: unknown }).external : null;
  if (typeof external !== "object" || external === null) return LINKEDIN_ONLY;
  const providers = external as Record<string, unknown>;
  return { google: providers.google === true, email: emailAllowed && providers.email === true };
}
