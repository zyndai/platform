import hashlib
import hmac
import html
import logging
import re
import secrets
from urllib.parse import urlparse

import config
from models.card import AgentProfileCard, CardSynthesis, Source, WritingSample
from services import embed
from services.jobs import new_card_id, utcnow

logger = logging.getLogger(__name__)


def new_claim_token() -> tuple[str, str]:
    """(token, sha256 hex) for an unowned card. The token goes to the anonymous
    publisher once; only its hash is stored."""
    token = secrets.token_urlsafe(24)
    return token, hash_claim_token(token)


def linkedin_handle_from_url(url: str | None) -> str | None:
    """Normalised LinkedIn public handle from a profile URL, or None.

    "https://www.linkedin.com/in/Chandan-Kumar/" → "chandan-kumar". Trailing
    slugs like /details/experience are ignored.
    """
    if not url or not url.strip():
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host not in ("linkedin.com", "www.linkedin.com", "in.linkedin.com") and not host.endswith(".linkedin.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    first = parts[0].lower()
    if first in ("in", "pub", "company", "school", "posts", "feed"):
        if len(parts) < 2:
            return None
        first = parts[1].lower()
    return first


def owner_user_metadata_linkedin(principal) -> str | None:
    """Best-effort LinkedIn handle for a signed-in Supabase user.

    Supabase's linkedin_oidc provider puts the public handle in
    user_metadata.preferred_username (and a numeric id in linkedin_id); the
    older generic OAuth flow sometimes has full_name only. Return None when
    nothing usable is present so the claim check can refuse cleanly.
    """
    md = getattr(principal, "user_metadata", None) or {}
    for key in ("preferred_username", "user_name", "linkedin_handle", "linkedin"):
        value = (md.get(key) or "").strip()
        if value:
            return value.lower()
    return None


def hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def can_claim(stored_hash: str | None, claim_token: str | None) -> bool:
    """May a signed-in user take ownership of an unowned card?"""
    if stored_hash:
        return bool(claim_token) and hmac.compare_digest(hash_claim_token(claim_token), stored_hash)
    return config.LEGACY_UNOWNED_CLAIM


_HTML_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+", re.I)


def clean_excerpt(text: str, limit: int = 500) -> str:
    """Unescape HTML, strip tags, collapse whitespace. Safe for card quotes."""
    t = html.unescape(str(text or ""))
    t = _HTML_TAG.sub(" ", t)
    t = t.replace("\u00a0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:limit]


def is_thin_excerpt(text: str) -> bool:
    """True when the excerpt is URL/emoji junk with almost no words."""
    raw = text or ""
    without_urls = _URL.sub(" ", raw)
    letters = re.sub(r"[^\w]", "", without_urls, flags=re.UNICODE)
    if len(letters) < 8:
        return True
    if _URL.search(raw) and len(letters) < 16:
        return True
    return False


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:50]


def _assign_handle(github_handle: str | None, x_handle: str | None, name: str, card_id: str) -> str:
    """Derive canonical slug: github > x > name, suffix card_id on collision."""
    base = (
        github_handle.lower() if github_handle
        else x_handle.lower() if x_handle
        else _slugify(name or "user")
    ) or "user"

    sb = config.get_supabase()
    handle = base
    for suffix in ("", f"-{card_id[:4]}"):
        handle = base + suffix
        resp = sb.table("agent_profile_cards").select("id").eq("handle", handle).execute()
        if not (resp.data):
            return handle
    return f"{base}-{card_id}"


def _try_custom_handle(slug: str, card_id: str) -> str:
    """Use slug if valid + available; otherwise append card_id suffix."""
    import re
    slug = re.sub(r"[^a-z0-9-]", "", slug.lower())[:30].strip("-")
    if len(slug) < 2:
        return f"user-{card_id[:6]}"
    sb = config.get_supabase()
    for candidate in (slug, f"{slug}-{card_id[:4]}", f"{slug}-{card_id}"):
        resp = sb.table("agent_profile_cards").select("id").eq("handle", candidate).execute()
        if not resp.data:
            return candidate
    return f"{slug}-{card_id}"


def assemble_card(
    synth: CardSynthesis,
    github_data: dict | None,
    github_handle: str | None,
    x_handle: str | None,
    resume_used: bool,
    linkedin_scraped: bool = False,
    x_stats: dict | None = None,
    linkedin_stats: dict | None = None,
    contribution_stats: dict | None = None,
    work_experience: list[dict] | None = None,
) -> AgentProfileCard:
    card_id = new_card_id()
    now = utcnow()

    sources: list[Source] = []
    if github_data:
        user = github_data.get("user", {})
        html_url = user.get("html_url")
        if html_url:
            synth.identity.links["github"] = html_url  # the API's URL, not the LLM's guess
        sources.append(
            Source(
                platform="github",
                url=html_url,
                scraped_at=now,
                method="github_api",
            )
        )
    if resume_used:
        sources.append(
            Source(platform="resume", url=None, scraped_at=now, method="user_upload")
        )
    if linkedin_scraped:
        sources.append(
            Source(platform="linkedin", url=None, scraped_at=now, method="http_fetch")
        )
    if x_handle:
        sources.append(
            Source(
                platform="x",
                url=f"https://x.com/{x_handle}",
                scraped_at=now,
                method="pending",
            )
        )
    synth.sources = sources

    # If X scraper didn't return handle but we have x_handle, fill it in
    if x_stats and not x_stats.get("handle") and x_handle:
        x_stats = {**x_stats, "handle": f"@{x_handle}"}
    elif x_handle and not x_stats:
        x_stats = None  # leave as None — page will infer from identity.links.x

    return AgentProfileCard(
        id=card_id,
        status="pending_review",
        created_at=now,
        updated_at=now,
        identity=synth.identity,
        citation_snippet=synth.citation_snippet,
        summary=synth.summary,
        affiliations=synth.affiliations,
        skills=synth.skills,
        projects=synth.projects,
        writing_samples=synth.writing_samples,
        searchable_facts=synth.searchable_facts,
        sources=synth.sources,
        experience_years=synth.experience_years,
        industries=synth.industries,
        availability=synth.availability,
        working_on=synth.working_on,
        can_help_with=synth.can_help_with,
        connect_with=synth.connect_with,
        love_talking_about=synth.love_talking_about,
        github_stats=synth.github_stats,
        x_stats=x_stats,
        linkedin_stats=linkedin_stats,
        contribution_stats=contribution_stats,
        work_experience=work_experience or None,
    )


def pick_avatar(linkedin_avatar: str | None, x_avatar: str | None, github_avatar: str | None) -> str:
    """Deterministic avatar priority: LinkedIn > X > GitHub. First valid http URL wins."""
    for candidate in (linkedin_avatar, x_avatar, github_avatar):
        if candidate and str(candidate).startswith("http"):
            return str(candidate)
    return ""


def refresh_avatar(card: dict, linkedin_avatar: str | None, x_avatar: str | None) -> bool:
    """Patch identity.avatar_url from freshly scraped platform avatars.

    Only overwrites when a scraped avatar is present and different; the existing
    avatar (e.g. a GitHub fallback) is left untouched when neither platform
    returned a usable one. Returns True when the card changed."""
    identity = dict(card.get("identity") or {})
    candidate = pick_avatar(linkedin_avatar, x_avatar, None)
    if candidate and candidate != identity.get("avatar_url"):
        identity["avatar_url"] = candidate
        card["identity"] = identity
        return True
    return False


def apply_linkedin_avatar(card: dict, avatar: str | None) -> str:
    """Sync a card's avatar after a fresh LinkedIn scrape.

    Photo present: store it in linkedin_stats and identity.avatar_url.
    Photo removed (avatar is None): drop the stale LinkedIn avatar so the
    frontend falls back to GitHub/X instead of a dead signed URL.
    Returns 'set' | 'cleared' | 'none' (nothing changed)."""
    if avatar:
        stats = dict(card.get("linkedin_stats") or {})
        identity = dict(card.get("identity") or {})
        if stats.get("avatar") == avatar and identity.get("avatar_url") == avatar:
            return "none"
        stats["avatar"] = avatar
        card["linkedin_stats"] = stats
        identity["avatar_url"] = avatar
        card["identity"] = identity
        return "set"
    changed = False
    stats = dict(card.get("linkedin_stats") or {})
    if "avatar" in stats:
        del stats["avatar"]
        card["linkedin_stats"] = stats
        changed = True
    identity = dict(card.get("identity") or {})
    if identity.get("avatar_url") and "licdn" in str(identity["avatar_url"]):
        identity["avatar_url"] = ""
        card["identity"] = identity
        changed = True
    return "cleared" if changed else "none"


def merge_scraped_posts(
    llm_samples: list[WritingSample],
    x_posts: list[dict] | None,
    linkedin_posts: list[dict] | None,
    cap: int = 10,
) -> list[WritingSample]:
    """Guarantee both platforms appear in writing_samples.

    The LLM under-fills when both X and LinkedIn sections are present, so
    real scraped posts (dated, with URLs) are injected deterministically,
    interleaved X/LinkedIn-first, and LLM picks fill the remaining slots.
    """
    def _key(w: WritingSample) -> str:
        url = (w.url or "").strip().rstrip("/")
        if url:
            return url
        return f"{w.platform}:{(w.excerpt or '').strip()[:80]}"

    result: list[WritingSample] = []
    seen: set[str] = set()

    def add(w: WritingSample) -> None:
        key = _key(w)
        if key in seen:
            return
        seen.add(key)
        result.append(w)

    def norm(posts: list[dict] | None, platform: str) -> list[WritingSample]:
        out: list[WritingSample] = []
        for p in posts or []:
            if not isinstance(p, dict):
                continue
            excerpt = clean_excerpt(str(p.get("excerpt") or ""))
            if not excerpt or is_thin_excerpt(excerpt):
                continue
            out.append(WritingSample(
                platform=platform,
                excerpt=excerpt,
                url=str(p.get("url") or ""),
                posted_at=str(p.get("posted_at") or ""),
            ))
        return out

    x_norm = norm(x_posts, "x")
    li_norm = norm(linkedin_posts, "linkedin")

    interleaved: list[WritingSample] = []
    for i in range(max(len(x_norm), len(li_norm))):
        if i < len(x_norm):
            interleaved.append(x_norm[i])
        if i < len(li_norm):
            interleaved.append(li_norm[i])

    for w in interleaved:
        if len(result) >= cap:
            break
        add(w)
    for w in llm_samples:
        if len(result) >= cap:
            break
        add(w)
    return result


def dedupe_memory_facts(facts: list[dict] | None) -> list[dict] | None:
    """Drop duplicate memory facts keyed on canonical predicate + lowercased object.

    The memory layer can return the same fact from several sources ("Stocks"
    and "stocks" as separate rows); dedupe so the public card and the edit page
    agree on one entry per fact.
    """
    if facts is None:
        return None
    if not facts:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for fact in facts:
        if not isinstance(fact, dict):
            out.append(fact)
            continue
        predicate = str(fact.get("predicate", "") or "")
        object_ = str(fact.get("object", "") or "").strip()
        if not predicate and not object_:
            # Free-form fact without a canonical key — keep as-is.
            out.append(fact)
            continue
        key = (predicate, object_.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def _row_to_card(row: dict) -> AgentProfileCard:
    data = dict(row["card"])
    if row.get("handle"):
        data["handle"] = row["handle"]
    if "zynd_memory" in data and isinstance(data.get("zynd_memory"), list):
        data["zynd_memory"] = dedupe_memory_facts(data["zynd_memory"])
    samples = data.get("writing_samples")
    if isinstance(samples, list):
        cleaned: list = []
        for s in samples:
            if not isinstance(s, dict):
                continue
            item = dict(s)
            item["excerpt"] = clean_excerpt(item.get("excerpt") or "")
            if item["excerpt"] and not is_thin_excerpt(item["excerpt"]):
                cleaned.append(item)
        data["writing_samples"] = cleaned
    jobs = data.get("work_experience")
    if isinstance(jobs, list):
        from scraping import linkedin as linkedin_scraper
        for job in jobs:
            if isinstance(job, dict) and job.get("description"):
                job["description"] = linkedin_scraper._clean_job_description(job.get("description"))
    return AgentProfileCard.model_validate(data)


def get_card_by_handle(handle: str) -> AgentProfileCard | None:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("handle", handle)
        .eq("status", "published")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        # The handle may have been renamed — resolve through the previous
        # handles recorded in the card JSON so old links keep working.
        try:
            resp = (
                sb.table("agent_profile_cards")
                .select("card,handle")
                .contains("card", {"previous_handles": [handle]})
                .eq("status", "published")
                .limit(1)
                .execute()
            )
            rows = resp.data or []
        except Exception as exc:
            logger.warning("previous-handle lookup failed handle=%s err=%s", handle, exc)
            rows = []
    if not rows:
        return None
    return _row_to_card(rows[0])


def insert_card(
    card: AgentProfileCard,
    handle_github: str | None,
    handle_x: str | None,
    scrape_raw: dict | None = None,
    user_intent: dict | None = None,
    owner_email: str | None = None,
    custom_handle: str | None = None,
    claim_token_hash: str | None = None,
    owner_user_id: str | None = None,
) -> str:
    handle = (
        _try_custom_handle(custom_handle, card.id)
        if custom_handle
        else _assign_handle(handle_github, handle_x, card.identity.name, card.id)
    )
    try:
        embedding = embed.embed_text(embed.card_search_text(card))
    except Exception:
        embedding = None
    sb = config.get_supabase()
    row: dict = {
        "id": card.id,
        "status": card.status,
        "handle_github": handle_github,
        "handle_x": handle_x,
        "handle": handle,
        "card": card.model_dump(mode="json"),
        "embedding": embedding,
        "scrape_raw": scrape_raw,
        "user_intent": user_intent,
        "owner_email": owner_email,
        "claim_token_hash": None if owner_email else claim_token_hash,
    }
    if owner_user_id and config.WRITES_OWNER_USER_ID:
        row["owner_user_id"] = owner_user_id
    sb.table("agent_profile_cards").upsert(row, on_conflict="id").execute()
    return handle


def get_card_by_owner(email: str) -> tuple[AgentProfileCard, str] | None:
    """Return (card, handle) for the owner's card.

    Published cards first. When the owner has no *published* card, fall back
    to their most recent row of any status — a card left `pending_review` by
    the old dashboard flow (or by the xmfj -> aafo data copy) must never make
    the signed-in owner look like they have no card at all. The status rides
    along in the card JSON, so the frontend can offer a "publish" action
    instead of pretending the profile doesn't exist."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .ilike("owner_email", _like_literal(email))
        .eq("status", "published")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        resp = (
            sb.table("agent_profile_cards")
            .select("card,handle")
            .ilike("owner_email", _like_literal(email))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
    if not rows:
        return None
    return _row_to_card(rows[0]), rows[0]["handle"]


def _like_literal(value: str) -> str:
    """Escape LIKE wildcards so ilike() is a case-insensitive exact match
    (emails often contain `_`, which LIKE would treat as "any character")."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _postgrest_quote(value: str) -> str:
    """Quote a value inside a PostgREST or() filter so commas, dots or
    parentheses in it can't change the filter's meaning."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def claim_candidates_by_linkedin(linkedin_url: str) -> list[dict]:
    """S08 claim-first: published cards whose LinkedIn URL matches, so onboarding
    can offer "claim it" instead of building a duplicate. Unowned cards only —
    a claimed card is the caller's own (or someone else's, never claimable).

    Returns [{"handle", "name", "headline", "claimed"}...], never owner_email."""
    handle = linkedin_handle_from_url(linkedin_url)
    if not handle:
        return []
    sb = config.get_supabase()
    # Normalise the stored URL's path the same way the matcher does: compare the
    # LinkedIn handle, not the raw URL (trailing slashes / locale prefixes vary).
    rows = list_published_rows(columns="card,handle,owner_email")
    out: list[dict] = []
    for row in rows:
        card_url = ((row.get("card") or {}).get("identity") or {}).get("links", {}).get("linkedin")
        if linkedin_handle_from_url(card_url) != handle:
            continue
        if _claimed_from_row(row):
            continue
        identity = (row.get("card") or {}).get("identity") or {}
        out.append({
            "handle": row.get("handle"),
            "name": identity.get("name") or "",
            "headline": identity.get("headline") or "",
            "claimed": False,
        })
    return out


def get_card_by_social_handle(
    handle_github: str | None,
    handle_x: str | None,
    linkedin_url: str | None = None,
) -> tuple[AgentProfileCard, str] | None:
    """Return (card, handle) for the most recent published card matching any
    of the given identities.

    Used by onboard.py's publish_card to detect an anonymous re-publish of the
    same identity so it never forks a second card (get_card_by_owner is the
    equivalent check for a signed-in publish). LinkedIn was added because the
    same person republishing while signed in with a different email than their
    old card used to fork a duplicate profile — a stale "twin" that their
    "my profile" button never points at."""
    if not handle_github and not handle_x and not linkedin_url:
        return None
    sb = config.get_supabase()
    filters = []
    if handle_github:
        filters.append(f"handle_github.eq.{_postgrest_quote(handle_github)}")
    if handle_x:
        filters.append(f"handle_x.eq.{_postgrest_quote(handle_x)}")
    if linkedin_url:
        filters.append(f"card->identity->links->>linkedin.eq.{_postgrest_quote(linkedin_url)}")
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("status", "published")
        .or_(",".join(filters))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    return _row_to_card(rows[0]), rows[0]["handle"]


def update_card(
    handle: str,
    card: AgentProfileCard,
    owner_email: str,
    new_handle: str | None = None,
    claim_token: str | None = None,
    owner_user_id: str | None = None,
) -> tuple[bool, str]:
    """Update a published card in-place after verifying ownership.

    Returns (False, handle) if the handle does not exist or ownership check fails.
    Returns (True, effective_handle) on success — effective_handle is new_handle if
    the rename succeeded, otherwise the original handle.

    Unowned cards (anonymous publish) are claimed by the first signed-in editor
    who presents the one-time claim token issued at publish. Unowned cards from
    before claim tokens existed can only be claimed when LEGACY_UNOWNED_CLAIM is on.
    """
    sb = config.get_supabase()
    check = (
        sb.table("agent_profile_cards")
        .select("owner_email,claim_token_hash")
        .eq("handle", handle)
        .execute()
    )
    if not check.data:
        return False, handle
    stored_owner = check.data[0].get("owner_email")
    if stored_owner and stored_owner.lower() != owner_email.lower():
        return False, handle
    if not stored_owner and not can_claim(check.data[0].get("claim_token_hash"), claim_token):
        logger.warning("claim refused handle=%s (missing or wrong claim token)", handle)
        return False, handle

    effective_handle = handle
    if new_handle:
        slug = re.sub(r"[^a-z0-9-]", "", new_handle.lower())[:30].strip("-")
        if len(slug) >= 2 and slug != handle:
            conflict = sb.table("agent_profile_cards").select("id").eq("handle", slug).execute()
            if not conflict.data:
                effective_handle = slug

    if effective_handle != handle:
        # Keep the old handle resolving: record it in the card JSON so
        # get_card_by_handle can find renamed cards and the web layer can
        # redirect old links to the canonical handle.
        previous = card.previous_handles or []
        if handle not in previous:
            card.previous_handles = [handle, *previous][:8]

    card.updated_at = utcnow()
    try:
        embedding = embed.embed_text(embed.card_search_text(card))
    except Exception:
        embedding = None

    update_payload: dict = {
        "card": card.model_dump(mode="json"),
        "status": card.status,
        "embedding": embedding,
        "updated_at": card.updated_at,
        # Unowned cards are claimed here (claim token already checked above).
        "owner_email": stored_owner or owner_email,
    }
    if not stored_owner:
        update_payload["claim_token_hash"] = None
    if owner_user_id and config.WRITES_OWNER_USER_ID:
        update_payload["owner_user_id"] = owner_user_id
    if effective_handle != handle:
        update_payload["handle"] = effective_handle

    sb.table("agent_profile_cards").update(update_payload).eq("handle", handle).execute()
    return True, effective_handle


def get_card(card_id: str) -> AgentProfileCard | None:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("id", card_id)
        .eq("status", "published")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        return None
    return _row_to_card(rows[0])


def search_cards(q: str, limit: int = 50) -> list[AgentProfileCard]:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("status", "published")
        .text_search("search_tsv", q)
        .limit(limit)
        .execute()
    )
    rows = resp.data or []
    if not rows and q:
        resp = (
            sb.table("agent_profile_cards")
            .select("card,handle")
            .eq("status", "published")
            .ilike("card->>summary", f"%{q}%")
            .limit(limit)
            .execute()
        )
        rows = resp.data or []
    return [_row_to_card(r) for r in rows]


def list_published(limit: int = 1000) -> list[AgentProfileCard]:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("status", "published")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_row_to_card(r) for r in (resp.data or [])]


def _claimed_from_row(row: dict) -> bool:
    """A card is "claimed" when an owner has taken it over (owner_email set).
    The email itself is never exposed — only this boolean."""
    return bool((row.get("owner_email") or "").strip())


def card_is_claimed(handle: str) -> bool | None:
    """Claimed flag for one published card; None when the card doesn't exist."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("owner_email")
        .eq("handle", handle)
        .eq("status", "published")
        .execute()
    )
    if not resp.data:
        return None
    return _claimed_from_row(resp.data[0])


