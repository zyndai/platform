"""Which country a place is in, so "India" matches a card that says "Gurgaon".

Card locations are free text and mostly name a city. A search for a country used to need the
country's name in the card, so "investors in India" missed everyone in Bengaluru who left it
out. This is a small copy of the places memory's people_query already knows
(services/memory/app/services/people_query.py: CITIES, COUNTRIES); it moves to
packages/contracts once that exists, and the two tables must stay in step until then.
"""
from __future__ import annotations

import re

# ISO alpha-2 -> (name shown to people, other spellings). Only the first name is ever displayed.
_COUNTRIES: dict[str, tuple[str, ...]] = {
    "IN": ("india",), "US": ("united states", "usa", "us", "u.s.", "america"),
    "GB": ("united kingdom", "uk", "u.k.", "england", "britain"),
    "DE": ("germany",), "FR": ("france",), "CA": ("canada",), "SG": ("singapore",),
    "AE": ("united arab emirates", "uae"), "AU": ("australia",), "BR": ("brazil",),
    "NL": ("netherlands",), "ES": ("spain",), "IT": ("italy",), "IL": ("israel",),
    "JP": ("japan",), "CN": ("china",), "CH": ("switzerland",), "SE": ("sweden",),
    "IE": ("ireland",), "NG": ("nigeria",), "KE": ("kenya",), "ID": ("indonesia",),
    "MX": ("mexico",), "KR": ("south korea", "korea"), "PT": ("portugal",), "PL": ("poland",),
    "EE": ("estonia",), "HK": ("hong kong",), "SA": ("saudi arabia",), "EG": ("egypt",),
    "ZA": ("south africa",), "NO": ("norway",), "DK": ("denmark",), "FI": ("finland",),
    "BE": ("belgium",), "AT": ("austria",), "NZ": ("new zealand",), "AR": ("argentina",),
    "CO": ("colombia",), "CL": ("chile",), "VN": ("vietnam",), "PH": ("philippines",),
    "TH": ("thailand",), "MY": ("malaysia",), "PK": ("pakistan",), "BD": ("bangladesh",),
    "LK": ("sri lanka",), "TR": ("turkey",), "UA": ("ukraine",),
}
# city spelling -> ISO alpha-2
_CITIES: dict[str, str] = {
    **{c: "IN" for c in (
        "bangalore", "bengaluru", "mumbai", "bombay", "delhi", "new delhi", "hyderabad", "pune",
        "chennai", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad")},
    **{c: "US" for c in (
        "san francisco", "sf", "bay area", "new york", "nyc", "boston", "seattle", "austin",
        "los angeles", "chicago", "miami", "denver")},
    "london": "GB", "berlin": "DE", "munich": "DE", "paris": "FR", "toronto": "CA",
    "vancouver": "CA", "dubai": "AE", "tel aviv": "IL", "amsterdam": "NL", "stockholm": "SE",
    "lisbon": "PT", "barcelona": "ES", "madrid": "ES", "sydney": "AU", "melbourne": "AU",
    "tokyo": "JP", "lagos": "NG", "nairobi": "KE", "jakarta": "ID", "sao paulo": "BR",
}
_COUNTRY_CODE = {spelling: code for code, names in _COUNTRIES.items() for spelling in names}

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _norm(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", (text or "").lower()).split())


def _phrase(norm: str, spellings) -> str:
    """Longest spelling that appears in `norm` as whole words, else ''."""
    padded = f" {norm} "
    return next((s for s in sorted(spellings, key=len, reverse=True) if f" {_norm(s)} " in padded), "")


def country_code(text: str) -> str:
    """ISO country of a place ("Gurgaon", "Pune, India", "India"), or '' when unknown.
    A country named in the text wins over the city's own country."""
    norm = _norm(text)
    if not norm:
        return ""
    country = _phrase(norm, _COUNTRY_CODE)
    if country:
        return _COUNTRY_CODE[country]
    city = _phrase(norm, _CITIES)
    return _CITIES[city] if city else ""


def has_city(text: str) -> bool:
    return bool(_phrase(_norm(text), _CITIES))


def country_name(text: str) -> str:
    """Display name of the country `text` is in ("India"), or ''."""
    names = _COUNTRIES.get(country_code(text))
    return names[0].title() if names else ""


def widen(location: str) -> str:
    """A city widened to its country ("Pune" -> "India"); '' when it is not a known city, or is
    already a country, so there is nothing broader to try."""
    if not has_city(location):
        return ""
    return country_name(location)


def same_country(wanted: str, have: str) -> bool:
    """True when `wanted` names just a country and `have` is somewhere in it."""
    if has_city(wanted):
        return False
    code = _COUNTRY_CODE.get(_phrase(_norm(wanted), _COUNTRY_CODE), "")
    return bool(code) and country_code(have) == code


def spellings_in_country(wanted: str) -> list[str]:
    """Every spelling of a country and of the cities geo knows in it, when `wanted` names just a
    country ("India" -> india, pune, gurgaon, ...); [] otherwise. A database pre-filter uses these
    to keep every card same_country() would accept."""
    if has_city(wanted):
        return []
    code = _COUNTRY_CODE.get(_phrase(_norm(wanted), _COUNTRY_CODE), "")
    if not code:
        return []
    return [*_COUNTRIES[code], *(city for city, c in _CITIES.items() if c == code)]
