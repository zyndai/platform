"""People to meet: a card owner's suggestions, computed as searches (people search plan Phase 2).

compute()      runs each of the owner's targets (suggest_targets) through search.search_agents
               with the owner as searcher (so people who want to meet someone like the owner rank
               up), keeps each person's best result, and leaves out who can't be suggested.
refresh_all()  the nightly job: the top TOP_N per claimed card into cards.card_suggestions, so
               the digest and owner home read a row instead of searching.
for_owner()    what a surface shows: the stored list (or a live compute when there is none),
               re-checked against today's exclusions, with the digest cooldown and diversity.

Who is never suggested: the owner, unclaimed cards (they can't accept), anyone the owner has a
connection row with in any state (pending, accepted, declined, blocked, revoked), Cards the owner
reported, people they hid, and people they marked not relevant. The digest also skips anyone it
showed in the last COOLDOWN_DAYS unless their score rose by more than RESHOW_GAIN.

The two tables come from packages/db cards 0031. Until a person applies it, every read and write
of them fails; suggestions are then computed live and nothing is recorded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from models.card import AgentProfileCard
from services import geo
from services.search_text import location_tokens

logger = logging.getLogger(__name__)

TOP_N = 20                  # stored per card by the nightly job
PER_TARGET_SEARCH = 8       # results asked of each target's search
MAX_PER_TARGET = 2          # spread across the kinds of people the owner asked for
MAX_PER_COMPANY = 1         # and across companies
FRESH_HOURS = 36            # a stored list older than this is computed again
COOLDOWN_DAYS = 14          # the digest is daily: don't email the same person within two weeks
RESHOW_GAIN = 0.15          # ... unless they now match much better than when they were shown
NEAR_CITY, NEAR_COUNTRY = 1.05, 1.03   # a small preference for people nearby, never a filter
MAX_WHY = 3

SURFACES = ("digest", "owner_home", "api")
ACTIONS = ("viewed", "connect", "hide", "not_relevant")

_GENERIC_REASONS = ("Matches your search terms", "Strong overall match for your query", "Role match",
                    "Approved fact", "Similar to people you asked to see less of")
_ROW_COLUMNS = "id,handle,owner_user_id,owner_email,card"
_tables_warned = False


def _sb():
    return config.get_supabase()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tables_unavailable(exc: Exception) -> None:
    """Log once per process: the suggestion tables are missing (0031 not applied) or failing."""
    global _tables_warned
    if not _tables_warned:
        logger.warning("suggestion tables unavailable (%s); computing live, recording nothing", exc)
        _tables_warned = True


def _card(row: dict) -> AgentProfileCard | None:
    try:
        card = AgentProfileCard.model_validate(row.get("card") or {})
    except Exception:  # noqa: BLE001 — a malformed card has no suggestions
        return None
    if row.get("handle"):
        card.handle = row["handle"]
    return card


def _claimed(row: dict) -> bool:
    return bool((row.get("owner_email") or "").strip()) and bool(row.get("owner_user_id"))


def owner_row(handle: str) -> dict | None:
    """The owner's published card row, by handle (or a handle it used to have)."""
    want = (handle or "").strip().lstrip("@").lower()
    if not want:
        return None
    rows = (_sb().table("agent_profile_cards").select(_ROW_COLUMNS).eq("handle", want)
            .eq("status", "published").limit(1).execute().data or [])
    if rows:
        return rows[0]
    from services import cards as cards_service
    card = cards_service.get_card_by_handle(want)
    if not card or not card.id:
        return None
    rows = (_sb().table("agent_profile_cards").select(_ROW_COLUMNS).eq("id", card.id)
            .eq("status", "published").limit(1).execute().data or [])
    return rows[0] if rows else None


# --- Who can't be suggested ------------------------------------------------------------------