def claimed_by_handles(handles: list[str]) -> dict[str, bool]:
    """Bulk claimed lookup for search/directory responses. The email itself is
    never returned — only the boolean."""
    if not handles:
        return {}
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("handle,owner_email")
        .in_("handle", handles)
        .execute()
    )
    return {r["handle"]: _claimed_from_row(r) for r in (resp.data or [])}


def get_card_by_handle_public(handle: str) -> dict | None:
    """Card dict with the `claimed` flag, for public (unauthenticated) reads."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,owner_email,alias")
        .eq("handle", handle)
        .eq("status", "published")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        # The handle may have been renamed — resolve through the previous
        # handles recorded in the card JSON so old links keep working.
        try:
            resp = (
                sb.table("agent_profile_cards")
                .select("card,handle,owner_email,alias")
                .contains("card", {"previous_handles": [handle]})
                .eq("status", "published")
                .limit(1)
                .execute()
            )
            rows = resp.data or []
        except Exception as exc:
            logger.warning("previous-handle lookup failed handle=%s err=%s", handle, exc)
            rows = []
    if not rows:
        return None
    card = _row_to_card(rows[0])
    return {
        **card.model_dump(mode="json"),
        "claimed": _claimed_from_row(rows[0]),
        "alias": rows[0].get("alias"),
    }


def list_published_public(limit: int = 1000) -> list[dict]:
    """All published cards as dicts with `claimed`, for the website's own
    directory/llms/sitemap surfaces (never includes owner_email)."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,owner_email,alias")
        .eq("status", "published")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    out: list[dict] = []
    for r in resp.data or []:
        card = _row_to_card(r)
        out.append({
            **card.model_dump(mode="json"),
            "claimed": _claimed_from_row(r),
            "alias": r.get("alias"),
        })
    return out


