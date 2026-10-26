"""What one scraped source can tell the onboarding page before the card is built.

The page shows each source filling in live, so this reads only what the scrapers
already returned (labelled lines in the text, the stats dict, the GitHub user)
and never calls an LLM: it has to be ready the moment the source finishes.
"""
import re

from services.cards import clean_excerpt, is_thin_excerpt

_LABELLED = {
    "name": ("Name",),
    "headline": ("Headline",),
    "location": ("Location",),
    "bio": ("About", "Bio"),
}
_BIO_MAX = 240
_POSTS_SHOWN = 3
_POST_MAX = 200


def _labelled(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        m = re.search(rf"^{label}:[ \t]*(.+)$", text, re.MULTILINE)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _post_excerpts(posts: list | None) -> list[str]:
    """The first few posts that will survive onto the card (same filters as the merge)."""
    out: list[str] = []
    for post in posts or []:
        if not isinstance(post, dict):
            continue
        excerpt = clean_excerpt(str(post.get("excerpt") or ""))
        if excerpt and not is_thin_excerpt(excerpt):
            out.append(_clip(excerpt, _POST_MAX))
        if len(out) == _POSTS_SHOWN:
            break
    return out


def github_preview(data: dict) -> dict:
    user = data.get("user") or {}
    stats = data.get("stats") or {}
    return {
        "name": user.get("name") or user.get("login") or "",
        "headline": user.get("bio") or "",
        "location": user.get("location") or "",
        "avatar": user.get("avatar_url") or "",
        "facts": [
            f"{stats['total_repos']} public repos" if stats.get("total_repos") else "",
            ", ".join(stats.get("top_languages") or []),
            f"{user['followers']} followers" if user.get("followers") else "",
        ],
    }


def text_preview(kind: str, text: str, stats: dict | None) -> dict:
    stats = stats or {}
    facts: list[str] = []
    if stats.get("followers") not in (None, "", "—"):
        facts.append(f"{stats['followers']} followers")
    if stats.get("posts") not in (None, "", "—", 0):
        facts.append(f"{stats['posts']} posts")
    preview = {
        "name": _labelled(text, _LABELLED["name"]),
        "headline": _labelled(text, _LABELLED["headline"]),
        "location": _labelled(text, _LABELLED["location"]),
        "bio": _clip(_labelled(text, _LABELLED["bio"]), _BIO_MAX),
        "avatar": stats.get("avatar") or "",
        "facts": facts,
        "posts": _post_excerpts(stats.get("posts_raw")),
    }
    if kind == "website" and not preview["name"]:
        preview["bio"] = preview["bio"] or _clip(text, _BIO_MAX)
    return preview


def build_preview(kind: str, text: str = "", stats: dict | None = None, github: dict | None = None) -> dict:
    """The preview dict for one finished source, empty values dropped."""
    raw = github_preview(github) if github else text_preview(kind, text, stats)
    raw["facts"] = [f for f in raw.get("facts", []) if f]
    return {k: v for k, v in raw.items() if v}