def exclusions(row: dict) -> dict:
    """{"card_ids": set, "handles": set, "less_like": [handle]} for this owner. Every source is
    best effort except connections: suggesting someone already connected is the bug this fixes."""
    card_ids = {row.get("id")} - {None}
    handles = {(row.get("handle") or "").lower()} - {""}
    less_like: list[str] = []
    user_id = row.get("owner_user_id")
    if user_id:
        for c in (_sb().table("connections").select("requester_user_id,requester_card_id,recipient_card_id")
                  .or_(f"requester_user_id.eq.{user_id},recipient_user_id.eq.{user_id}").execute().data or []):
            other = c.get("recipient_card_id") if c.get("requester_user_id") == user_id else c.get("requester_card_id")
            if other:
                card_ids.add(other)
        try:
            reports = (_sb().table("card_reports").select("target_card_id").eq("reporter_user_id", user_id)
                       .eq("status", "open").execute().data or [])
            card_ids.update(r["target_card_id"] for r in reports if r.get("target_card_id"))
        except Exception as exc:  # noqa: BLE001
            logger.info("suggestions: reports unavailable (%s)", exc)
        try:
            from services import match_prefs
            prefs = match_prefs.get(user_id)
            handles.update(h.lower() for h in prefs.get("hide_person") or [])
            less_like = list(prefs.get("less_like_this") or [])
        except Exception as exc:  # noqa: BLE001
            logger.info("suggestions: match preferences unavailable (%s)", exc)
    if row.get("id"):
        try:
            dismissed = (_sb().table("card_suggestion_impressions").select("candidate_card_id")
                         .eq("card_id", row["id"]).in_("action", ["hide", "not_relevant"]).execute().data or [])
            card_ids.update(r["candidate_card_id"] for r in dismissed if r.get("candidate_card_id"))
        except Exception as exc:  # noqa: BLE001
            _tables_unavailable(exc)
    return {"card_ids": card_ids, "handles": handles, "less_like": less_like}


def _excluded(person: dict, ex: dict) -> bool:
    return person.get("card_id") in ex["card_ids"] or (person.get("handle") or "").lower() in ex["handles"]


# --- Computing --------------------------------------------------------------------------------

def _reason_text(reason) -> str:
    if isinstance(reason, dict):
        return str(reason.get("text") or "").strip()
    return str(reason or "").strip()


def build_why(result: dict, two_way: list[str]) -> list[str]:
    """At most MAX_WHY specific reasons, most telling first: wants to meet someone like the owner,
    then what the search matched (headline, approved fact, topic, what was loosened, place).
    Generic reasons are dropped."""
    why: list[str] = []
    if two_way:
        why.append("Wants to meet " + " and ".join(k.lower() for k in two_way[:2]) + " like you")
    for reason in result.get("match_reasons") or []:
        text = _reason_text(reason)
        if not text or text in _GENERIC_REASONS or text.startswith("Wants to meet people like you"):
            continue
        if text not in why:
            why.append(text)
    return why[:MAX_WHY]


def _near(owner_location: str, location: str) -> float:
    if not owner_location or not location:
        return 1.0
    mine = location_tokens(owner_location)
    if mine and mine <= location_tokens(location):
        return NEAR_CITY
    return NEAR_COUNTRY if geo.same_country(owner_location, location) else 1.0


def _person(result: dict, target, score: float, two_way: list[str]) -> dict:
    return {
        "handle": result.get("handle") or "",
        "card_id": result.get("agent_id") or "",
        "name": result.get("name") or "",
        "headline": result.get("headline") or "",
        "location": result.get("location") or "",
        "avatar_url": result.get("avatar_url") or "",
        "company": result.get("company") or "",
        "url": result.get("url") or "",
        "score": round(score, 3),
        "two_way": bool(two_way),
        "two_way_kinds": two_way,
        "target": target.label,
        "why": build_why(result, two_way),
        "relaxed": list(result.get("relaxed") or []),
    }


def _rank_key(person: dict):
    return (not person["two_way"], -person["score"], person["handle"].casefold())


