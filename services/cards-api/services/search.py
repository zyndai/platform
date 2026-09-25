import json
import logging

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services.embed import card_search_text, embed_text

logger = logging.getLogger(__name__)

# Per source (vector + full text) candidates handed to the Python scorer.
CANDIDATES_PER_SOURCE = 200


def _parse_embedding(raw) -> list[float]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [float(x) for x in raw]
    if isinstance(raw, str):
        try:
            return [float(x) for x in json.loads(raw)]
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _candidates(q: str, query_vec: list[float]) -> list[dict]:
    """Rows to score: {"card", "handle", "similarity"?, "embedding"?}.

    With a query, the SQL functions in db/patch_search_rpc.sql return the top
    matches by vector similarity (HNSW) and by full-text rank. Filter-only
    searches — or a database without those functions yet — page through every
    published card.
    """
    if q:
        sb = config.get_supabase()
        try:
            by_id: dict[str, dict] = {}
            if query_vec:
                resp = sb.rpc("match_cards", {"query_embedding": query_vec, "match_count": CANDIDATES_PER_SOURCE}).execute()
                for r in resp.data or []:
                    by_id[r["id"]] = {"card": r["card"], "handle": r["handle"], "similarity": r.get("similarity")}
            resp = sb.rpc("search_cards_fts", {"q": q, "match_count": CANDIDATES_PER_SOURCE}).execute()
            for r in resp.data or []:
                by_id.setdefault(r["id"], {"card": r["card"], "handle": r["handle"]})
            return list(by_id.values())
        except Exception as exc:  # noqa: BLE001 — functions not deployed yet: degrade, don't fail search
            logger.warning("search RPCs unavailable (%s); falling back to a full scan", exc)
    return cards_service.list_published_rows(columns="card,handle,embedding")


def search_agents(
    q: str = "",
    role: str = "",
    location: str = "",
    skills: str = "",
    industry: str = "",
    availability: str = "",
    experience_min: int | None = None,
    limit: int = 10,
) -> list[dict]:
    query_vec = embed_text(q) if q else []
    rows = _candidates(q, query_vec)
    q_tokens = _norm(q).split() if q else []
    skill_list = [s.strip().lower() for s in skills.split(",") if s.strip()] if skills else []
    industry_norm = _norm(industry)
    location_norm = _norm(location)
    role_norm = _norm(role)
    availability_norm = _norm(availability)

    results = []
    for row in rows:
        card_data = row.get("card") or {}
        try:
            card = AgentProfileCard.model_validate(card_data)
        except Exception:
            continue
        if row.get("handle"):
            card.handle = row["handle"]
        search_text = card_search_text(card).lower()

        score = 0.0
        reasons: list[str] = []

        sim = row.get("similarity")
        if sim is None and query_vec:
            sim = _cosine(query_vec, _parse_embedding(row.get("embedding")))
        if query_vec and sim:
            score += sim * 0.5
            if sim > 0.6:
                reasons.append("Strong overall match for your query")

        if q_tokens:
            hits = [t for t in q_tokens if t in search_text]
            if hits:
                score += 0.25 * (len(hits) / len(q_tokens))
                reasons.append("Matches your search terms")

        if role_norm and (role_norm in _norm(card.identity.headline) or role_norm in search_text):
            score += 0.25
            reasons.append(card.identity.headline or "Role match")

        if location_norm and location_norm in _norm(card.identity.location):
            score += 0.3
            reasons.append(f"Based in {card.identity.location}")

        matched_skills = [
            sk for sk in skill_list
            if any(sk in s.name.lower() or s.name.lower() in sk for s in card.skills)
        ]
        if skill_list and matched_skills:
            score += 0.25 * (len(matched_skills) / len(skill_list))
            reasons.append("Skills: " + ", ".join(matched_skills))

        if industry_norm and any(industry_norm in _norm(i) for i in card.industries):
            score += 0.2
            reasons.append("Industry: " + ", ".join(card.industries))

        if availability_norm and availability_norm in _norm(card.availability):
            score += 0.2
            reasons.append(f"Available for {card.availability}")

        if experience_min is not None and card.experience_years and card.experience_years >= experience_min:
            score += 0.15
            reasons.append(f"{card.experience_years} years experience")

        results.append(
            {
                "agent_id": card.id,
                "handle": card.handle,
                "name": card.identity.name,
                "headline": card.identity.headline,
                "location": card.identity.location,
                "skills": [s.name for s in card.skills],
                "industries": card.industries,
                "availability": card.availability,
                "experience_years": card.experience_years,
                "match_score": round(min(score, 1.0), 3),
                "match_reasons": reasons[:6],
                "url": f"{config.SITE_BASE_URL}/p/{card.handle}" if card.handle else f"{config.SITE_BASE_URL}/profile/{card.id}",
            }
        )

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results[:limit]
