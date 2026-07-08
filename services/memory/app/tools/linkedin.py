
import asyncio

import httpx

from app.services.token_store import get_tokens


def _get_headers(user_id: str) -> dict:
    tokens = get_tokens(user_id=user_id, provider="linkedin")
    if not tokens:
        raise ValueError("LinkedIn not connected. Please connect your LinkedIn account first.")
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _get_linkedin_user_urn(headers: dict) -> str:
    with httpx.Client() as client:
        resp = client.get("https://api.linkedin.com/v2/userinfo", headers=headers)
        resp.raise_for_status()
        return f"urn:li:person:{resp.json()['sub']}"


async def post_to_linkedin(user_id: str, text: str) -> dict:
    def _post() -> dict:
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
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }
            with httpx.Client() as client:
                resp = client.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    return {"success": True, "post_id": resp.json().get("id")}
                return {"success": False, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_post)


async def send_linkedin_dm(user_id: str, recipient: str, text: str) -> dict:
    return {
        "success": False,
        "error": "LinkedIn DM is not yet available. This feature requires LinkedIn Partner Program access.",
        "placeholder": True,
    }


async def read_linkedin_dms(user_id: str, max_results: int = 10) -> dict:
    return {
        "success": False,
        "error": "LinkedIn DM reading is not yet available. This feature requires LinkedIn Partner Program access.",
        "placeholder": True,
    }
