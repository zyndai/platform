"""Unit tests for password hashing. No I/O."""
from app.passwords import hash_password, verify_password


def test_hash_verify_roundtrip():
    h = hash_password("supersecret")
    assert verify_password("supersecret", h)


def test_wrong_password_fails():
    assert not verify_password("nope", hash_password("supersecret"))


def test_hash_is_salted_unique():
    # Same password hashes differently each time (random salt).
    assert hash_password("samepassword") != hash_password("samepassword")


def test_verify_handles_missing_or_garbage():
    assert not verify_password("x", None)
    assert not verify_password("x", "")
    assert not verify_password("x", "not-a-valid-hash")
    assert not verify_password("x", "pbkdf2_sha256$bad$bad$bad")
