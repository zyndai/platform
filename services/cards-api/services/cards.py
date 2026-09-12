import re

import config
from models.card import AgentProfileCard, CardSynthesis, Source
from services import embed
from services.jobs import new_card_id, utcnow


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
    )


def pick_avatar(linkedin_avatar: str | None, x_avatar: str | None, github_avatar: str | None) -> str:
    """Deterministic avatar priority: LinkedIn > X > GitHub. First valid http URL wins."""
    for candidate in (linkedin_avatar, x_avatar, github_avatar):
        if candidate and str(candidate).startswith("http"):
            return str(candidate)
    return ""


def _row_to_card(row: dict) -> AgentProfileCard:
    data = dict(row["card"])
    if row.get("handle"):
        data["handle"] = row["handle"]
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
) -> str:
    handle = _assign_handle(handle_github, handle_x, card.identity.name, card.id)
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


def update_card(handle: str, card: AgentProfileCard, owner_email: str) -> bool:
    """Update a published card in-place after verifying ownership.

    Returns False (without modifying anything) if the handle does not exist
    or the stored owner_email belongs to a different user.

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
        return False
    stored_owner = check.data[0].get("owner_email")
    if stored_owner and stored_owner != owner_email:
        return False
    card.updated_at = utcnow()
    try:
        embedding = embed.embed_text(embed.card_search_text(card))
    except Exception:
        embedding = None
    sb.table("agent_profile_cards").update(
        {
            "card": card.model_dump(mode="json"),
            "status": card.status,
            "embedding": embedding,
            "updated_at": card.updated_at,
            # Unowned legacy cards get claimed on first edit.
            "owner_email": stored_owner or owner_email,
        }
    ).eq("handle", handle).execute()
    return True


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


def list_published_rows(limit: int = 1000) -> list[dict]:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card,handle,embedding")
        .eq("status", "published")
        .limit(limit)
        .execute()
    )
    return resp.data or []
