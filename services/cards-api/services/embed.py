import config

EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536


def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    client = config.get_llm_client()
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text[:8000])
    return list(resp.data[0].embedding)


def card_search_text(card) -> str:
    parts = [
        card.identity.name,
        card.identity.headline,
        card.identity.location,
        card.summary,
    ]
    parts += [s.name for s in card.skills]
    parts += [p.name for p in card.projects]
    parts += list(card.industries)
    if card.availability:
        parts.append(f"available {card.availability}")
    if card.experience_years:
        parts.append(f"{card.experience_years} years experience")
    return " ".join(p for p in parts if p)
