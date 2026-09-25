"""Unit tests for the multi-client OAuth logic (no DB/Redis needed).

Covers the second confidential client added for the Hermes Deployer: client
recognition, constant-time secret check, and the deployer-only personal-token
branch selector.
"""
import pytest

from app import oauth
from app.config import settings


def test_both_clients_are_known():
    assert oauth._is_known_client(settings.oauth_client_id)
    assert oauth._is_known_client(settings.deployer_oauth_client_id)


def test_unknown_client_rejected():
    assert not oauth._is_known_client("someone-else")


def test_only_deployer_is_deployer_client():
    assert oauth._is_deployer_client(settings.deployer_oauth_client_id)
    assert not oauth._is_deployer_client(settings.oauth_client_id)


def test_check_client_accepts_matching_secret():
    oauth._check_client(settings.oauth_client_id, settings.oauth_client_secret)
    oauth._check_client(settings.deployer_oauth_client_id, settings.deployer_oauth_client_secret)


def test_check_client_rejects_cross_secret():
    # The deployer id with the ChatGPT secret (and vice versa) must fail.
    with pytest.raises(Exception):
        oauth._check_client(settings.deployer_oauth_client_id, settings.oauth_client_secret)
    with pytest.raises(Exception):
        oauth._check_client(settings.oauth_client_id, settings.deployer_oauth_client_secret)


def test_deployer_redirect_prefix_allowlisted():
    assert any("deployer.zynd.ai" in p for p in settings.allowed_redirect_prefixes)


def test_code_user_binding_matches():
    import json as _json

    stored = _json.dumps({"user_id": "u-1", "redirect_uri": "https://deployer.zynd.ai/cb"})
    assert oauth._resolve_code_user(stored, "https://deployer.zynd.ai/cb") == "u-1"


def test_code_user_binding_rejects_mismatched_redirect_uri():
    import json as _json

    stored = _json.dumps({"user_id": "u-1", "redirect_uri": "https://deployer.zynd.ai/cb"})
    with pytest.raises(ValueError):
        oauth._resolve_code_user(stored, "https://evil.example/cb")


def test_code_user_binding_accepts_legacy_bare_user_id():
    # Codes issued before the rollout are a bare user_id string (no binding).
    assert oauth._resolve_code_user("u-legacy", "https://anything") == "u-legacy"
