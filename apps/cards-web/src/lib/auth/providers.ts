/**
 * Which sign-in methods cards.zynd.ai offers besides LinkedIn.
 *
 * LinkedIn (OIDC) is the default and is always shown (D12 in
 * docs/plans/ZYND_DB_UNIFY_PLAN.md). Google and the email magic link exist
 * behind these flags; turning either on reverses D12 for that method. Both
 * default off, and each one needs Supabase (aafo) configured first: the Google
 * provider for NEXT_PUBLIC_AUTH_GOOGLE, SMTP for NEXT_PUBLIC_AUTH_EMAIL.
 *
 * NEXT_PUBLIC_* is inlined at `next build`, so server and client always agree
 * and flipping a flag needs a rebuild. The literal `process.env.NAME` reads are
 * required for that inlining to happen.
 */
export const googleSignInEnabled = process.env.NEXT_PUBLIC_AUTH_GOOGLE === "true";
export const emailSignInEnabled = process.env.NEXT_PUBLIC_AUTH_EMAIL === "true";
export const alternateSignInEnabled = googleSignInEnabled || emailSignInEnabled;
