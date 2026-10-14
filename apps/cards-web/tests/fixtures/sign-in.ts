import type { BrowserContext } from "@playwright/test";

/** Sign in as the fixture owner (Alice) by planting the Supabase session cookie. */
export async function signIn(context: BrowserContext) {
  const user = {
    id: "11111111-1111-4111-8111-111111111111",
    aud: "authenticated",
    role: "authenticated",
    email: "owner@example.test",
    user_metadata: { name: "Alice Chen" },
  };
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const token = [
    Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString(
      "base64url",
    ),
    Buffer.from(
      JSON.stringify({
        sub: user.id,
        email: user.email,
        exp,
        aud: "authenticated",
        role: "authenticated",
      }),
    ).toString("base64url"),
    "smoke-fixture-signature",
  ].join(".");
  await context.addCookies([
    {
      name: "sb-127-auth-token",
      value:
        "base64-" +
        Buffer.from(
          JSON.stringify({
            access_token: token,
            refresh_token: "smoke-refresh",
            token_type: "bearer",
            expires_at: exp,
            expires_in: 3600,
            user,
          }),
        ).toString("base64url"),
      url: "http://127.0.0.1:3010",
      sameSite: "Lax",
    },
  ]);
}
