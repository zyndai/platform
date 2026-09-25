"""
Common utilities for all Google Workspace tools.
Handles authentication and credentials building.
"""

from datetime import datetime, timezone

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from services.token_store import get_tokens, save_tokens
import config


class PersistentCredentials(Credentials):
    """Credentials that persist refreshed access tokens back to the DB.

    Without this, every tool call builds a fresh Credentials from the stored
    (possibly stale) access token and google-auth re-refreshes each time,
    wasting a Google token endpoint call per tool invocation. This subclass
    saves the new access token after each successful refresh so the next
    ``get_google_creds()`` loads the current token.
    """

    _user_id: str

    def refresh(self, request):
        try:
            super().refresh(request)
        except RefreshError:
            raise ValueError(
                "Google token has expired or been revoked. "
                "Please reconnect your Google account in Settings → Connected Accounts."
            ) from None

        # Best-effort persist — a save failure shouldn't crash the caller
        # because the credentials are already valid in-memory.
        try:
            expires_in = None
            if self.expiry:
                expires_in = max(0, int((self.expiry - datetime.now(timezone.utc)).total_seconds()))
            save_tokens(
                user_id=self._user_id,
                provider="google",
                tokens={
                    "access_token": self.token,
                    "refresh_token": self.refresh_token,
                    **({"expires_in": expires_in} if expires_in is not None else {}),
                },
            )
        except Exception:
            pass


def get_google_creds(user_id: str) -> PersistentCredentials:
    """
    Build Google OAuth2 credentials from stored tokens in the database.

    Returns a :class:`PersistentCredentials` that auto-refreshes when expired
    and persists the new access token so subsequent calls reuse it.

    Args:
        user_id (str): The platform user ID to fetch tokens for.

    Returns:
        PersistentCredentials: Ready-to-use google-auth credentials with
                               auto-refresh + DB persistence.

    Raises:
        ValueError: If the user hasn't connected Google, or if the stored
                    refresh token is invalid / revoked.
    """
    tokens = get_tokens(user_id=user_id, provider="google")
    if not tokens:
        raise ValueError("Google not connected. Please connect your Google account in settings.")

    creds = PersistentCredentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
    )
    creds._user_id = user_id
    return creds