def compute(row: dict, *, embed_cache: dict | None = None, ex: dict | None = None) -> list[dict]:
    """Every person this owner could be suggested, best first (two-way people lead). Unlimited:
    callers cut it. [] for an unclaimed or unreadable card, or one that says nothing to search with."""
    from services import cards as cards_service
    from services import search
    from services.suggest_targets import targets_for

    card = _card(row)
    if card is None or not _claimed(row):
        return []
    targets = targets_for(card)
    if not targets:
        return []
    ex = ex if ex is not None else exclusions(row)
    less_like = [c for h in ex["less_like"][:10] if (c := cards_service.get_card_by_handle(h))]
    cache = embed_cache if embed_cache is not None else {}
    best: dict[str, dict] = {}
    for target in targets:
        if target.q and target.q not in cache:
            try:
                cache[target.q] = search.embed_text(target.q)
            except Exception as exc:  # noqa: BLE001 — no embedding: words only
                logger.info("suggestions: embedding failed (%s)", exc)
                cache[target.q] = []
        results = search.search_agents(
            q=target.q, role=target.role, topics=",".join(target.topics), limit=PER_TARGET_SEARCH,
            searcher=card, less_like=less_like, relax=True, keep_role=True,
            query_vec=cache.get(target.q, []) if target.q else [],
        )
        for result in results:
            two_way = list(result.get("two_way") or [])
            score = float(result.get("match_score") or 0.0) * _near(card.identity.location, result.get("location") or "")
            person = _person(result, target, min(score, 1.0), two_way)
            if not person["handle"] or _excluded(person, ex):
                continue
            current = best.get(person["handle"])
            if current is None or person["score"] > current["score"]:
                best[person["handle"]] = person
    return sorted(best.values(), key=_rank_key)


def diversify(people: list[dict], k: int) -> list[dict]:
    """The first k people, at most MAX_PER_TARGET per target and MAX_PER_COMPANY per company."""
    per_target: dict[str, int] = {}
    per_company: dict[str, int] = {}
    out = []
    for p in people:
        company = (p.get("company") or "").strip().lower()
        if per_target.get(p.get("target") or "", 0) >= MAX_PER_TARGET:
            continue
        if company and per_company.get(company, 0) >= MAX_PER_COMPANY:
            continue
        per_target[p.get("target") or ""] = per_target.get(p.get("target") or "", 0) + 1
        if company:
            per_company[company] = per_company.get(company, 0) + 1
        out.append(p)
        if len(out) >= k:
            break
    return out


# --- Stored suggestions -----------------------------------------------------------------------

def refresh(row: dict, *, embed_cache: dict | None = None) -> int:
    """Replace this card's stored suggestions with its top TOP_N; the number written."""
    people = compute(row, embed_cache=embed_cache)[:TOP_N]
    now = _now().isoformat()
    sb = _sb()
    sb.table("card_suggestions").delete().eq("card_id", row["id"]).execute()
    if people:
        sb.table("card_suggestions").insert([{
            "card_id": row["id"], "candidate_card_id": p["card_id"], "target": p["target"],
            "score": p["score"], "why": p["why"], "two_way": p["two_way"], "computed_at": now,
        } for p in people if p.get("card_id")]).execute()
    return len(people)


def refresh_all(handle: str | None = None) -> dict:
    """The nightly job: every claimed published card (or one handle). One search per target per
    card, and each distinct target text is embedded once for the whole run."""
    from services import cards as cards_service

    want = (handle or "").strip().lstrip("@").lower()
    rows = [r for r in cards_service.list_published_rows(columns=_ROW_COLUMNS) if _claimed(r)]
    if want:
        rows = [r for r in rows if (r.get("handle") or "").lower() == want]
    stats = {"cards": len(rows), "written": 0, "errors": 0}
    cache: dict = {}
    for row in rows:
        try:
            stats["written"] += refresh(row, embed_cache=cache)
        except Exception as exc:  # noqa: BLE001 — one card's failure never stops the run
            stats["errors"] += 1
            logger.warning("suggestions refresh failed handle=%s err=%s", row.get("handle"), exc)
            if stats["errors"] == 1 and _missing_table(exc):
                stats["table_missing"] = True
                break
    return stats


