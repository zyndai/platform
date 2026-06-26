"""Password hashing — PBKDF2-HMAC-SHA256 via the standard library (no extra deps).

600k iterations per OWASP guidance for PBKDF2-SHA256. Stored format:
    pbkdf2_sha256$<iterations>$<salt_hex>$<derived_hex>
"""
import hashlib
import hmac
import secrets

_ALGO = "sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_{_ALGO}${_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iterations_s, salt_hex, derived_hex = stored.split("$")
        if scheme != f"pbkdf2_{_ALGO}":
            return False
        iterations = int(iterations_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(derived_hex)
    except (ValueError, AttributeError):
        return False
    derived = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt, iterations)
    return hmac.compare_digest(derived, expected)  # constant-time
