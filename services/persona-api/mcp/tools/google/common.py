"""
Common utilities for all Google Workspace tools.
Handles authentication and credentials building.
"""

from google.oauth2.credentials import Credentials
from services.token_store import get_tokens
import config

def get_google_creds(user_id: str) -> Credentials:
    """
    Build Google OAuth2 credentials from stored tokens in the database.
    
    Args:
        user_id (str): The platform user ID to fetch tokens for.
        
    Returns:
        Credentials: A ready-to-use google-auth Credentials object.
        
    Raises:
        ValueError: If the user hasn't successfully completed Google OAuth yet.
    """
    tokens = get_tokens(user_id=user_id, provider="google")
    if not tokens:
        raise ValueError("Google not connected. Please connect your Google account in settings.")

    return Credentials(
        token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
    )
