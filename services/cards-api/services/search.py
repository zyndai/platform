import json
import logging
import time
from datetime import datetime, timezone

import config
from models.card import AgentProfileCard
from services import cards as cards_service
from services import card_cache, geo
from services.embed import card_search_text, describes_person, embed_text
from services.search_constraints import SKILL_ALIASES, Constraints, explicit_query_constraints, skill_key, skill_matches
from services.two_way import TWO_WAY_BOOST, kinds_of, too_much_like, two_way_match
from services.search_text import (
    _LOCATION_ALIASES,
    ROLE_SYNONYMS,
    contains_all,
    location_terms,
    location_tokens,
    phrase_score,
    query_terms,
    role_matches,
    role_tokens,
    term_sequence,
    token_set,
    topic_phrases,
    topic_terms,
)

logger = logging.getLogger(__name__)

# Per source (vector + full text) candidates handed to the Python scorer.
CANDIDATES_PER_SOURCE = 200
# Most cards cards.filter_cards may return for a filtered search. Reaching it means the filter
# was too broad to trust (a truncated list could drop a match), so the search reads every card.
FILTERED_ROWS_LIMIT = 2000


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


def current_company(card: AgentProfileCard) -> str:
    """The company of the card's newest LinkedIn role, or "" when unknown."""
    for job in card.work_experience or []:
        company = str((job or {}).get("company") or "").strip() if isinstance(job, dict) else ""
        if company and company.upper() != "N/A":
            return company
    return ""


def _skill_matches(wanted: str, skill_name: str) -> bool:
    """Match the requested topic with whole words; Go must never match Django."""
    return skill_matches(wanted, skill_name)


SLOW_SEARCH_SECONDS = 3.0     # a search slower than this logs where its time went
QUERY_VECTOR_TTL_SECONDS = 600.0    # memory retries a timed-out search, assistants repeat a query: embed once
QUERY_VECTOR_CACHE = 512
_query_vectors: dict[str, tuple[float, list[float]]] = {}


def _embed_query(q: str) -> list[float]:
    """q's embedding, reused for QUERY_VECTOR_TTL_SECONDS. Oldest entries go first when full."""
    now = time.monotonic()
    hit = _query_vectors.get(q)
    if hit and now - hit[0] < QUERY_VECTOR_TTL_SECONDS:
        return hit[1]
    vec = embed_text(q)
    if vec:
        if len(_query_vectors) >= QUERY_VECTOR_CACHE:
            oldest = sorted(list(_query_vectors.items()), key=lambda kv: kv[1][0])   # a copy: other threads write too
            for key, _ in oldest[: QUERY_VECTOR_CACHE // 4]:
                _query_vectors.pop(key, None)
        _query_vectors[q] = (now, vec)
    return vec


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
    topics: str = "",
    relax: bool = False,
    keep_role: bool = False,
    query_vec: list[float] | None = None,
) -> list[dict]:
    """Score published cards against a query.

    candidate_rows scopes the search to those rows (a group's members) instead of every card;
    less_like are Cards the searcher asked to see less of.

    topics are guesses about what the person works on (a caller parsed them out of free text):
    they add to the score and never remove a card, unlike skills, which are a requirement.

    relax=True keeps the role, location and skills as requirements first, then, while fewer than
    `limit` cards qualify, drops them one at a time: skills, then a city widened to its country,
    then the location, then the role. Cards found by a looser pass always rank below those found
    by a stricter one and say what was relaxed (`relaxed`, plus a match reason). keep_role=True
    never drops the role (suggestions: "investors" must stay investors).

    query_vec is q's embedding when the caller already has it (suggestions embed each target once
    per refresh, not once per card)."""
    q_terms = query_terms(q)
    if q and not q_terms and not any((role, location, skills, industry, availability, experience_min is not None)):
        return []   # "who is in the": nothing to look for, and embedding it would match noise
    inferred_location, inferred_skills = explicit_query_constraints(q)
    location = location or inferred_location
    skills = skills or ",".join(inferred_skills)
    if query_vec is None:
        query_vec = _embed_query(q) if q else []
    started = time.monotonic()
    fetches: list[str] = []
    copied: list[list[dict]] = []      # the snapshot's rows with this query's similarity, built once

    def rows_for(r: str, loc: str, sk: str) -> list[dict]:
        fetched = time.monotonic()
        if candidate_rows is None and not copied and (snap := card_cache.snapshot()) is not None:
            q_unit = card_cache.unit(query_vec)
            copied.append([{**row, "similarity": card_cache.dot(q_unit, row["unit"])} for row in snap.rows
                           if include_unclaimed or row["claimed"]])
        if copied:
            # every pass scores the same copy: the scorer applies this pass's requirements exactly
            rows = copied[0]
        else:
            rows = _rows_for(q, query_vec, include_unclaimed, candidate_rows,
                             Constraints(r, loc, tuple(s.strip() for s in sk.split(",") if s.strip()),
                                         industry, availability, experience_min))
        fetches.append(f"{len(rows)} rows in {time.monotonic() - fetched:.1f}s{' (snapshot)' if copied else ''}")
        return rows

    def finish(found: list[dict]) -> list[dict]:
        """A slow search says where its time went (one line, never the query), so a relaxed search that
        outlasts its caller's timeout can be profiled from the server log instead of guessed at."""
        elapsed = time.monotonic() - started
        if elapsed > SLOW_SEARCH_SECONDS:
            logger.warning("slow search: %.1fs over %d pass(es) [%s], relax=%s, filters=%s, embedded=%s",
                           elapsed, len(fetches), "; ".join(fetches), relax, bool(role or location or skills),
                           bool(query_vec))
        return found[:limit]

    common = dict(q=q, query_vec=query_vec, industry=industry, availability=availability,
                  experience_min=experience_min, searcher=searcher, less_like=less_like, topics=topics,
                  want_role=role, want_location=location, want_skills=skills)
    results = _search_pass(rows=rows_for(role, location, skills), role=role, location=location, skills=skills, **common)
    if not relax or len(results) >= limit:
        return finish(results)

    seen = {r["handle"] for r in results if r.get("handle")}
    for dropped, stage_role, stage_location, stage_skills, note in _relaxations(role, location, skills, keep_role):
        if len(results) >= limit:
            break
        for r in _search_pass(rows=rows_for(stage_role, stage_location, stage_skills),
                              role=stage_role, location=stage_location, skills=stage_skills, **common):
            if r.get("handle") in seen:
                continue
            seen.add(r.get("handle"))
            r["relaxed"] = dropped
            r["match_reasons"] = [*r["match_reasons"], note]
            results.append(r)
    return finish(results)


