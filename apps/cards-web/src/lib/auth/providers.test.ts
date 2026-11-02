import assert from "node:assert/strict";
import test from "node:test";

import { EMAIL_SIGN_IN_ENABLED, hasAlternateSignIn, LINKEDIN_ONLY, parseSignInSettings } from "./providers.ts";

const BOTH_ON = { external: { google: true, email: true, linkedin_oidc: true }, disable_signup: false };

test("Google follows Supabase's provider setting", () => {
  assert.equal(parseSignInSettings(BOTH_ON).google, true);
  assert.equal(parseSignInSettings({ external: { google: false, email: true } }).google, false);
});

test("email stays off while the code constant is off, even when Supabase has it on", () => {
  assert.equal(EMAIL_SIGN_IN_ENABLED, false);
  assert.deepEqual(parseSignInSettings(BOTH_ON), { google: true, email: false });
});

test("once allowed, email follows Supabase's provider setting", () => {
  assert.deepEqual(parseSignInSettings(BOTH_ON, true), { google: true, email: true });
  assert.deepEqual(parseSignInSettings({ external: { google: false, email: false } }, true), LINKEDIN_ONLY);
});

test("anything but an explicit true stays hidden", () => {
  for (const data of [null, undefined, "settings", 42, {}, { external: null }, { external: "yes" },
    { external: { google: "true", email: 1 } }]) {
    assert.deepEqual(parseSignInSettings(data, true), LINKEDIN_ONLY, JSON.stringify(data));
  }
});

test("alternate sign-in exists when either method is on", () => {
  assert.equal(hasAlternateSignIn(LINKEDIN_ONLY), false);
  assert.equal(hasAlternateSignIn({ google: true, email: false }), true);
  assert.equal(hasAlternateSignIn({ google: false, email: true }), true);
});
