"""Unit tests for the Supabase email-verification security gate (no network/DB)."""
from app.supabase_auth import _verified_email


def test_google_confirmed_email_is_trusted():
    user = {"email": "User@Gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "google"}}
    assert _verified_email(user) == "user@gmail.com"


def test_github_verified_via_user_metadata_is_trusted():
    user = {"email": "dev@example.com", "user_metadata": {"email_verified": True},
            "app_metadata": {"provider": "github"}}
    assert _verified_email(user) == "dev@example.com"


def test_unconfirmed_email_is_rejected():
    # The account-takeover vector: a valid token but an unverified email.
    user = {"email": "victim@gmail.com", "app_metadata": {"provider": "google"}}
    assert _verified_email(user) is None


def test_untrusted_provider_is_rejected_even_if_confirmed():
    # Self-serve email/password signup: confirmed but not an ownership-verifying OAuth provider.
    user = {"email": "victim@gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "email"}}
    assert _verified_email(user) is None


def test_missing_email_is_rejected():
    assert _verified_email({"app_metadata": {"provider": "google"},
                            "email_confirmed_at": "2026-01-01T00:00:00Z"}) is None


def test_missing_provider_is_rejected():
    assert _verified_email({"email": "x@gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z"}) is None
