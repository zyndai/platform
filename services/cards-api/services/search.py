import json
import logging
from datetime import datetime, timezone

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services.embed import card_search_text, embed_text
from services.search_constraints import Constraints, explicit_query_constraints, skill_matches
from services.two_way import LESS_LIKE_PENALTY, TWO_WAY_BOOST, kinds_of, too_much_like, two_way_match
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


def _age_days(fact: dict) -> int | None:
    """Days since the owner approved this fact (how current it is), or None when unknown."""
    from services.card_view import _parse_ts

    approved = _parse_ts(fact.get("approved_at") if isinstance(fact, dict) else None)
    if approved is None:
        return None
    return max((datetime.now(timezone.utc) - approved).days, 0)


def _skill_matches(wanted: str, skill_name: str) -> bool:
    """Match the requested topic with whole words; Go must never match Django."""
    return skill_matches(wanted, skill_name)


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
            # Broadcasts are deliberately absent from durable embeddings: their
            # exact expiry must not leave a stale semantic match behind.
            from services.beacons import active_beacon, candidate_rows as beacon_rows
            for r in beacon_rows():
                if not include_unclaimed and not (r.get("owner_email") or "").strip():
                    continue
                try:
                    beacon = active_beacon(AgentProfileCard.model_validate(r["card"]))
                except (ValueError, TypeError, KeyError):
                    continue
                if beacon and any(t in token_set(beacon.text) for t in query_terms(q)):
                    by_id.setdefault(r["id"], r)
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
    searcher: AgentProfileCard | None = None,
    less_like: list[AgentProfileCard] | None = None,
    candidate_rows: list[dict] | None = None,
) -> list[dict]:
    """Score published cards against a query.

    candidate_rows scopes the search to those rows (a group's members) instead of every card;
    less_like are Cards the searcher asked to see less of."""
    # Stopwords out, whole words only: "in", "who" and "ai" used to substring-match nearly
    # every card ("ai" is inside "maintain").
    q_terms = query_terms(q)
    if q and not q_terms and not any((role, location, skills, industry, availability, experience_min is not None)):
        return []   # "who is in the": nothing to look for, and embedding it would match noise
    inferred_location, inferred_skills = explicit_query_constraints(q)
    location = location or inferred_location
    skills = skills or ",".join(inferred_skills)
    constraints = Constraints(role, location, tuple(s.strip() for s in skills.split(",") if s.strip()), industry, availability, experience_min)
    query_vec = embed_text(q) if q else []
    if candidate_rows is not None:
        rows = candidate_rows
    elif constraints.active:
        # Page the published corpus: pre-limited vector candidates can omit the
        # only valid city/skill match. Filter before ranking or applying a limit.
        rows = cards_service.list_published_rows()
        if not include_unclaimed:
            rows = [r for r in rows if bool((r.get("owner_email") or "").strip())]
    else:
        rows = _candidates(q, query_vec, include_unclaimed)
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    industry_norm = _norm(industry)
    role_norm = _norm(role)
    availability_norm = _norm(availability)
    location_want = location_terms(location)
    searcher_kinds = kinds_of(searcher) if searcher is not None else set()

    results = []
    for row in rows:
        card_data = row.get("card") or {}
        try:
            card = AgentProfileCard.model_validate(card_data)
        except Exception:
            continue
        if row.get("handle"):
            card.handle = row["handle"]
        if not constraints.matches(card):
            continue
        search_text = card_search_text(card).lower()
        from services.beacons import active_beacon
        beacon = active_beacon(card)
        if beacon:
            search_text += " " + beacon.text.lower()
        text_tokens = token_set(search_text)

        score = 0.0
        reasons: list = []
        if beacon and q_terms and any(t in token_set(beacon.text) for t in q_terms):
            score += 0.2
            reasons.append("Current beacon: " + beacon.text)

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
                            "source": fact.get("source") or "",
                            "age_days": _age_days(fact),
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

        if searcher_kinds and searcher is not None and card.handle != searcher.handle:
            fits = two_way_match(searcher_kinds, card)
            if fits:
                score += TWO_WAY_BOOST
                reasons.append("Wants to meet people like you: " + ", ".join(fits[:2]))

        if less_like and any(too_much_like(d, card) for d in less_like):
            score -= LESS_LIKE_PENALTY
            reasons.append("Similar to people you asked to see less of")

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
                "linkedin_url": (card.identity.links or {}).get("linkedin") or "",
                "match_score": round(max(min(score, 1.0), 0.0), 3),
                "match_reasons": reasons[:6],
                "url": f"{config.SITE_BASE_URL}/p/{card.handle}" if card.handle else f"{config.SITE_BASE_URL}/profile/{card.id}",
            }
        )

    results.sort(key=lambda r: r["match_score"], reverse=True)
    if q:
        results = [r for r in results if r["match_score"] >= 0.2]
    return results[:limit]
