import html
import re

import config
from models.card import AgentProfileCard, CardSynthesis, Source, WritingSample
from services import embed
from services.jobs import new_card_id, utcnow


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
            synth.identity.links.setdefault("github", html_url)
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
    }
    sb.table("agent_profile_cards").upsert(row, on_conflict="id").execute()
    return handle


def get_card_by_owner(email: str) -> tuple[AgentProfileCard, str] | None:
    """Return (card, handle) for the most recently created card owned by email."""
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle")
        .eq("owner_email", email)
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
) -> tuple[bool, str]:
    """Update a published card in-place after verifying ownership.

    Returns (False, handle) if the handle does not exist or ownership check fails.
    Returns (True, effective_handle) on success — effective_handle is new_handle if
    the rename succeeded, otherwise the original handle.

    Cards created before the ownership feature have `owner_email` NULL —
    the first authenticated editor claims them.
    """
    sb = config.get_supabase()
    check = (
        sb.table("agent_profile_cards")
        .select("owner_email")
        .eq("handle", handle)
        .execute()
    )
    if not check.data:
        return False, handle
    stored_owner = check.data[0].get("owner_email")
    if stored_owner and stored_owner != owner_email:
        return False, handle

    effective_handle = handle
    if new_handle:
        slug = re.sub(r"[^a-z0-9-]", "", new_handle.lower())[:30].strip("-")
        if len(slug) >= 2 and slug != handle:
            conflict = sb.table("agent_profile_cards").select("id").eq("handle", slug).execute()
            if not conflict.data:
                effective_handle = slug

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
        # Unowned legacy cards get claimed on first edit.
        "owner_email": stored_owner or owner_email,
    }
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
    """Backend-only refresh of the stored ZYND memory snapshot on a card row.

    Called by the periodic memory refresh cron, not by end users — no ownership
    check. Only the card JSON changes; the search embedding is left untouched
    (the memory section is not searchable content).
    """
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
    card.zynd_memory = zynd_memory
    card.updated_at = utcnow()
    sb.table("agent_profile_cards").update(
        {"card": card.model_dump(mode="json"), "updated_at": card.updated_at}
    ).eq("handle", handle).execute()
    return True


def list_published_rows(limit: int = 1000) -> list[dict]:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,embedding,owner_email")
        .eq("status", "published")
        .limit(limit)
        .execute()
    )
    return resp.data or []