def _missing_table(exc: Exception) -> bool:
    text = str(exc)
    return "42P01" in text or "card_suggestions" in text and "does not exist" in text


def _stored(row: dict) -> list[dict] | None:
    """The stored list with today's card data, or None when there is none, it is stale, or the
    table can't be read (then the caller computes live)."""
    try:
        stored = (_sb().table("card_suggestions").select("candidate_card_id,target,score,why,two_way,computed_at")
                  .eq("card_id", row["id"]).execute().data or [])
    except Exception as exc:  # noqa: BLE001
        _tables_unavailable(exc)
        return None
    if not stored:
        return None
    oldest = min(str(s.get("computed_at") or "") for s in stored)
    if oldest < (_now() - timedelta(hours=FRESH_HOURS)).isoformat():
        return None
    ids = [s["candidate_card_id"] for s in stored]
    cards = {c["id"]: c for c in (_sb().table("agent_profile_cards").select(_ROW_COLUMNS).in_("id", ids)
                                  .eq("status", "published").execute().data or [])}
    from services.search import current_company

    people = []
    for s in stored:
        c = cards.get(s["candidate_card_id"])
        card = _card(c) if c and _claimed(c) else None
        if card is None:
            continue          # unpublished or unclaimed since the job ran
        people.append({
            "handle": c["handle"], "card_id": c["id"], "name": card.identity.name, "headline": card.identity.headline,
            "location": card.identity.location, "avatar_url": card.identity.avatar_url or "",
            "company": current_company(card), "url": f"{config.SITE_BASE_URL.rstrip('/')}/p/{c['handle']}",
            "score": float(s.get("score") or 0.0), "two_way": bool(s.get("two_way")), "two_way_kinds": [],
            "target": s.get("target") or "", "why": list(s.get("why") or []), "relaxed": [],
        })
    return sorted(people, key=_rank_key)


def _recently_emailed(card_id: str) -> dict[str, float]:
    """candidate card id -> the best score they had when the digest showed them, last COOLDOWN_DAYS."""
    since = (_now() - timedelta(days=COOLDOWN_DAYS)).isoformat()
    try:
        rows = (_sb().table("card_suggestion_impressions").select("candidate_card_id,score")
                .eq("card_id", card_id).eq("surface", "digest").gte("shown_at", since).execute().data or [])
    except Exception as exc:  # noqa: BLE001
        _tables_unavailable(exc)
        return {}
    shown: dict[str, float] = {}
    for r in rows:
        cid = r.get("candidate_card_id")
        if cid:
            shown[cid] = max(shown.get(cid, 0.0), float(r.get("score") or 0.0))
    return shown


def for_owner_row(row: dict, surface: str, k: int = 2, *, with_outside: bool = True) -> dict:
    """{"handle", "people", "outside"} as `surface` shows them."""
    handle = row.get("handle") or ""
    empty = {"handle": handle, "people": [], "outside": []}
    card = _card(row)
    if card is None or not _claimed(row):
        return empty
    ex = exclusions(row)
    people = _stored(row)
    if people is None:
        people = compute(row, ex=ex)
    people = [p for p in people if not _excluded(p, ex)]
    if surface == "digest":
        shown = _recently_emailed(row["id"])
        people = [p for p in people if p["card_id"] not in shown or p["score"] > shown[p["card_id"]] + RESHOW_GAIN]
    people = diversify(people, k)
    outside: list[dict] = []
    if with_outside and len(people) < 2:
        from services import suggested_people
        outside = suggested_people.outside_for(card, people)
    return {"handle": handle, "people": people, "outside": outside}