def claim_card_by_owner(handle: str, principal: dict) -> tuple[bool, str]:
    """Claim an unowned card when the signed-in LinkedIn identity matches the
    card's LinkedIn URL. Returns (claimed, message).

    Kept separate from the legacy claim-token path (update_card): this one is
    driven by the S03 "Claim with LinkedIn" CTA and requires the OAuth identity
    to match, not a one-time token.
    """
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("owner_email,claim_token_hash,card,status")
        .eq("handle", handle)
        .execute()
    )
    if not resp.data:
        return False, "card not found"
    row = resp.data[0]
    if _claimed_from_row(row):
        return False, "this card is already claimed"
    owner_email = (getattr(principal, "email", "") or "").strip()
    if not owner_email:
        return False, "signed-in account has no email"

    card = _row_to_card(row)
    card_linkedin = linkedin_handle_from_url(card.identity.links.get("linkedin"))
    user_linkedin = owner_user_metadata_linkedin(principal)
    if not card_linkedin:
        return False, "this card has no LinkedIn profile to match against"
    if not user_linkedin:
        return False, "your LinkedIn identity could not be read — sign in with LinkedIn and try again"
    if card_linkedin != user_linkedin:
        return False, "your LinkedIn account does not match this card's LinkedIn profile"

    sb.table("agent_profile_cards").update(
        {"owner_email": owner_email, "claim_token_hash": None}
    ).eq("handle", handle).execute()
    return True, "claimed"


