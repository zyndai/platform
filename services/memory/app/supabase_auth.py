"""Verify a Supabase (Google/GitHub) access token server-side and return the user's
verified email.

We delegate token verification to Supabase's /auth/v1/user endpoint (no need for the
JWT signing secret): a valid token returns the user, an invalid one returns 401.

Security: the returned email is trusted by /token/exchange to identify (and link) a
ZYND account, so we MUST NOT trust a raw `email` field alone. Supabase will happily
return an *unconfirmed* email for a self-serve email/password (or other) signup, which
would let an attacker register `victim@example.com` without proving ownership and then
take over the victim's account via the email upsert. We therefore require the email to
be provider-verified AND to come from a trusted OAuth provider that itself verifies
email ownership.
"""
import httpx

from app.config import settings

# OAuth providers that verify the user owns the email before issuing identity.
# These are the only providers the dashboard offers for the connect flow.
TRUSTED_PROVIDERS = frozenset({"google", "github"})


def _verified_identity(user: dict) -> tuple[str, str] | None:
    """Extract (email, display_name) from a Supabase user object, or None if it fails
    the security checks. display_name is the provider-supplied name (Google full_name)
    — the human label shown in matches; it falls back to the email local-part, never
    the full email. Pure (no I/O) so the gate is unit-testable without a live token."""
    email = user.get("email")
    if not email:
        return None
    # Email must be confirmed by Supabase or marked verified by the OAuth provider.
    email_verified = bool(
        user.get("email_confirmed_at")
        or user.get("user_metadata", {}).get("email_verified")
    )
    provider = user.get("app_metadata", {}).get("provider")
    if not email_verified or provider not in TRUSTED_PROVIDERS:
        return None
    email = email.strip().lower()
    meta = user.get("user_metadata", {})
    name = (meta.get("full_name") or meta.get("name") or "").strip()
    return email, (name or email.split("@", 1)[0])


async def _fetch_user(access_token: str) -> dict | None:
    if not access_token or not (settings.supabase_url and settings.supabase_anon_key):
        return None
    url = settings.supabase_url.rstrip("/") + "/auth/v1/user"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": settings.supabase_anon_key,
            })
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


async def supabase_identity(access_token: str) -> tuple[str, str] | None:
    """Verified (email, display_name) for a Supabase Google/GitHub session, or None."""
    user = await _fetch_user(access_token)
    return _verified_identity(user) if user else None


async def supabase_email(access_token: str) -> str | None:
    identity = await supabase_identity(access_token)
    return identity[0] if identity else None
