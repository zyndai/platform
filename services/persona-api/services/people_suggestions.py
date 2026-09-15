"""
People Suggestions — proactive "Similar people" surfaced on the People page.

Turns a persona's own profile (title/organization/location/interests from
persona_agents.profile, headline/experience/skills from linkedin_profiles)
into a handful of QuickEnrich searches ("recipes"), each labeled with a
plain-language reason, and stores the results in suggested_contacts so the
People page and the get_suggested_people chat tool can read them without
re-querying QuickEnrich on every page load.

Four recipes, run independently and then merged:
  same_role          — people with the user's own job title
  same_company       — colleagues at the user's own company
  near_you           — people (in the user's own role, if known) near the
                        user's own city
  shared_interests   — LLM-planned filters from interests/skills, mapped
                        onto the QuickEnrich dimensions that can stand in
                        for "same interests" (industry, company-About
                        keywords, peer titles) — there's no per-person
                        interest filter on the API itself. Falls back to a
                        plain company-keyword search when the LLM call
                        fails or nothing is configured.

Every recipe search goes through mcp.tools.quickenrich.search_people_database,
so it's FREE (contact-finder), auto-corrects invented enum values via
services/quickenrich_lookups.py, and warms services/quickenrich_cache.py —
so a later email/phone reveal on one of these people is a cache hit.

A person can match more than one recipe; they're assigned to exactly one
"primary" section (most-specific recipe wins) so the same card never shows
up twice across rows, with the match count folded into their score.

This module is deliberately synchronous, like services/quickenrich.py —
callers run it via asyncio.to_thread from background tasks and the weekly
refresh loop (agent/people_suggestions_loop.py). Nothing in here raises for
a "normal" failure (not configured, no signals, one recipe erroring) — every
path returns a {status: ...} dict so a bad run never takes down whatever
triggered it.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import config
from services import quickenrich as qe
from services import quickenrich_cache as cache

logger = logging.getLogger(__name__)

TABLE = "suggested_contacts"
RUNS_TABLE = "suggested_contact_runs"

# How many people to keep per recipe / in total. Recipes are queried with
# headroom (2x) since some results get dropped as duplicates or as the user
# themselves.
MAX_PER_RECIPE = 6
RECIPE_QUERY_LIMIT = 12

# Manual "Refresh suggestions" cooldown — matches the weekly loop's cadence
# loosely (you can force a refresh far more often than the loop runs, but
# not on every click).
MANUAL_COOLDOWN_SECONDS = 3600

RECIPE_TITLES = {
    "same_role": "Same role",
    "same_company": "At your company",
    "near_you": "Near you",
    "shared_interests": "Shared interests",
}

# Priority order used to assign a person who matched multiple recipes to
# exactly one section — most specific/intentional match wins.
_RECIPE_PRIORITY = ["same_company", "shared_interests", "same_role", "near_you"]


def _sb():
    return config.get_supabase()


# ── Signal collection ───────────────────────────────────────────────

def _location_text(raw) -> str:
    """
    Pull a plain "City, Region, Country" string out of the profile actor's
    `location` field, which — confirmed against a live scrape row — is a
    nested object ({parsed: {city, text, ...}, linkedinText, countryCode}),
    not a plain string. Stringifying it directly (str(raw)) produces
    garbage like "{'parsed': {'city': 'Washington', ...". Tolerates a
    plain string too, in case a differently-shaped payload ever lands here.
    """
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        parsed = raw.get("parsed")
        if isinstance(parsed, dict) and parsed.get("text"):
            return str(parsed["text"]).strip()
        if raw.get("linkedinText"):
            return str(raw["linkedinText"]).strip()
    return ""


def collect_signals(user_id: str) -> dict:
    """
    Gather what we know about the user: persona profile + LinkedIn profile.

    Returns a flat dict — title, organization, location, city, interests
    (list), skills (list), own_linkedin_url — with "" / [] for anything
    missing. Never raises; a lookup failure just yields fewer signals for
    the recipes below to work with.
    """
    sb = _sb()
    signals: dict = {
        "title": "", "organization": "", "location": "", "city": "",
        "interests": [], "skills": [], "own_linkedin_url": "",
    }

    try:
        persona_q = (
            sb.table("persona_agents")
            .select("profile")
            .eq("user_id", user_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("[people-suggestions] persona lookup failed for %s: %s", user_id, e)
        persona_q = None

    if persona_q and persona_q.data:
        profile = persona_q.data[0].get("profile") or {}
        signals["title"] = str(profile.get("title") or "").strip()
        signals["organization"] = str(profile.get("organization") or "").strip()
        signals["location"] = str(profile.get("location") or "").strip()
        raw_interests = profile.get("interests")
        if isinstance(raw_interests, str):
            signals["interests"] = [s.strip() for s in raw_interests.split(",") if s.strip()]
        elif isinstance(raw_interests, list):
            signals["interests"] = [str(s).strip() for s in raw_interests if s]

    try:
        li_q = (
            sb.table("linkedin_profiles")
            .select("raw_profile,profile_url")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("[people-suggestions] linkedin lookup failed for %s: %s", user_id, e)
        li_q = None

    if li_q and li_q.data:
        row = li_q.data[0]
        signals["own_linkedin_url"] = str(row.get("profile_url") or "").strip()
        profile = row.get("raw_profile") or {}
        if not signals["title"] or not signals["organization"]:
            experience = profile.get("experience") or []
            first = experience[0] if experience and isinstance(experience[0], dict) else {}
            if not signals["title"]:
                # harvestapi's profile actor names this field "position", not
                # "title" — confirmed against a live scrape row. "title" is
                # kept as a fallback in case a differently-shaped payload
                # (a different actor version, say) ever uses it instead.
                signals["title"] = str(first.get("position") or first.get("title") or "").strip()
            if not signals["organization"]:
                signals["organization"] = str(
                    first.get("companyName") or first.get("company") or ""
                ).strip()
        if not signals["location"]:
            signals["location"] = _location_text(profile.get("location"))
        for skill in (profile.get("skills") or [])[:10]:
            name = skill.get("name") if isinstance(skill, dict) else skill
            name = str(name or "").strip()
            if name and name not in signals["skills"]:
                signals["skills"].append(name)

    # A bare city out of "San Francisco Bay Area" / "Bengaluru, Karnataka, India".
    signals["city"] = signals["location"].split(",")[0].strip() if signals["location"] else ""

    return signals


# ── Recipes ──────────────────────────────────────────────────────────

def build_recipes(signals: dict) -> list[dict]:
    """
    Turn collected signals into QuickEnrich search recipes.

    Each recipe is {key, title, reason, filters} where `filters` are kwargs
    for mcp.tools.quickenrich.search_people_database. A recipe is omitted
    entirely when there's nothing meaningful to search on.
    """
    recipes: list[dict] = []
    title = signals.get("title") or ""
    organization = signals.get("organization") or ""
    city = signals.get("city") or ""

    if title:
        recipes.append({
            "key": "same_role",
            "title": RECIPE_TITLES["same_role"],
            "reason": f"Also working as {title}",
            "filters": {"titles": [title]},
        })

    if organization:
        recipes.append({
            "key": "same_company",
            "title": RECIPE_TITLES["same_company"],
            "reason": f"Colleagues at {organization}",
            "filters": {"company_names": [organization]},
        })

    if city:
        filters = {"cities": [city]}
        reason = f"People based near {city}"
        if title:
            filters["titles"] = [title]
            reason = f"{title}s based near {city}"
        recipes.append({
            "key": "near_you",
            "title": RECIPE_TITLES["near_you"],
            "reason": reason,
            "filters": filters,
        })

    interest_recipe = _plan_shared_interests(signals)
    if interest_recipe:
        recipes.append(interest_recipe)

    return recipes


def _plan_shared_interests(signals: dict) -> dict | None:
    """
    Build the 'shared_interests' recipe from interests/skills.

    Tries an LLM call to translate interests into industry + company
    keywords + peer titles (the QuickEnrich dimensions that can stand in
    for "same interests" — there's no per-person interest filter). Falls
    back to a plain company-keyword search built directly from the raw
    interest/skill words when the LLM is unavailable or returns nothing
    usable. Returns None when there's nothing to plan from at all.
    """
    interests = (signals.get("interests") or [])[:6]
    skills = (signals.get("skills") or [])[:6]
    words = interests + [s for s in skills if s not in interests]
    if not words:
        return None

    planned = _llm_plan_interest_filters(words, signals)
    if planned:
        filters, reason = planned
        return {
            "key": "shared_interests",
            "title": RECIPE_TITLES["shared_interests"],
            "reason": reason,
            "filters": filters,
        }

    filters: dict = {"company_keywords": words[:4]}
    if signals.get("title"):
        filters["titles"] = [signals["title"]]
    return {
        "key": "shared_interests",
        "title": RECIPE_TITLES["shared_interests"],
        "reason": f"Also into {', '.join(words[:3])}",
        "filters": filters,
    }


def _llm_plan_interest_filters(words: list[str], signals: dict) -> tuple[dict, str] | None:
    """
    One LLM call: interests/skills -> QuickEnrich filter dimensions.

    Returns (filters, reason) or None on any failure — this is a nice-to-have
    layer over the rule-based fallback in _plan_shared_interests, never a
    hard dependency of it.
    """
    try:
        from agent.orchestrator import _get_provider
    except Exception as e:
        logger.debug("[people-suggestions] provider import failed: %s", e)
        return None

    prompt = (
        "A person's interests/skills are given below. Suggest a JSON object "
        "for finding OTHER professionals who share these interests, using ONLY "
        "these keys: titles (list of 1-3 job titles such people might hold), "
        "industries (list of 0-2 company industries), company_keywords (list "
        "of 1-4 words likely to appear in a matching company's LinkedIn About "
        "text), and reason (a short sentence like "
        "'Also into AI agents and fintech'). Reply with ONLY the JSON object, "
        "no markdown, no explanation.\n\n"
        f"Interests/skills: {', '.join(words)}\n"
    )
    if signals.get("title"):
        prompt += f"Their own current title: {signals['title']}\n"

    try:
        provider = _get_provider()
        text, _ = provider.chat_with_tools(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Return the JSON object."},
            ],
            [],
        )
    except Exception as e:
        logger.warning("[people-suggestions] interest-planning LLM call failed: %s", e)
        return None

    if not text:
        return None

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    filters: dict = {}
    titles = data.get("titles")
    if isinstance(titles, list) and titles:
        filters["titles"] = [str(t).strip() for t in titles if str(t).strip()][:3]
    industries = data.get("industries")
    if isinstance(industries, list) and industries:
        filters["industries"] = [str(i).strip() for i in industries if str(i).strip()][:2]
    keywords = data.get("company_keywords")
    if isinstance(keywords, list) and keywords:
        filters["company_keywords"] = [str(k).strip() for k in keywords if str(k).strip()][:4]

    if not filters:
        return None

    reason = str(data.get("reason") or "").strip() or f"Also into {', '.join(words[:3])}"
    return filters, reason


# ── Run (generate + persist) ────────────────────────────────────────

def run_for_user(user_id: str, *, manual: bool = False) -> dict:
    """
    Generate (or refresh) this user's suggested-people shortlist.

    Runs each recipe's QuickEnrich search, merges + dedups the combined
    results, scores and ranks them, replaces the user's suggested_contacts
    rows, and stamps suggested_contact_runs. Never raises.
    """
    if not qe.is_configured():
        _stamp_run(user_id, status="skipped", detail="QuickEnrich not configured", manual=manual)
        return {"status": "skipped", "reason": "not_configured", "recipes": []}

    try:
        signals = collect_signals(user_id)
    except Exception as e:
        logger.warning("[people-suggestions] signal collection failed for %s: %s", user_id, e)
        signals = {}

    recipes = build_recipes(signals)
    if not recipes:
        _stamp_run(user_id, status="skipped", detail="no signals to build recipes from", manual=manual)
        return {"status": "skipped", "reason": "no_signals", "recipes": []}

    # Imported lazily — mcp.tools.quickenrich imports this module (for the
    # get_suggested_people tool), so a module-level import here would cycle.
    from mcp.tools.quickenrich import search_people_database

    own_linkedin = cache.normalize_linkedin(signals.get("own_linkedin_url", ""))

    # cache_key -> {"person": shaped result, "recipes": [recipe keys that matched]}
    merged: dict[str, dict] = {}
    recipe_order: list[str] = []
    recipe_by_key = {r["key"]: r for r in recipes}

    for recipe in recipes:
        recipe_order.append(recipe["key"])
        try:
            result = search_people_database(
                user_id, limit=RECIPE_QUERY_LIMIT, **recipe["filters"]
            )
        except Exception as e:
            logger.warning(
                "[people-suggestions] recipe %s failed for %s: %s", recipe["key"], user_id, e
            )
            continue
        if result.get("status") != "success":
            continue
        for person in result.get("results", []):
            linkedin_url = person.get("linkedin_url") or ""
            if own_linkedin and cache.normalize_linkedin(linkedin_url) == own_linkedin:
                continue  # that's the user themselves
            key = cache.contact_key(
                linkedin_url=linkedin_url,
                company_url=person.get("company_url", ""),
                first_name=person.get("first_name", ""),
                last_name=person.get("last_name", ""),
            )
            if not key:
                continue
            entry = merged.setdefault(key, {"person": person, "recipes": []})
            entry["recipes"].append(recipe["key"])
            # Prefer whichever copy of the record looks richer.
            if person.get("has_email") and not entry["person"].get("has_email"):
                entry["person"] = person

    now = datetime.now(timezone.utc).isoformat()

    if not merged:
        _replace_suggestions(user_id, [])
        _stamp_run(user_id, status="ok", detail="0 matches", manual=manual)
        return {"status": "success", "count": 0, "generated_at": now, "recipes": []}

    # Assign each person to exactly one "primary" recipe so the same card
    # never appears in two sections; fold the multi-match into their score.
    priority = {k: i for i, k in enumerate(_RECIPE_PRIORITY)}
    grouped: dict[str, list[tuple[str, dict, float]]] = {}
    for key, entry in merged.items():
        matched = entry["recipes"]
        primary = min(matched, key=lambda k: priority.get(k, 99))
        person = entry["person"]
        score = (
            len(matched) * 1.0
            + (0.5 if person.get("has_email") else 0)
            + (0.25 if person.get("has_phone") else 0)
        )
        grouped.setdefault(primary, []).append((key, person, score))

    rows_out: list[dict] = []
    sections: list[dict] = []
    for recipe_key in recipe_order:
        items = grouped.get(recipe_key) or []
        if not items:
            continue
        items.sort(key=lambda t: t[2], reverse=True)
        items = items[:MAX_PER_RECIPE]
        recipe = recipe_by_key[recipe_key]
        section_items = []
        for rank, (key, person, score) in enumerate(items):
            rows_out.append({
                "user_id": user_id,
                "cache_key": key,
                "recipe": recipe_key,
                "reason": recipe["reason"],
                "score": score,
                "rank": rank,
                "generated_at": now,
                "updated_at": now,
            })
            section_items.append(person)
        sections.append({
            "key": recipe_key,
            "title": recipe["title"],
            "reason": recipe["reason"],
            "items": section_items,
        })

    _replace_suggestions(user_id, rows_out)
    _stamp_run(
        user_id, status="ok",
        detail=f"{len(rows_out)} matches across {len(sections)} recipes",
        manual=manual,
    )

    return {"status": "success", "count": len(rows_out), "generated_at": now, "recipes": sections}


def _replace_suggestions(user_id: str, rows: list[dict]) -> None:
    """Swap in a fresh shortlist — delete then insert, so people who no
    longer match anything actually disappear instead of accumulating."""
    try:
        _sb().table(TABLE).delete().eq("user_id", user_id).execute()
        if rows:
            _sb().table(TABLE).insert(rows).execute()
    except Exception as e:
        logger.warning("[people-suggestions] replace failed for %s: %s", user_id, e)


def _stamp_run(user_id: str, *, status: str, detail: str = "", manual: bool = False) -> None:
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "user_id": user_id,
        "last_run_at": now,
        "status": status,
        "detail": detail[:500],
        "updated_at": now,
    }
    if manual:
        row["last_manual_at"] = now
    try:
        _sb().table(RUNS_TABLE).upsert(row, on_conflict="user_id").execute()
    except Exception as e:
        logger.warning("[people-suggestions] run stamp failed for %s: %s", user_id, e)


# ── Read ─────────────────────────────────────────────────────────────

def _get_run(user_id: str) -> dict:
    try:
        q = _sb().table(RUNS_TABLE).select("*").eq("user_id", user_id).limit(1).execute()
        if q.data:
            return q.data[0]
    except Exception as e:
        logger.warning("[people-suggestions] run read failed for %s: %s", user_id, e)
    return {}


def get_run_state(user_id: str) -> dict:
    """Public wrapper around _get_run — used by the weekly refresh loop
    (agent/people_suggestions_loop.py) to check due-ness without reaching
    into a private helper."""
    return _get_run(user_id)


def refresh_cooldown_seconds(user_id: str) -> int:
    """Public: seconds until this user's manual-refresh cooldown clears (0
    when a refresh is allowed right now). Used by the /refresh endpoint's
    rate limit (api/people.py) without reaching into private helpers."""
    return _cooldown_seconds(_get_run(user_id))


def _cooldown_seconds(run: dict) -> int:
    stamp = run.get("last_manual_at")
    if not stamp:
        return 0
    try:
        last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return max(0, int(MANUAL_COOLDOWN_SECONDS - elapsed))


def is_due(run: dict, *, interval_seconds: int) -> bool:
    """True when a user has no run yet, or their last run is older than
    `interval_seconds` — used by the weekly refresh loop."""
    stamp = run.get("last_run_at")
    if not stamp:
        return True
    try:
        last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() > interval_seconds


def get_suggestions(user_id: str) -> dict:
    """
    Read the stored shortlist back, grouped by recipe, joined against
    enriched_contacts for the full shaped person record.

    Returns {status, generated_at, sections, can_refresh, cooldown_seconds}.
    `status` is "empty" when nothing has been generated yet (new user, or
    QuickEnrich not configured) rather than an error.
    """
    from mcp.tools.quickenrich import _shape_cached  # lazy — see run_for_user

    try:
        rows_q = (
            _sb().table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("recipe")
            .order("rank")
            .execute()
        )
        rows = rows_q.data or []
    except Exception as e:
        logger.warning("[people-suggestions] read failed for %s: %s", user_id, e)
        rows = []

    run = _get_run(user_id)
    cooldown = _cooldown_seconds(run)

    if not rows:
        return {
            "status": "empty",
            "generated_at": run.get("last_run_at"),
            "sections": [],
            "can_refresh": cooldown <= 0,
            "cooldown_seconds": cooldown,
        }

    cache_keys = list({r["cache_key"] for r in rows})
    contacts_by_key: dict[str, dict] = {}
    try:
        contacts_q = (
            _sb().table(cache.CONTACTS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .in_("cache_key", cache_keys)
            .execute()
        )
        contacts_by_key = {c["cache_key"]: c for c in (contacts_q.data or [])}
    except Exception as e:
        logger.warning("[people-suggestions] contact join failed for %s: %s", user_id, e)

    sections_by_key: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        recipe = row["recipe"]
        if recipe not in sections_by_key:
            sections_by_key[recipe] = {
                "key": recipe,
                "title": RECIPE_TITLES.get(recipe, recipe.replace("_", " ").title()),
                "reason": row.get("reason") or "",
                "items": [],
            }
            order.append(recipe)
        contact = contacts_by_key.get(row["cache_key"])
        if not contact:
            continue
        sections_by_key[recipe]["items"].append(_shape_cached(contact))

    sections = [sections_by_key[k] for k in order if sections_by_key[k]["items"]]

    return {
        "status": "success" if sections else "empty",
        "generated_at": run.get("last_run_at"),
        "sections": sections,
        "can_refresh": cooldown <= 0,
        "cooldown_seconds": cooldown,
    }
