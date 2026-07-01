"""Unit tests for hardening fixes (no DB): control-char sanitize + token sub guard."""
import jwt

from app.auth import verify_access_token
from app.config import settings
from app.services.ingest import clean_text


def test_clean_text_strips_controls_keeps_whitespace():
    assert clean_text("a\x00b\x07c") == "abc"            # NUL + control removed
    assert clean_text("line1\nline2\ttab\rok") == "line1\nline2\ttab\rok"  # \n \t \r kept


def test_token_without_sub_is_rejected():
    # Validly signed, correct issuer/type, but no sub -> ValueError (401), not KeyError (500).
    tok = jwt.encode({"typ": "access", "iss": settings.jwt_issuer}, settings.jwt_secret, algorithm="HS256")
    try:
        verify_access_token(tok)
        assert False, "expected ValueError"
    except ValueError:
        pass