def _a(noun: str) -> str:
    """"a" or "an" for a role noun: "Not an investor", "Not a lawyer"."""
    return "an" if noun[:1].lower() in "aeiou" else "a"


def _relaxations(role: str, location: str, skills: str, keep_role: bool = False):
    """(dropped, role, location, skills, reason) for each looser pass, each also loosened as the
    ones before it were."""
    dropped: list[str] = []
    if skills:
        skills = ""
        dropped.append("skills")
        yield list(dropped), role, location, skills, "Skill filter relaxed (closest match)"
    if location:
        country = geo.widen(location)
        if country:
            if "location" not in dropped:
                dropped.append("location")
            yield list(dropped), role, country, skills, f"Not in {location} (closest match: {country})"
        if "location" not in dropped:
            dropped.append("location")
        yield list(dropped), role, "", skills, f"Not in {location} (closest match)"
        location = ""
    if role and not keep_role:
        dropped.append("role")
        yield list(dropped), "", location, skills, f"Not {_a(role)} {role} (closest match)"


# --- Scoring -------------------------------------------------------------------------------
#
# score = relevance x fit x quality, each in 0..1, so a score means the same thing for every
# query and a requested constraint that a card misses costs it a fixed share instead of nothing.
#
#   relevance  how well the card's text answers the query: 60% meaning (embedding cosine
#              rescaled from its useful range), 40% words (query terms on the card, or the best
#              approved fact), plus a little for topic guesses. A search with no query terms is
#              all filters, so every card that passes them is equally relevant.
#   fit        the product, over the constraints the caller asked for, of how well the card meets
#              each (FIT_*). Only relaxed passes can miss one: a strict pass already dropped them.
#   quality    0.85..1.0 for a claimed owner and a current approved fact; x TWO_WAY_BOOST when the
#              card wants to meet the searcher's kind, x LESS_LIKE_FACTOR for "less like this".
#              Memory adds "verified" in its own re-rank, where trust data is already at hand.
#
# The constants start from the plan (docs/plans/ZYND_PEOPLE_SEARCH_PLAN.md 1.1). SEM_FLOOR/SEM_SPAN
# are the cosine range of text-embedding-3-small for related text; re-fit them on a sample of real
# query/card cosines (the golden set embeds with a hash, so it cannot calibrate them).
SEM_FLOOR, SEM_SPAN = 0.20, 0.40
W_SEM, W_LEX, W_TOPIC = 0.6, 0.4, 0.15
MET_RELEVANCE = 0.4                # a card that meets a requested role, place or skill is a real candidate
BEACON_LEX = 0.8                    # a current broadcast that names a query term
FIT_ROLE_HEADLINE, FIT_ROLE_ELSEWHERE, FIT_ROLE_MISSING = 1.0, 0.9, 0.5
FIT_LOCATION_MET, FIT_LOCATION_COUNTRY, FIT_LOCATION_MISSING = 1.0, 0.85, 0.6
FIT_SKILL_MISSING = 0.7
QUALITY_BASE, QUALITY_CLAIMED, QUALITY_FRESH = 0.85, 0.075, 0.075
LESS_LIKE_FACTOR = 0.7
MIN_SCORE = 0.25                    # a text query's results below this are noise


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def semantic_score(cosine: float | None) -> float:
    """Embedding cosine rescaled so related text is 0..1 (unrelated text is near SEM_FLOOR)."""
    return _clamp(((cosine or 0.0) - SEM_FLOOR) / SEM_SPAN)


