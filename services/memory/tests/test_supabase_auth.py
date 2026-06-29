"""Unit tests for the Supabase identity gate (no network/DB): verified email + name."""
from app.services.matching import _match_label
from app.supabase_auth import _verified_identity


def test_google_confirmed_returns_email_name_and_sub():
    user = {"id": "sub-123", "email": "User@Gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "google"},
            "user_metadata": {"full_name": "Sahil Yadav"}}
    assert _verified_identity(user) == ("user@gmail.com", "Sahil Yadav", "sub-123")


def test_name_falls_back_to_local_part_not_full_email():
    user = {"email": "victim@gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "google"}}
    assert _verified_identity(user) == ("victim@gmail.com", "victim", "")


def test_github_verified_via_user_metadata_is_trusted():
    user = {"id": "g-1", "email": "dev@example.com", "user_metadata": {"email_verified": True, "name": "Dev"},
            "app_metadata": {"provider": "github"}}
    assert _verified_identity(user) == ("dev@example.com", "Dev", "g-1")


def test_unconfirmed_email_is_rejected():
    assert _verified_identity({"email": "victim@gmail.com", "app_metadata": {"provider": "google"}}) is None


def test_untrusted_provider_is_rejected_even_if_confirmed():
    user = {"email": "victim@gmail.com", "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "email"}}
    assert _verified_identity(user) is None


def test_missing_email_is_rejected():
    assert _verified_identity({"app_metadata": {"provider": "google"},
                               "email_confirmed_at": "2026-01-01T00:00:00Z"}) is None


def test_match_label_shows_name_strips_email_falls_back():
    assert _match_label("Sahil Yadav", "abcd1234-x") == "Sahil Yadav"   # real name passes through
    assert _match_label("sahil@gmail.com", "abcd1234-x") == "sahil"     # legacy email -> local-part only
    assert _match_label(None, "abcd1234-x") == "zynd-abcd1234"          # unknown -> opaque handle
