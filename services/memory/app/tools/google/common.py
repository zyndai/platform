
from google.oauth2.credentials import Credentials
from app.services.token_store import get_tokens
from app.config import settings


def get_google_creds(user_id: str) -> Credentials:
    tokens = get_tokens(user_id=user_id, provider="google")
    if not tokens:
        raise ValueError("Google not connected. Please connect your Google account in settings.")

    return Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )
