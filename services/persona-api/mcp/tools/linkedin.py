"""
LinkedIn MCP Tools

Registered via the ContextAware framework so the agent can:
  - read_linkedin_profile — read the principal's scraped LinkedIn data
  - post_to_linkedin      — share a post on the user's LinkedIn feed
  - send_linkedin_dm      — [PLACEHOLDER] DM requires LinkedIn Partner Program
  - read_linkedin_dms     — [PLACEHOLDER] DM requires LinkedIn Partner Program

All functions accept a `user_id` to look up stored data or OAuth tokens.
"""

import httpx
import asyncio

import config
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


def _extract_profile_fields(raw_profile: dict) -> dict:
    """Extract human-readable fields from an Apify raw_profile blob."""
    result: dict = {}

    if raw_profile.get("headline"):
        result["headline"] = raw_profile["headline"]
    if raw_profile.get("summary"):
        result["summary"] = raw_profile["summary"]
    if raw_profile.get("location"):
        result["location"] = raw_profile["location"]
    if raw_profile.get("industry"):
        result["industry"] = raw_profile["industry"]
    if raw_profile.get("connections_count"):
        result["connections_count"] = raw_profile["connections_count"]

    experience = raw_profile.get("experience", [])
    if experience:
        result["experience"] = []
        for exp in experience[:15]:
            result["experience"].append({
                "title": exp.get("title", ""),
                "company": exp.get("companyName") or exp.get("company") or "",
                "date_range": exp.get("dateRange") or exp.get("date_range") or "",
                "description": exp.get("description") or exp.get("body", "") or "",
            })

    education = raw_profile.get("education", [])
    if education:
        result["education"] = []
        for edu in education[:10]:
            result["education"].append({
                "school": edu.get("schoolName") or edu.get("school") or "",
                "degree": edu.get("degree") or "",
                "field": edu.get("fieldOfStudy") or edu.get("field") or "",
                "date_range": edu.get("dateRange") or edu.get("date_range") or "",
            })

    skills = raw_profile.get("skills", [])
    if skills:
        result["skills"] = [s if isinstance(s, str) else s.get("name", str(s)) for s in skills[:50]]

    languages = raw_profile.get("languages", [])
    if languages:
        result["languages"] = [l if isinstance(l, str) else l.get("name", str(l)) for l in languages]

    certifications = raw_profile.get("certifications", [])
    if certifications:
        result["certifications"] = []
        for cert in certifications[:20]:
            result["certifications"].append({
                "name": cert.get("name", ""),
                "issuer": cert.get("authority") or cert.get("institution") or "",
                "date": cert.get("date") or cert.get("date_range") or "",
            })

    return result


def read_linkedin_profile(user_id: str) -> dict:
    """
    Read the principal's scraped LinkedIn profile data.

    Returns structured fields from the most recent scrape: headline, summary,
    experience, education, skills, languages, certifications, and recent posts.
    Use this when the principal asks about their own LinkedIn data or when you
    need to reference their professional background.

    Args:
        user_id (str): The platform user ID

    Returns:
        dict: Structured profile with keys like headline, summary, experience,
              education, skills, languages, certifications, and recent_posts.
              Returns {"success": False, "error": "..."} if no profile scraped.
    """
    sb = config.get_supabase()
    result = (
        sb.table("linkedin_profiles")
        .select("raw_profile, raw_posts, scraped_at, profile_url")
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        return {
            "success": False,
            "error": "No LinkedIn profile data found. Ask the principal to connect LinkedIn in their dashboard settings.",
        }

    row = result.data[0]
    raw_profile = row.get("raw_profile") or {}
    raw_posts = row.get("raw_posts") or []

    profile = _extract_profile_fields(raw_profile)
    profile["profile_url"] = row.get("profile_url", "")
    profile["scraped_at"] = row.get("scraped_at", "")

    fields_found = [k for k in ("headline", "experience", "education", "skills", "summary") if profile.get(k)]
    profile_empty = len(fields_found) == 0

    recent_posts = []
    for post in raw_posts[:10]:
        text = post.get("text") or post.get("body") or ""
        if len(text) > 500:
            text = text[:497] + "..."
        recent_posts.append({
            "text": text,
            "posted_at": post.get("postedAt") or post.get("posted_at") or post.get("createdAt") or "",
            "url": post.get("postUrl") or post.get("url") or "",
            "reaction_count": post.get("reactionCount") or post.get("reactions_count") or 0,
        })
    profile["recent_posts"] = recent_posts

    if profile_empty:
        profile["warning"] = (
            "The last scrape returned no profile details (headline, experience, education, skills). "
            "The Apify actor may need a fresh run — ask the principal to disconnect and reconnect "
            "LinkedIn in their dashboard's Accounts page to trigger a new scrape. "
            "Also verify the profile URL is correct: " + (profile["profile_url"] or "unknown")
        )

    return {"success": True, **profile}
