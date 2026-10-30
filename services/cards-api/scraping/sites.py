"""Proof that lives on a person's own pages rather than in an API: their newsletter
or blog posts, the visual work in a design portfolio, and the products they
launched on Product Hunt.

All of them read the markdown Jina Reader returns for a public page (scraping/website.py)
and return plain dicts, so what they find can show on the create page the moment
the source finishes and go onto the card without another model call. They only
recognise the sites below; on any other page they return nothing and the
synthesis step reads the page text instead.
"""
import re
from urllib.parse import urlparse

POSTS_PER_SITE = 5
GALLERY_ITEMS = 6
LAUNCHES_PER_PROFILE = 6

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


# One path segment "@<username>": the profile itself, or one of its tabs below it (/made, /submitted).
_PH_PROFILE_SEGMENT = re.compile(r"^@(?P<user>[A-Za-z0-9_]{1,40})$")


def producthunt_maker(url: str) -> str | None:
    """The username a pasted Product Hunt profile belongs to: producthunt.com/@ada.

    A product or launch page (/products/…, /posts/…) has no maker of its own to read,
    so it gives None and is read as an ordinary page."""
    if _host(url) != "producthunt.com":
        return None
    first = urlparse(url).path.strip("/").split("/")[0]
    m = _PH_PROFILE_SEGMENT.match(first)
    return m.group("user").lower() if m else None


# ── newsletter / blog posts ──────────────────────────────────────────────────