# S07: short share alias. Paths the top-level /[alias] redirect route must
# never swallow; static routes win in Next, but rejecting these keeps the
# redirect surface unambiguous.
RESERVED_ALIASES = {
    "p", "find", "directory", "search", "api", "create", "for-ai", "auth",
    "profile", "tag", "edit", "onboard", "mcp", "dashboard", "settings",
    "home", "about", "contact", "help", "login", "logout", "account", "cards",
    "zynd", "www", "assets", "images", "icons", "icon", "apple-icon",
    "favicon.ico", "llms.txt", "llms-full.txt", "agents.txt", "sitemap.xml",
    "robots.txt", "data.json", "opengraph-image", "_next", "web",
}

_ALIAS_RE = re.compile(r"[^a-z0-9-]")


def normalize_alias(raw: str) -> str:
    """Slug-ify a proposed alias the same way handles are slug-ified."""
    return _ALIAS_RE.sub("", (raw or "").lower())[:30].strip("-")


def set_card_alias(handle: str, raw_alias: str | None, owner_email: str) -> tuple[bool, str, str | None]:
    """Set (or clear) a card's short alias. Owner-only; validates reserved
    words and uniqueness. Returns (ok, message, final_alias)."""
    slug = normalize_alias(raw_alias or "")
    sb = config.get_supabase()
    if raw_alias and (len(slug) < 2 or len(slug) > 30):
        return False, "alias must be 2–30 letters, numbers, or hyphens", None
    if slug and slug in RESERVED_ALIASES:
        return False, f'"{slug}" is reserved — pick another alias', None
    if slug:
        clash = (
            sb.table("agent_profile_cards")
            .select("id")
            .or_(f"alias.eq.{slug},handle.eq.{slug}")
            .execute()
        )
        if clash.data:
            return False, f'"{slug}" is taken — pick another alias', None
    stored = (
        sb.table("agent_profile_cards")
        .select("owner_email")
        .eq("handle", handle)
        .execute()
    )
    if not stored.data:
        return False, "card not found", None
    if (stored.data[0].get("owner_email") or "").strip().lower() != (owner_email or "").strip().lower():
        return False, "not the card owner", None
    sb.table("agent_profile_cards").update({"alias": slug or None}).eq("handle", handle).execute()
    return True, "saved", slug or None


