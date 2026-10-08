import hashlib
import hmac
import html
import logging
import re
import secrets

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


def _row_to_card(row: dict) -> AgentProfileCard:
    data = dict(row["card"])
    if row.get("handle"):
        data["handle"] = row["handle"]
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


def _is_claimed_row(row: dict) -> bool:
    return bool((row.get("owner_email") or "").strip())


def get_published_card(handle: str) -> tuple[AgentProfileCard, bool] | None:
    """(card, claimed). claimed is owner_email present; never expose the email."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,owner_email")
        .eq("handle", handle)
        .eq("status", "published")
        .execute()
    )
    rows = resp.data or []
    if not rows:
        try:
            resp = (
                sb.table("agent_profile_cards")
                .select("card,handle,owner_email")
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
    return _row_to_card(rows[0]), _is_claimed_row(rows[0])


def get_card_by_handle(handle: str) -> AgentProfileCard | None:
    found = get_published_card(handle)
    return found[0] if found else None


def linkedin_key(url: str) -> str:
    from urllib.parse import urlparse

    raw = (url or "").strip().lower().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else ""


def claimed_handle_set() -> set[str]:
    claimed, _known = claimed_index()
    return claimed


def claimed_index() -> tuple[set[str], bool]:
    """(claimed handles, True if owner_email was present on rows)."""
    rows = list_published_rows(columns="handle,owner_email")
    claimed: set[str] = set()
    known = False
    for row in rows:
        if "owner_email" in row:
            known = True
        handle = row.get("handle")
        if handle and (row.get("owner_email") or "").strip():
            claimed.add(handle)
    return claimed, known


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


def update_card_memory(handle: str, zynd_memory: list[dict] | None) -> bool:
    """Write the public memory snapshot and rebuild search text from it.

    None = not connected. [] = connected, nothing public. Embedding is
    recomputed so /ask and FTS-adjacent scoring see approved facts; OpenAI
    failures leave the previous embedding in place rather than blocking the
    snapshot write.
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
    card.zynd_memory = zynd_memory
    card.updated_at = utcnow()
    payload: dict = {"card": card.model_dump(mode="json"), "updated_at": card.updated_at}
    try:
        payload["embedding"] = embed.embed_text(embed.card_search_text(card))
    except Exception as exc:
        logger.warning("re-embed after memory update failed handle=%s err=%s", handle, exc)
    sb.table("agent_profile_cards").update(payload).eq("handle", handle).execute()
    return True


def claim_card(handle: str, owner_email: str, *, linkedin_url: str | None = None, claim_token: str | None = None) -> str:
    """Attach owner_email if LinkedIn URLs match or the claim token is valid.

    Returns 'ok', 'not_found', 'already_owned', 'mismatch', or 'need_linkedin'.
    """
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,owner_email,claim_token_hash")
        .eq("handle", handle)
        .execute()
    )
    if not resp.data:
        return "not_found"
    row = resp.data[0]
    stored_owner = (row.get("owner_email") or "").strip()
    if stored_owner:
        if stored_owner.lower() == owner_email.lower():
            return "ok"
        return "already_owned"
    card = _row_to_card(row)
    card_key = linkedin_key((card.identity.links or {}).get("linkedin") or "")
    offered_key = linkedin_key(linkedin_url or "")
    token_ok = can_claim(row.get("claim_token_hash"), claim_token)
    linkedin_ok = bool(card_key and offered_key and card_key == offered_key)
    if not linkedin_ok and not token_ok:
        if not card_key:
            return "need_linkedin"
        return "mismatch"
    sb.table("agent_profile_cards").update(
        {"owner_email": owner_email, "claim_token_hash": None, "updated_at": utcnow()}
    ).eq("handle", handle).execute()
    return "ok"


def hide_from_agents(handle: str) -> bool:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card")
        .eq("handle", handle)
        .execute()
    )
    if not resp.data:
        return False
    card = _row_to_card(resp.data[0])
    card.hidden_from_agents = True
    card.updated_at = utcnow()
    sb.table("agent_profile_cards").update(
        {"card": card.model_dump(mode="json"), "updated_at": card.updated_at}
    ).eq("handle", handle).execute()
    try:
        sb.table("takedown_requests").insert(
            {"handle": handle, "status": "pending", "created_at": utcnow()}
        ).execute()
    except Exception as exc:
        logger.warning("takedown_requests insert skipped handle=%s err=%s", handle, exc)
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
