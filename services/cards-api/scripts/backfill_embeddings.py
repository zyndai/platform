import config
from models.card import AgentProfileCard
from services import embed


def main() -> None:
    sb = config.get_supabase()
    rows = (
        sb.table("agent_profile_cards")
        .select("id,card,embedding")
        .eq("status", "published")
        .execute()
        .data
        or []
    )
    backfilled = 0
    for row in rows:
        if row.get("embedding"):
            continue
        card = AgentProfileCard.model_validate(row["card"])
        try:
            emb = embed.embed_text(embed.card_search_text(card))
            sb.table("agent_profile_cards").update({"embedding": emb}).eq("id", row["id"]).execute()
            backfilled += 1
            print(f"embedded {row['id']} ({len(emb)} dims)")
        except Exception as exc:
            print(f"failed {row['id']}: {exc}")
    print(f"done: {backfilled} backfilled")


if __name__ == "__main__":
    main()
