import json
import logging

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services.embed import card_search_text, embed_text
from services.search_text import (
    contains_all,
    location_terms,
    location_tokens,
    query_terms,
    role_matches,
    token_set,
)

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


def _skill_matches(wanted: str, skill_name: str) -> bool:
    """Whole-word skill match, either direction: "AI dev tools" reaches a skill called "AI",
    but "go" no longer reaches "django"."""
    want, have = set(query_terms(wanted)), set(query_terms(skill_name))
    return bool(want and have) and (have <= want or want <= have)


def _candidates(q: str, query_vec: list[float], include_unclaimed: bool) -> list[dict]:
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
                resp = sb.rpc(
                    "match_cards",
                    {"query_embedding": query_vec, "match_count": CANDIDATES_PER_SOURCE, "include_unclaimed": include_unclaimed},
                ).execute()
                for r in resp.data or []:
                    by_id[r["id"]] = {"card": r["card"], "handle": r["handle"], "similarity": r.get("similarity")}
            resp = sb.rpc(
                "search_cards_fts",
                {"q": q, "match_count": CANDIDATES_PER_SOURCE, "include_unclaimed": include_unclaimed},
            ).execute()
            for r in resp.data or []:
                by_id.setdefault(r["id"], {"card": r["card"], "handle": r["handle"]})
            return list(by_id.values())
        except Exception as exc:  # noqa: BLE001 — functions not deployed yet: degrade, don't fail search
            logger.warning("search RPCs unavailable (%s); falling back to a full scan", exc)
    rows = cards_service.list_published_rows(columns="card,handle,embedding,owner_email")
    if not include_unclaimed:
        rows = [r for r in rows if bool((r.get("owner_email") or "").strip())]
    return rows


def search_agents(
    q: str = "",
    role: str = "",
    location: str = "",
    skills: str = "",
    industry: str = "",
    availability: str = "",
    experience_min: int | None = None,
    limit: int = 10,
    include_unclaimed: bool = False,
) -> list[dict]:
    # Stopwords out, whole words only: "in", "who" and "ai" used to substring-match nearly
    # every card ("ai" is inside "maintain").
    q_terms = query_terms(q)
    if q and not q_terms and not any((role, location, skills, industry, availability)):
        return []   # "who is in the": nothing to look for, and embedding it would match noise
    query_vec = embed_text(q) if q else []
    rows = _candidates(q, query_vec, include_unclaimed)
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    industry_norm = _norm(industry)
    role_norm = _norm(role)
    availability_norm = _norm(availability)
    location_want = location_terms(location)

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
        text_tokens = token_set(search_text)

        score = 0.0
        reasons: list = []

        sim = row.get("similarity")
        if sim is None and query_vec:
            sim = _cosine(query_vec, _parse_embedding(row.get("embedding")))
        if query_vec and sim:
            score += sim * 0.5
            if sim > 0.6:
                reasons.append("Strong overall match for your query")

        if q_terms:
            hits = [t for t in q_terms if t in text_tokens]
            if hits:
                score += 0.25 * (len(hits) / len(q_terms))
                reasons.append("Matches your search terms")
            from services.card_view import fact_object, freshness_boost, live_facts

            # A card's approved facts earn a bonus in proportion to how much of the query the
            # best of them covers, so one shared word no longer counts as a full match.
            matched_memory = []
            best_cover = 0.0
            for fact in live_facts(card.zynd_memory):
                blob = token_set(fact_object(fact))
                covered = len([t for t in q_terms if t in blob]) / len(q_terms) if blob else 0.0
                if covered:
                    matched_memory.append(fact)
                    best_cover = max(best_cover, covered)
            if matched_memory:
                score += 0.2 * best_cover
                if config.FEATURE_S06_CARDVIEW:
                    boost = max(freshness_boost(f) for f in matched_memory)
                    score += boost
                    for fact in matched_memory[:3]:
                        reasons.append({
                            "type": "memory",
                            "text": fact_object(fact),
                        })
                else:
                    reasons.append("Approved fact")

        if role_norm:
            if role_matches(token_set(card.identity.headline), role):
                score += 0.25            # their headline says it: the strongest role signal
                reasons.append(card.identity.headline or "Role match")
            elif role_matches(text_tokens, role):
                score += 0.1             # mentioned somewhere on the card
                reasons.append("Role match")

        if location_want and all(t in location_tokens(card.identity.location) for t in location_want):
            score += 0.3
            reasons.append(f"Based in {card.identity.location}")

        matched_skills = [
            sk for sk in skill_list
            if any(_skill_matches(sk, s.name) for s in card.skills)
        ]
        if skill_list and matched_skills:
            score += 0.25 * (len(matched_skills) / len(skill_list))
            reasons.append("Skills: " + ", ".join(matched_skills))

        if industry_norm and any(contains_all(token_set(i), industry) for i in card.industries):
            score += 0.2
            reasons.append("Industry: " + ", ".join(card.industries))

        if availability_norm and contains_all(token_set(card.availability), availability):
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
    if q:
        results = [r for r in results if r["match_score"] >= 0.2]
    return results[:limit]