def for_owner(handle: str, surface: str, k: int = 2) -> dict | None:
    """for_owner_row by handle; None when there is no such published card."""
    row = owner_row(handle)
    return for_owner_row(row, surface, k) if row else None


# --- What owners saw and did ------------------------------------------------------------------

def record_impressions(card_id: str, surface: str, people: list[dict]) -> int:
    """One row per person shown. Owner home is shown many times a day: at most one row per
    person per day there. Best effort; the number written."""
    people = [p for p in people if p.get("card_id")]
    if not card_id or not people or surface not in SURFACES:
        return 0
    try:
        if surface == "owner_home":
            since = (_now() - timedelta(days=1)).isoformat()
            seen = {r["candidate_card_id"] for r in (
                _sb().table("card_suggestion_impressions").select("candidate_card_id").eq("card_id", card_id)
                .eq("surface", surface).gte("shown_at", since).execute().data or [])}
            people = [p for p in people if p["card_id"] not in seen]
        if not people:
            return 0
        now = _now().isoformat()
        _sb().table("card_suggestion_impressions").insert([
            {"card_id": card_id, "candidate_card_id": p["card_id"], "surface": surface,
             "score": p.get("score"), "shown_at": now} for p in people]).execute()
        return len(people)
    except Exception as exc:  # noqa: BLE001
        _tables_unavailable(exc)
        return 0


def _mark(card_id: str, candidate_card_id: str, action: str, surface: str) -> None:
    rows = (_sb().table("card_suggestion_impressions").select("id,action").eq("card_id", card_id)
            .eq("candidate_card_id", candidate_card_id).order("shown_at", desc=True).limit(1).execute().data or [])
    if rows:
        _sb().table("card_suggestion_impressions").update({"action": action}).eq("id", rows[0]["id"]).execute()
    else:
        _sb().table("card_suggestion_impressions").insert({
            "card_id": card_id, "candidate_card_id": candidate_card_id, "surface": surface,
            "shown_at": _now().isoformat(), "action": action}).execute()


def feedback(row: dict, candidate_handle: str, action: str, surface: str = "owner_home") -> dict:
    """"hide" or "not_relevant" on a suggested person: never suggested again. Also written to the
    owner's match preferences (hide_person / less_like_this) when network controls are on, so
    their searches learn it too."""
    from fastapi import HTTPException

    if action not in ("hide", "not_relevant"):
        raise HTTPException(422, "action must be hide or not_relevant")
    target = owner_row(candidate_handle)
    if not target or target.get("id") == row.get("id"):
        raise HTTPException(404, "Card not found")
    recorded = True
    try:
        _mark(row["id"], target["id"], action, surface if surface in SURFACES else "owner_home")
    except Exception as exc:  # noqa: BLE001
        _tables_unavailable(exc)
        recorded = False
    from services import trust
    remembered = False
    if trust.enabled() and row.get("owner_user_id"):
        from services import match_prefs
        try:
            match_prefs.add(row["owner_user_id"], "hide_person" if action == "hide" else "less_like_this", target["handle"])
            remembered = True
        except HTTPException as exc:
            logger.info("suggestions: match preference not saved (%s)", exc.detail)
    if not (recorded or remembered):
        raise HTTPException(503, "Could not save that right now")
    return {"ok": True, "handle": target["handle"], "action": action}


def mark_connected(requester_card_id: str, recipient_card_id: str) -> None:
    """A connection request to someone the owner was suggested: their newest impression becomes
    "connect". Best effort; never fails the request."""
    try:
        rows = (_sb().table("card_suggestion_impressions").select("id,action").eq("card_id", requester_card_id)
                .eq("candidate_card_id", recipient_card_id).order("shown_at", desc=True).limit(1).execute().data or [])
        if rows and not rows[0].get("action"):
            _sb().table("card_suggestion_impressions").update({"action": "connect"}).eq("id", rows[0]["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.info("suggestions: connect not recorded (%s)", exc)
