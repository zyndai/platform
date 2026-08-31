import config
from models.card import AgentProfileCard, CardSynthesis, Source
from services.jobs import new_card_id, utcnow


def assemble_card(
    synth: CardSynthesis,
    github_data: dict | None,
    github_handle: str | None,
    x_handle: str | None,
    resume_used: bool,
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

    return AgentProfileCard(
        id=card_id,
        status="pending_review",
        created_at=now,
        updated_at=now,
        identity=synth.identity,
        citation_snippet=synth.citation_snippet,
        summary=synth.summary,
        skills=synth.skills,
        projects=synth.projects,
        writing_samples=synth.writing_samples,
        searchable_facts=synth.searchable_facts,
        sources=synth.sources,
    )


def _row_to_card(row: dict) -> AgentProfileCard:
    return AgentProfileCard.model_validate(row["card"])


def insert_card(card: AgentProfileCard, handle_github: str | None, handle_x: str | None) -> None:
    sb = config.get_supabase()
    sb.table("agent_profile_cards").insert(
        {
            "id": card.id,
            "status": card.status,
            "handle_github": handle_github,
            "handle_x": handle_x,
            "card": card.model_dump(mode="json"),
        }
    ).execute()


def get_card(card_id: str) -> AgentProfileCard | None:
    sb = config.get_supabase()
    resp = (
        sb.table("agent_profile_cards")
        .select("card")
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
        .select("card")
        .eq("status", "published")
        .text_search("search_tsv", q)
        .limit(limit)
        .execute()
    )
    rows = resp.data or []
    if not rows and q:
        resp = (
            sb.table("agent_profile_cards")
            .select("card")
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
        .select("card")
        .eq("status", "published")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_row_to_card(r) for r in (resp.data or [])]