def relevance_score(sem: float, lex: float, topic: float, has_query: bool, has_topics: bool) -> float:
    if has_query:
        base = W_SEM * sem + W_LEX * lex
    else:
        base = 0.5 + 0.5 * topic if has_topics else 1.0
    return _clamp(base + (W_TOPIC * topic if has_query else 0.0))


def quality_score(claimed: bool, freshness: float) -> float:
    """freshness is 0..1: how current the card's best approved fact is."""
    return QUALITY_BASE + QUALITY_CLAIMED * bool(claimed) + QUALITY_FRESH * _clamp(freshness)


def _squash(text: str) -> str:
    """The form cards.filter_cards compares in: lower case, only letters, digits, + and #."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() and ch.isascii() or ch in "+#")


def _fragments(*words: str) -> list[str]:
    return list(dict.fromkeys(f for f in (_squash(w) for w in words) if f))


def filter_groups(role: str, location: str, skills: tuple[str, ...]) -> tuple[list, list, list]:
    """(role groups, location fragments, skill groups) for cards.filter_cards: every spelling the
    exact rules in Constraints.matches could accept, so the database only drops cards they would."""
    role_groups = []
    for term in query_terms(role):
        words = [term, *sorted(ROLE_SYNONYMS.get(term, ()))]
        if term == "founder":
            words.append("is_founder_of")           # an approved fact makes someone a founder
        role_groups.append(_fragments(*words))
    skill_groups = []
    for wanted in skills:
        for term in query_terms(skill_key(wanted)):
            skill_groups.append(_fragments(term, *(k for k, v in SKILL_ALIASES.items() if v == term)))
    place: list[str] = []
    for term in location_terms(location):
        place += [term, *(alias for alias, canonical in _LOCATION_ALIASES.items() if canonical == term)]
    place += geo.spellings_in_country(location)
    return role_groups, _fragments(*place), skill_groups


def _filtered_rows(
    query_vec: list[float], include_unclaimed: bool, role: str, location: str, skills: tuple[str, ...],
) -> list[dict] | None:
    """Rows that could pass these constraints, from the database (cards.filter_cards), with
    similarity already computed; None when the function is missing or too much came back."""
    role_groups, place, skill_groups = filter_groups(role, location, skills)
    args = {"p_role": role_groups, "p_location": place, "p_skills": skill_groups,
            "include_unclaimed": include_unclaimed, "match_count": FILTERED_ROWS_LIMIT}
    if query_vec:
        args["query_embedding"] = query_vec
    try:
        rows = config.get_supabase().rpc("filter_cards", args).execute().data or []
    except Exception as exc:  # noqa: BLE001 — migration 0030 not applied yet: read every card instead
        logger.warning("filter_cards unavailable (%s); falling back to a full scan", exc)
        return None
    if len(rows) >= FILTERED_ROWS_LIMIT:
        return None
    return rows


def _rows_for(
    q: str, query_vec: list[float], include_unclaimed: bool, candidate_rows: list[dict] | None,
    constraints: Constraints,
) -> list[dict]:
    """The rows one scoring pass needs: those that could pass `constraints`. The exact test still
    runs in the scorer; this only keeps it from reading cards that cannot."""
    if candidate_rows is not None:
        return candidate_rows
    if not constraints.active:
        return _candidates(q, query_vec, include_unclaimed)
    # Page the published corpus when pre-limited vector candidates could omit the only valid
    # match. The database does that filtering when it can; industry, availability and experience
    # are not in it, so a search that uses them reads every card.
    if not (constraints.industry or constraints.availability or constraints.experience_min is not None):
        rows = _filtered_rows(query_vec, include_unclaimed, constraints.role, constraints.location, constraints.skills)
        if rows is not None:
            return rows
    rows = cards_service.list_published_rows()
    if not include_unclaimed:
        rows = [r for r in rows if bool((r.get("owner_email") or "").strip())]
    return rows


def _search_pass(
    *, q: str, query_vec: list[float], rows: list[dict], role: str, location: str, skills: str,
    industry: str, availability: str, experience_min: int | None,
    searcher: AgentProfileCard | None, less_like: list[AgentProfileCard] | None, topics: str,
    want_role: str | None = None, want_location: str | None = None, want_skills: str | None = None,
) -> list[dict]:
    """One scoring pass over `rows` with exactly these requirements; best match first, unlimited.

    role/location/skills are what a card must pass in this pass. want_* are what the caller asked
    for (they differ in a relaxed pass, which dropped some): fit is judged against those, so a card
    that missed a dropped requirement scores lower than one that met it."""
    from services.beacons import active_beacon
    from services.card_view import fact_object, freshness_boost, live_facts

    want_role = role if want_role is None else want_role
    want_location = location if want_location is None else want_location
    want_skills = skills if want_skills is None else want_skills
    q_terms = query_terms(q)
    # Topic words only ever add to a card's relevance: they are not part of the query's coverage
    # (an unmatched topic would dilute it) and never a requirement.
    topics_scored = topic_phrases(topics, {c for t in q_terms for c in topic_terms(t)})
    constraints = Constraints(role, location, tuple(s.strip() for s in skills.split(",") if s.strip()), industry, availability, experience_min)
    skill_list = [s.strip() for s in want_skills.split(",") if s.strip()] if want_skills else []
    industry_norm = _norm(industry)
    availability_norm = _norm(availability)
    location_want = location_terms(want_location)
    searcher_kinds = kinds_of(searcher) if searcher is not None else set()

    results = []
    for row in rows:
        card = row.get("model")             # parsed once in the snapshot
        if card is None:
            try:
                card = AgentProfileCard.model_validate(row.get("card") or {})
            except Exception:
                continue
            if row.get("handle"):
                card.handle = row["handle"]
        if not constraints.matches(card):
            continue
        if "search_text" not in row:
            row["search_text"] = card_search_text(card).lower()
        search_text = row["search_text"]
        beacon = active_beacon(card)
        if beacon:
            search_text += " " + beacon.text.lower()
        text_tokens = token_set(search_text)
        facts = live_facts(card.zynd_memory)
        about = [f for f in facts if describes_person(f)]      # not what they are looking for
        reasons: list = []

        # relevance: meaning and words
        sim = row.get("similarity")
        if sim is None and query_vec:
            sim = _cosine(query_vec, _parse_embedding(row.get("embedding")))
        sem = semantic_score(sim) if query_vec else 0.0
        if query_vec and (sim or 0.0) > 0.6:
            reasons.append("Strong overall match for your query")
        lex = 0.0
        if q_terms:
            hits = [t for t in q_terms if t in text_tokens]
            if hits:
                lex = len(hits) / len(q_terms)
                reasons.append("Matches your search terms")
            # An approved fact earns lexical credit in proportion to how much of the query it
            # alone covers, so one shared word no longer counts as a full match.
            matched_memory = []
            for fact in about:
                blob = token_set(fact_object(fact))
                covered = len([t for t in q_terms if t in blob]) / len(q_terms) if blob else 0.0
                if covered:
                    matched_memory.append(fact)
                    lex = max(lex, covered)
            if matched_memory:
                if config.FEATURE_S06_CARDVIEW:
                    for fact in matched_memory[:3]:
                        reasons.append({
                            "type": "memory",
                            "text": fact_object(fact),
                            "source": fact.get("source") or "",
                            "age_days": _age_days(fact),
                        })
                else:
                    reasons.append("Approved fact")
            if beacon and any(t in token_set(beacon.text) for t in q_terms):
                lex = max(lex, BEACON_LEX)
                reasons.insert(0, "Current beacon: " + beacon.text)
        topic = 0.0
        if topics_scored:
            text_seq = term_sequence(search_text)
            fact_seqs = [term_sequence(fact_object(f)) for f in about]
            per_topic = [max([phrase_score(text_seq, terms), *(phrase_score(fs, terms) for fs in fact_seqs)])
                         for _, terms in topics_scored]
            found = [label for (label, _), got in zip(topics_scored, per_topic) if got >= 1.0]
            if found:
                reasons.append("Mentions " + ", ".join(found))
            topic = sum(per_topic) / len(per_topic)
        # fit: how well the card meets each constraint the caller asked for
        fit = 1.0
        role_missing = False
        met: set[str] = set()          # query words a satisfied constraint already answers
        if want_role:
            if role_matches(role_tokens(card.identity.headline), want_role):
                reasons.append(card.identity.headline or "Role match")      # the strongest role signal
                fit *= FIT_ROLE_HEADLINE
                met.update(query_terms(want_role))
            elif role_matches(role_tokens(search_text), want_role, activities=False) or constraints.role:
                # mentioned elsewhere on the card (work history, an approved fact)
                reasons.append("Role match")
                fit *= FIT_ROLE_ELSEWHERE
                met.update(query_terms(want_role))
            else:
                fit *= FIT_ROLE_MISSING
                role_missing = True
        if location_want:
            if all(t in location_tokens(card.identity.location) for t in location_want):
                reasons.append(f"Based in {card.identity.location}")
                fit *= FIT_LOCATION_MET
                met.update(location_want)
            elif geo.same_country(want_location, card.identity.location):
                reasons.append(f"Based in {card.identity.location}")
                fit *= FIT_LOCATION_COUNTRY
                met.update(location_want)
            else:
                fit *= FIT_LOCATION_MISSING
        if skill_list:
            matched_skills = [sk for sk in skill_list if any(_skill_matches(sk, s.name) for s in card.skills)]
            if matched_skills:
                reasons.append("Skills: " + ", ".join(matched_skills))
                for sk in matched_skills:
                    met.update(query_terms(sk))
            fit *= FIT_SKILL_MISSING + (1 - FIT_SKILL_MISSING) * len(matched_skills) / len(skill_list)
        if industry_norm and any(contains_all(token_set(i), industry) for i in card.industries):
            reasons.append("Industry: " + ", ".join(card.industries))
        if availability_norm and contains_all(token_set(card.availability), availability):
            reasons.append(f"Available for {card.availability}")
        if experience_min is not None and card.experience_years and card.experience_years >= experience_min:
            reasons.append(f"{card.experience_years} years experience")

        if q_terms and met:
            # "investors in India" is answered by an investor in Gurgaon: words a met constraint
            # covers count as found even when the card's text does not repeat them.
            lex = max(lex, len(set(q_terms) & (met | {t for t in q_terms if t in text_tokens})) / len(q_terms))
        relevance = relevance_score(sem, lex, topic, bool(q_terms or query_vec), bool(topics_scored))
        if met:
            relevance = max(relevance, MET_RELEVANCE)

        # quality: who they are, and what the searcher said about people like them
        claimed = row.get("claimed")
        if claimed is None:
            claimed = bool((row.get("owner_email") or "").strip())
        freshness = max((freshness_boost(f) for f in facts), default=0.0) / 0.1
        quality = quality_score(bool(claimed), freshness)
        fits: list[str] = []
        if searcher_kinds and searcher is not None and card.handle != searcher.handle:
            fits = two_way_match(searcher_kinds, card)
            if fits:
                quality *= 1 + TWO_WAY_BOOST
                reasons.append("Wants to meet people like you: " + ", ".join(fits[:2]))
        if less_like and any(too_much_like(d, card) for d in less_like):
            quality *= LESS_LIKE_FACTOR
            reasons.append("Similar to people you asked to see less of")

        score = _clamp(relevance * fit * quality)
        # The noise floor is about the text, not the constraints: a relaxed result that missed a
        # dropped place or skill is already ranked down (and labelled) by its fit. One that is not
        # the kind of person asked for must clear the floor with that penalty counted.
        if q and _clamp(relevance * quality) * (FIT_ROLE_MISSING if role_missing else 1.0) < MIN_SCORE:
            continue
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
                "avatar_url": card.identity.avatar_url or "",
                "company": current_company(card),
                "two_way": fits,
                "match_score": round(score, 3),
                "match_reasons": reasons[:6],
                "url": config.profile_url(card.handle) if card.handle else f"{config.SITE_BASE_URL}/profile/{card.id}",
            }
        )

    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results
