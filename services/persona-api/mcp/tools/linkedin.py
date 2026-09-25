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
import re

import config
from services.token_store import get_tokens
from mcp.tools.error_utils import friendly_error


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
            return friendly_error("post to LinkedIn", Exception(f"LinkedIn returned HTTP {resp.status_code}"))
    except Exception as e:
        return friendly_error("post to LinkedIn", e)


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


def _relevance_tokens(text: str) -> set[str]:
    """Word set for query-vs-headline matching. Splits on punctuation (so
    "Co-Founder," yields "founder") and keeps both plural and singular forms,
    so a "founders" query still matches a "Founder & CEO" headline."""
    tokens: set[str] = set()
    for w in re.split(r"[^a-z0-9]+", text.lower()):
        if len(w) <= 2:
            continue
        tokens.add(w)
        if len(w) > 3 and w.endswith("s"):
            tokens.add(w[:-1])
    return tokens


def search_linkedin_people(user_id: str, query: str, location: str = "", top_k: int = 8) -> dict:
    """
    Search LinkedIn ITSELF for people matching a role, topic, or keyword —
    e.g. "AI founders", "product designers in Berlin". This is a real,
    paid LinkedIn scrape (via Apify), separate from and complementary to
    `search_zynd_personas` / `search_zynd_network`, which only ever cover
    people who already have a Zynd persona.

    Use this when:
      - the principal explicitly asks to find/search people "on LinkedIn", or
      - a Zynd Network people search came back thin or empty and broadening
        to LinkedIn is a reasonable next step — say what you're doing
        ("I didn't find much on the network, checking LinkedIn too...")
        rather than switching silently.

    This calls a metered third-party API per search — do not call it
    speculatively, and don't retry it repeatedly for the same ask; one
    well-formed query is enough. Results are real public LinkedIn
    profiles, NOT Zynd personas: you cannot `request_connection` or
    `message_zynd_agent` them, only share/reference their profile_url.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        query: Role/topic/keyword phrase, e.g. "AI founder", "growth marketer".
        location: Optional city/region/country to narrow by, e.g. "San Francisco".
        top_k: Max people to return (1-15, default 8).

    Returns {status, count, results: [{name, headline, location, profile_url,
    current_company, match_reason}]}. If `warning` is present, the
    underlying data came back thinner than expected (field-mapping may be
    stale against the provider's current schema) — mention that
    uncertainty rather than presenting a confident empty answer as "no one
    matches."
    """
    top_k = max(1, min(int(top_k or 8), 15))
    q = (query or "").strip()
    if not q:
        return {
            "status": "error",
            "error": "A search query is required.",
            "error_message": "I need a role, topic, or keyword to search LinkedIn for — e.g. \"AI founders\" or \"product designers\".",
            "hint": "Try again with a specific role or topic.",
            "results": [],
            "count": 0,
        }

    try:
        import asyncio
        from services.linkedin_scraper import search_people
        items = asyncio.run(
            search_people(query=q, locations=[location.strip()] if location.strip() else None, max_items=top_k)
        )
    except Exception as e:
        return friendly_error("search LinkedIn for people", e)

    # Query tokens used for headline relevance filtering below.
    query_tokens = _relevance_tokens(q)

    results = []
    fields_missing = 0
    for item in items[:top_k * 3]:  # overscan so filtering doesn't starve top_k
        name = item.get("name") or f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
        loc = item.get("location")
        if isinstance(loc, dict):
            loc = loc.get("linkedinText") or loc.get("text") or ""
        current_position = item.get("currentPosition")
        company = ""
        if isinstance(current_position, list) and current_position:
            first_pos = current_position[0]
            if isinstance(first_pos, dict):
                company = first_pos.get("companyName") or ""
        profile_url = item.get("linkedinUrl") or item.get("profileUrl") or item.get("url") or ""
        headline = item.get("headline") or ""

        # Drop profiles whose headline shares no words with the query — these are
        # Apify returning tangentially matched profiles (LinkedIn's own algo
        # sometimes ranks for profile activity or network proximity rather than role).
        if query_tokens and headline:
            if not query_tokens & _relevance_tokens(headline):
                continue

        if not (name and profile_url):
            fields_missing += 1
        results.append({
            "name": name,
            "headline": headline,
            "location": loc or "",
            "profile_url": profile_url,
            "current_company": company,
            "match_reason": f"LinkedIn search match for \"{q}\"" + (f" in {location}" if location else ""),
        })
        if len(results) >= top_k:
            break

    out = {"status": "success", "count": len(results), "results": results, "source": "linkedin"}
    if items and fields_missing > len(results) / 2:
        out["warning"] = (
            "LinkedIn returned results but most are missing a name or profile link — "
            "the field mapping may be out of date against the provider's current response shape. "
            "Treat these results as unreliable rather than a confident match list."
        )
    return out


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
        # harvestapi's linkedin-profile-posts actor puts post text under
        # `content` and the URL under `linkedinUrl` — `text`/`body`/`postUrl`
        # don't exist on real responses, which is why posts used to come
        # back with a timestamp but no content.
        text = post.get("content") or post.get("text") or post.get("body") or ""
        if len(text) > 500:
            text = text[:497] + "..."
        posted_at_raw = post.get("postedAt")
        if isinstance(posted_at_raw, dict):
            # `postedAt` is a nested {timestamp, date} object, not a string.
            posted_at = posted_at_raw.get("date") or posted_at_raw.get("timestamp") or ""
        else:
            posted_at = posted_at_raw or post.get("posted_at") or post.get("createdAt") or ""
        engagement = post.get("engagement")
        reaction_count = engagement.get("likes") if isinstance(engagement, dict) else None
        if reaction_count is None:
            reaction_count = post.get("reactionCount") or post.get("reactions_count") or 0
        recent_posts.append({
            "text": text,
            "posted_at": posted_at,
            "url": post.get("linkedinUrl") or post.get("postUrl") or post.get("url") or "",
            "reaction_count": reaction_count,
        })
    profile["recent_posts"] = recent_posts

    if profile_empty:
        if not row.get("scraped_at"):
            # No scraped_at yet means a scrape has never actually completed —
            # most commonly because one just kicked off (connect triggers it
            # in the background and it can take a minute or two) and hasn't
            # landed. Telling the principal to reconnect here would just
            # restart the same in-flight process, not fix anything.
            profile["warning"] = (
                "LinkedIn is connected but the profile scrape hasn't finished yet. "
                "This usually completes within a couple of minutes of connecting — "
                "ask the principal to try again shortly rather than reconnecting."
            )
        else:
            profile["warning"] = (
                "The last scrape returned no profile details (headline, experience, education, skills). "
                "The Apify actor may need a fresh run — ask the principal to disconnect and reconnect "
                "LinkedIn in their dashboard's Accounts page to trigger a new scrape. "
                "Also verify the profile URL is correct: " + (profile["profile_url"] or "unknown")
            )

    return {"success": True, **profile}
