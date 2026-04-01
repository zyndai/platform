"""
LinkedIn MCP Tools

Registered via the ContextAware framework so the agent can:
  - post_to_linkedin   — share a post on the user's LinkedIn feed
  - send_linkedin_dm   — [PLACEHOLDER] DM requires LinkedIn Partner Program
  - read_linkedin_dms  — [PLACEHOLDER] DM requires LinkedIn Partner Program

All functions accept a `user_id` to look up stored OAuth tokens.
"""

import httpx
import asyncio
from services.token_store import get_tokens


def _get_headers(user_id: str) -> dict:
    """Build auth headers from stored LinkedIn tokens."""
    tokens = get_tokens(user_id=user_id, provider="linkedin")
    if not tokens:
        raise ValueError("LinkedIn not connected. Please connect your LinkedIn account first.")
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _get_linkedin_user_urn(headers: dict) -> str:
    """Get the user's LinkedIn URN (person ID)."""
    with httpx.Client() as client:
        resp = client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers=headers,
        )
        resp.raise_for_status()
        return f"urn:li:person:{resp.json()['sub']}"


def post_to_linkedin(user_id: str, text: str) -> dict:
    """
    Share a text post on the user's LinkedIn feed.

    Args:
        user_id (str): The platform user ID
        text (str): Post content

    Returns:
        dict: Post result
    """
    try:
        headers = _get_headers(user_id)
        author_urn = _get_linkedin_user_urn(headers)

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        with httpx.Client() as client:
            resp = client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers=headers,
                json=payload,
            )
            if resp.status_code in (200, 201):
                return {"success": True, "post_id": resp.json().get("id")}
            return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_linkedin_dm(user_id: str, recipient: str, text: str) -> dict:
    """
    [PLACEHOLDER] Send a direct message on LinkedIn.

    LinkedIn messaging API is restricted to approved Partner Program members.
    This is a placeholder that will be implemented when access is granted.

    Args:
        user_id (str): The platform user ID
        recipient (str): LinkedIn profile URL or ID
        text (str): Message content

    Returns:
        dict: Placeholder result
    """
    return {
        "success": False,
        "error": "LinkedIn DM is not yet available. This feature requires LinkedIn Partner Program access.",
        "placeholder": True,
    }


def read_linkedin_dms(user_id: str, max_results: int = 10) -> dict:
    """
    [PLACEHOLDER] Read direct messages on LinkedIn.

    LinkedIn messaging API is restricted to approved Partner Program members.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of messages to fetch

    Returns:
        dict: Placeholder result
    """
    return {
        "success": False,
        "error": "LinkedIn DM reading is not yet available. This feature requires LinkedIn Partner Program access.",
        "placeholder": True,
    }