def get_card_by_alias(alias: str) -> dict | None:
    """Public card dict (with `claimed`) for a short alias, or None."""
    slug = normalize_alias(alias)
    if not slug:
        return None
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,owner_email,alias")
        .eq("alias", slug)
        .eq("status", "published")
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    row = resp.data[0]
    card = _row_to_card(row)
    return {**card.model_dump(mode="json"), "claimed": _claimed_from_row(row), "alias": row.get("alias")}


def request_takedown(handle: str, requester_user_id: str | None, note: str | None) -> bool:
    """Record a "not me" report and hide the card from every public surface
    immediately by moving it out of `published` status (takedown review queue
    decides restore vs delete)."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("id")
        .eq("handle", handle)
        .eq("status", "published")
        .execute()
    )
    if not resp.data:
        return False
    try:
        sb.table("takedown_requests").insert(
            {
                "handle": handle,
                "requester_user_id": requester_user_id,
                "note": (note or "").strip()[:1000] or None,
                "status": "pending",
            }
        ).execute()
    except Exception as exc:
        logger.warning("takedown insert failed handle=%s err=%s", handle, exc)
    sb.table("agent_profile_cards").update({"status": "takedown_requested"}).eq("handle", handle).execute()
    return True


def update_card_memory(handle: str, zynd_memory: list[dict] | None) -> bool:
    """Backend-only refresh of the stored ZYND memory snapshot on a card row.

    Called by the periodic memory refresh cron, not by end users — no ownership
    check. None = not connected (clears the snapshot). [] = connected, nothing
    public. The search embedding is recomputed so /ask sees approved facts;
    an embed failure leaves the previous embedding in place.
    """
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,embedding")
        .eq("handle", handle)
        .execute()
    )
    if not resp.data:
        return False
    card = _row_to_card(resp.data[0])
    card.zynd_memory = dedupe_memory_facts(zynd_memory)
    card.updated_at = utcnow()
    payload: dict = {"card": card.model_dump(mode="json"), "updated_at": card.updated_at}
    try:
        from services import embed

        vec = embed.embed_text(embed.card_search_text(card))
        if vec:
            payload["embedding"] = vec
    except Exception as exc:
        logger.warning("re-embed after memory update failed handle=%s err=%s", handle, exc)
    sb.table("agent_profile_cards").update(payload).eq("handle", handle).execute()
    return True


def list_published_rows(
    limit: int | None = None,
    columns: str = "card,handle,embedding,owner_email",
    page_size: int = 1000,
) -> list[dict]:
    """All published rows (or the first `limit`), paged so PostgREST's per-request
    row cap never silently truncates the result."""
    sb = config.get_supabase()
    rows: list[dict] = []
    start = 0
    while limit is None or len(rows) < limit:
        end = start + page_size - 1
        if limit is not None:
            end = min(end, limit - 1)
        page = (
            sb.table("agent_profile_cards")
            .select(columns)
            .eq("status", "published")
            .order("id")
            .range(start, end)
            .execute()
        ).data or []
        rows.extend(page)
        if len(page) < end - start + 1:
            break
        start = end + 1
    return rows