_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]\n]{12,220})\]\((?P<href>https?://[^)\s]+)\)")
# A Medium story's path ends in a slug plus the hex id Medium gives every story.
_MEDIUM_STORY = re.compile(r"^[\w-]+-[0-9a-f]{8,}$")


def writing_platform(url: str, markdown: str = "") -> str | None:
    """'substack' | 'medium' for pages whose post links we know how to pick out."""
    host = _host(url)
    if _on(host, "substack.com") or "substackcdn.com" in markdown:
        return "substack"
    if _on(host, "medium.com"):
        return "medium"
    return None


def _medium_author(url: str) -> str | None:
    """The handle a pasted Medium page belongs to: medium.com/@ada or ada.medium.com."""
    parsed = urlparse(url)
    host = _host(url)
    if host == "medium.com":
        first = parsed.path.strip("/").split("/")[0]
        return first[1:].lower() if first.startswith("@") and len(first) > 1 else None
    if host.endswith(".medium.com"):
        return host.removesuffix(".medium.com")
    return None


def _is_post_link(platform: str, page_url: str, href: str) -> bool:
    """Only the pasted person's own posts: profile and archive pages also link
    other writers' stories (recommendations, responses, "more from Medium")."""
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if platform == "substack":
        # A post lives on the newsletter's own host under /p/<slug>.
        return host == _host(page_url) and parsed.path.startswith("/p/") and len(parsed.path) > 3
    author = _medium_author(page_url)
    if not author:
        return False
    parts = parsed.path.strip("/").split("/")
    if host == f"{author}.medium.com":
        return len(parts) == 1 and bool(_MEDIUM_STORY.match(parts[0]))
    return (
        host == "medium.com" and len(parts) == 2 and parts[0].lower() == f"@{author}"
        and bool(_MEDIUM_STORY.match(parts[1]))
    )


def extract_posts(markdown: str, url: str, limit: int = POSTS_PER_SITE) -> list[dict]:
    """The newest posts on a newsletter or blog page: title (plus subtitle), link, platform."""
    platform = writing_platform(url, markdown)
    if not platform:
        return []
    by_href: dict[str, list[str]] = {}
    for m in _LINK.finditer(markdown):
        href = m.group("href").split("?")[0].split("#")[0]
        if not _is_post_link(platform, url, href):
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
        # The one Behance host the image proxy (cards-web api/img) serves.
        return host == "mir-s3-cdn-cf.behance.net" and parsed.path.startswith("/projects/")
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


# ── Product Hunt launches ────────────────────────────────────────────────────

# A link whose text has no brackets, so the alt text of a linked cover image
# ("[![Image 5: Orbit](…)](…)") is not mistaken for a product name.
_PH_LINK = re.compile(r"(?<!!)\[(?P<text>[^\[\]\n]{1,80})\]\((?P<href>https?://[^)\s]+)\)")
# A product page or a launch post, optionally followed by one of its sub-pages.
_PH_PRODUCT = re.compile(
    r"^https?://(?:www\.)?producthunt\.com/(?P<kind>products|posts)/(?P<slug>[a-z0-9][a-z0-9-]{0,80})(?:[/?#]|$)"
)
# An ATX heading: "## Made".
_ATX_HEADING = re.compile(r"^#{1,6}\s+(?P<text>.+?)\s*#*$")
# The underline of a setext heading, which Jina Reader also emits: "Made\n----".
_SETEXT_RULE = re.compile(r"^(?:=+|-+)$")
# Profile sections that list the person's own launches: "Made", "Maker history",
# "Products made", "Hunted", "Submitted", with or without a count after them.
# Upvotes, collections, stacks and followed products are other people's work.
_MAKER_HEADING = re.compile(
    r"^(?:made|maker(?: of| history)?|products made|hunted|hunter(?: history)?|submitted)\b", re.I,
)
# A bare upvote count under a product: "412", "3,201", "1.2K", "▲ 88", "88 upvotes".
_PH_UPVOTES = re.compile(r"^(?:▲\s*)?(?P<n>\d{1,3}(?:,\d{3})+|\d{1,7}(?:\.\d)?)(?P<k>[kK])?(?:\s+upvotes?)?$")
# Card chrome that sits where a tagline would: "Launched in 2021", "Follow", "12 reviews".
_PH_NOT_TAGLINE = re.compile(r"^(?:launched|featured|follow(?:ing)?|upvoted?|visit|maker|hunter|\d+ reviews?)\b", re.I)
# How many lines under a product's name to look for its tagline and upvotes.
_PH_DETAIL_LINES = 4
_PH_TAGLINE_MAX = 160


def _heading(lines: list[str], i: int) -> str | None:
    line = lines[i].strip()
    m = _ATX_HEADING.match(line)
    if m:
        return m.group("text")
    # Only a lone line counts: a rule right under a card's last line ("412\n---")
    # separates cards, it doesn't make "412" a heading.
    prev = lines[i - 1].strip() if i > 0 else ""
    nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
    return line if line and not prev and len(nxt) >= 3 and _SETEXT_RULE.match(nxt) else None


def _upvotes(line: str) -> int | None:
    m = _PH_UPVOTES.match(line)
    if not m:
        return None
    n = float(m.group("n").replace(",", ""))
    return int(n * 1000) if m.group("k") else int(n)


def _is_tagline(line: str) -> bool:
    return (
        not line.startswith(("[", "!", "#", "*", "-", "|", "<", "="))
        and len(line.split()) >= 2 and len(line) <= _PH_TAGLINE_MAX
        and not _PH_NOT_TAGLINE.match(line)
    )


def _names_maker(markdown: str, user: str) -> bool:
    """The page is the pasted person's: its body shows their @handle. A renamed or
    missing profile can land on a page of trending products instead."""
    body = markdown.split("Markdown Content:", 1)[-1]
    return re.search(rf"(?<!\w)@{re.escape(user)}(?![\w-])", body, re.I) is not None


def extract_launches(markdown: str, url: str, limit: int = LAUNCHES_PER_PROFILE) -> list[dict]:
    """Products a maker launched or hunted, read off their Product Hunt profile:
    name, tagline, link, upvotes (None when the page shows no count).

    Only the profile's Made / Hunted sections count. A page with no such section —
    which is what Product Hunt's bot check returns — gives an empty list."""
    user = producthunt_maker(url)
    if not user or not _names_maker(markdown, user):
        return []
    lines = markdown.splitlines()
    launches: list[dict] = []
    seen: set[str] = set()
    in_maker_section = False
    current: dict | None = None
    detail_lines = 0
    for i, raw in enumerate(lines):
        line = raw.strip()
        products = [(m, p) for m in _PH_LINK.finditer(line) if (p := _PH_PRODUCT.match(m.group("href")))]
        heading = _heading(lines, i)
        # A product name can itself be a heading ("### [Orbit](…)"): that stays in the section.
        if heading is not None and not products:
            in_maker_section = bool(_MAKER_HEADING.match(heading.strip("*_ ")))
            current = None
            continue
        if not in_maker_section:
            continue
        if products:
            link, product = products[0]
            name = " ".join(link.group("text").split())
            key = product.group("slug")
            current = None
            if key in seen or name.lower() in seen:
                continue
            # Stop at the next new product, not at the last one kept, so it still gets its tagline.
            if len(launches) == limit:
                break
            seen.update((key, name.lower()))
            current = {
                "name": name,
                "tagline": "",
                "url": f"https://www.producthunt.com/{product.group('kind')}/{key}",
                "upvotes": None,
                "source": "producthunt",
            }
            launches.append(current)
            detail_lines = 0
            continue
        if current is None or not line:
            continue
        detail_lines += 1
        if detail_lines > _PH_DETAIL_LINES:
            current = None
        elif current["upvotes"] is None and (votes := _upvotes(line)) is not None:
            current["upvotes"] = votes
        elif not current["tagline"] and _is_tagline(line):
            current["tagline"] = line
    return launches
