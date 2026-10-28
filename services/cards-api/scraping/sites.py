"""Proof that lives on a person's own pages rather than in an API: their newsletter
or blog posts and the visual work in a design portfolio.

Both read the markdown Jina Reader returns for a public page (scraping/website.py)
and return plain dicts, so what they find can show on the create page the moment
the source finishes and go onto the card without another model call. They only
recognise the sites below; on any other page they return nothing and the
synthesis step reads the page text instead.
"""
import re
from urllib.parse import urlparse

POSTS_PER_SITE = 5
GALLERY_ITEMS = 6

# Hosts the create page labels as writing / portfolio. A custom-domain Substack
# is recognised from its page content in `writing_platform`.
_WRITING_HOSTS = (
    "substack.com", "medium.com", "dev.to", "hashnode.dev", "beehiiv.com", "ghost.io",
    "wordpress.com", "blogspot.com", "bearblog.dev", "mirror.xyz",
)
_PORTFOLIO_HOSTS = {"behance.net": "behance", "dribbble.com": "dribbble"}


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def is_writing_url(url: str) -> bool:
    host = _host(url)
    return any(_on(host, d) for d in _WRITING_HOSTS)


def portfolio_platform(url: str) -> str | None:
    host = _host(url)
    for domain, name in _PORTFOLIO_HOSTS.items():
        if _on(host, domain):
            return name
    return None


# ── newsletter / blog posts ──────────────────────────────────────────────────

_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]\n]{12,220})\]\((?P<href>https?://[^)\s]+)\)")
_MEDIUM_POST = re.compile(r"^/(?:@?[\w.-]+/)?[\w-]+-[0-9a-f]{8,}$")


def writing_platform(url: str, markdown: str = "") -> str | None:
    """'substack' | 'medium' for pages whose post links we know how to pick out."""
    host = _host(url)
    if _on(host, "substack.com") or "substackcdn.com" in markdown:
        return "substack"
    if _on(host, "medium.com"):
        return "medium"
    return None


def _is_post_link(platform: str, page_host: str, href: str) -> bool:
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if platform == "substack":
        # A post lives on the newsletter's own host under /p/<slug>.
        return host == page_host and parsed.path.startswith("/p/") and len(parsed.path) > 3
    return _on(host, "medium.com") and bool(_MEDIUM_POST.match(parsed.path))


def extract_posts(markdown: str, url: str, limit: int = POSTS_PER_SITE) -> list[dict]:
    """The newest posts on a newsletter or blog page: title (plus subtitle), link, platform."""
    platform = writing_platform(url, markdown)
    if not platform:
        return []
    page_host = _host(url)
    by_href: dict[str, list[str]] = {}
    for m in _LINK.finditer(markdown):
        href = m.group("href").split("?")[0].split("#")[0]
        if not _is_post_link(platform, page_host, href):
            continue
        text = " ".join(m.group("text").split())
        texts = by_href.setdefault(href, [])
        if text not in texts:
            texts.append(text)
    posts = []
    for href, texts in by_href.items():
        # Archives link each post twice: once by title, once by its subtitle.
        excerpt = texts[0] if len(texts) == 1 else f"{texts[0]} — {texts[1]}"
        posts.append({"platform": platform, "excerpt": excerpt, "url": href, "posted_at": ""})
        if len(posts) == limit:
            break
    return posts


# ── design portfolio tiles ───────────────────────────────────────────────────

_LINKED_IMAGE = re.compile(r"\[!\[(?P<alt>[^\]]*)\]\((?P<img>https?://[^)\s]+)\)\]\((?P<href>https?://[^)\s]+)\)")
_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<img>https?://[^)\s]+)\)")
_VIEW_LINK = re.compile(r"\[View (?P<title>[^\]]+)\]\((?P<href>https?://[^)\s]+)\)")
_ALT_PREFIX = re.compile(r"^Image \d+:?\s*")
# How far past a bare image to look for its "View <title>" link.
_VIEW_WINDOW = 400


def _is_work_image(platform: str, img: str) -> bool:
    """Project covers, not avatars, icons or site chrome."""
    parsed = urlparse(img)
    host = (parsed.hostname or "").lower()
    if platform == "behance":
        return _on(host, "behance.net") and parsed.path.startswith("/projects/")
    return host == "cdn.dribbble.com" and (
        parsed.path.startswith("/userupload/") or "/screenshots/" in parsed.path
    )


def _is_work_link(platform: str, href: str) -> bool:
    """A link to one project / shot, not to a profile or a category."""
    domain, prefix = ("behance.net", "/gallery/") if platform == "behance" else ("dribbble.com", "/shots/")
    return _on(_host(href), domain) and urlparse(href).path.startswith(prefix)


def _title(alt: str, href: str) -> str:
    title = " ".join(_ALT_PREFIX.sub("", alt).split())
    if title:
        return title[:120]
    slug = urlparse(href).path.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip()[:120]


def extract_gallery(markdown: str, url: str, limit: int = GALLERY_ITEMS) -> list[dict]:
    """Project tiles from a Behance or Dribbble profile: title, link, cover image."""
    platform = portfolio_platform(url)
    if not platform:
        return []
    found: list[tuple[int, dict]] = []
    seen: set[str] = set()

    def add(pos: int, alt: str, img: str, href: str) -> None:
        key = img.split("?")[0]
        if key in seen or not _is_work_image(platform, img) or not _is_work_link(platform, href):
            return
        seen.add(key)
        found.append((pos, {"title": _title(alt, href), "url": href, "image_url": img, "source": platform}))

    for m in _LINKED_IMAGE.finditer(markdown):  # Behance: the cover is itself the link
        add(m.start(), m.group("alt"), m.group("img"), m.group("href"))
    for m in _IMAGE.finditer(markdown):  # Dribbble: the cover, then a "View <title>" link
        view = _VIEW_LINK.search(markdown, m.end(), m.end() + _VIEW_WINDOW)
        if view:
            add(m.start(), m.group("alt") or view.group("title"), m.group("img"), view.group("href"))
    found.sort(key=lambda item: item[0])
    return [item for _, item in found[:limit]]
