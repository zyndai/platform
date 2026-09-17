"""LinkedIn profile + recent posts via Apify actors (no cookies).

Profile: data-slayer~linkedin-profile-scraper (primary) — experience[] with
         job_title, company_name, job_started_on ("M-YYYY"), job_still_working
         dev_fusion / atomus remain fallbacks
Posts:   atomus~linkedin-posts-scraper-pro           — own posts only, newest first, capped at 7
         Jina Reader Activity section                — free fallback when the posts actor
                                                       is unavailable (billing caps, errors)

Both profile and posts fetches run concurrently. Falls back to Jina Reader on Apify failure.
Returns tuple[str, dict | None] — (profile_text, linkedin_stats).
"""

import asyncio
import re
from urllib.parse import urlparse

import httpx

import config

_APIFY_BASE = "https://api.apify.com/v2"
# data-slayer: structured experience[] + logos. 99%+ success, same vendor as X scrape.
# dev_fusion / atomus remain fallbacks if data-slayer returns empty.
_ACTOR_PROFILE_PRIMARY  = "data-slayer~linkedin-profile-scraper"
_ACTOR_PROFILE_DEV_FUSION = "dev_fusion/linkedin-profile-scraper"
_ACTOR_PROFILE_FALLBACK = "atomus~linkedin-profile-scraper"
_ACTOR_POSTS = "atomus~linkedin-posts-scraper-pro"
_MAX_POSTS = 7
_MAX_CHARS = 12_000

# "[Satya Nadella shared this](https://www.linkedin.com/posts/…)" — how Jina's
# markdown renders every entry in the public-profile Activity section.
_JINA_MARKER = re.compile(
    r"^\[[^\]]*? (shared|reposted) this\]\((https://www\.linkedin\.com/posts/[^)]+)\)"
)
_JINA_MORE = re.compile(r"\[\.\.\.more\]\([^)]+\)")
_JINA_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")


def _strip_md(text: str) -> str:
    """Markdown links/images → plain text, for clean post excerpts."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # images
    text = _JINA_MD_LINK.sub(r"\1", text)  # links
    return re.sub(r"\s+", " ", text).strip()


def _handle_from_url(url: str) -> str | None:
    """Extract the profile handle. LinkedIn URLs are /in/{handle}."""
    parts = urlparse(url).path.strip("/").split("/")
    if not parts or not parts[0]:
        return None
    if len(parts) >= 2 and parts[0] == "in":
        return parts[1]
    return parts[0]


def _compact_connections(n: int | str | None) -> str:
    if n is None:
        return "500+"
    try:
        v = int(str(n).replace(",", "").replace("+", "").strip())
        if v >= 500:
            return "500+"
        return str(v)
    except (ValueError, TypeError):
        return str(n)


def _skill_name(s) -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return s.get("name") or s.get("skill") or ""
    return ""


_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_yyyymm(s: str | None) -> str:
    """Parse "YYYY-MM" string (dev_fusion format) → "Mon YYYY"."""
    if not s:
        return ""
    parts = s.split("-")
    if len(parts) >= 2:
        try:
            year, month = int(parts[0]), int(parts[1])
            if 1 <= month <= 12:
                return f"{_MONTH_ABBR[month]} {year}"
        except (ValueError, IndexError):
            pass
    try:
        return str(int(parts[0]))  # year-only fallback
    except (ValueError, IndexError):
        return s


def _duration_from_yyyymm(start: str | None, end: str | None) -> str:
    """Compute duration string from "YYYY-MM" strings (dev_fusion format)."""
    if not start:
        return ""
    from datetime import datetime
    try:
        sp = start.split("-")
        sy, sm = int(sp[0]), int(sp[1]) if len(sp) > 1 else 1
        if end:
            ep = end.split("-")
            ey, em = int(ep[0]), int(ep[1]) if len(ep) > 1 else 1
        else:
            now = datetime.now()
            ey, em = now.year, now.month
        months = (ey - sy) * 12 + (em - sm)
        return _months_str(months) if months > 0 else ""
    except (ValueError, IndexError):
        return ""


def _fmt_date(d: dict | None) -> str:
    if not d or not isinstance(d, dict):
        return ""
    month = d.get("month") or 0
    year = d.get("year") or 0
    if year and month and 1 <= month <= 12:
        return f"{_MONTH_ABBR[month]} {year}"
    if year:
        return str(year)
    return ""


def _months_str(months: int) -> str:
    if months < 12:
        return f"{months} mo{'s' if months != 1 else ''}"
    yrs = months // 12
    rem = months % 12
    s = f"{yrs} yr{'s' if yrs != 1 else ''}"
    if rem:
        s += f" {rem} mo{'s' if rem != 1 else ''}"
    return s


def _duration_from_dates(start: dict | None, end: dict | None) -> str:
    if not start or not start.get("year"):
        return ""
    from datetime import datetime
    sy, sm = start.get("year", 0), start.get("month") or 1
    if end and end.get("year"):
        ey, em = end.get("year", 0), end.get("month") or 1
    else:
        now = datetime.now()
        ey, em = now.year, now.month
    months = (ey - sy) * 12 + (em - sm)
    return _months_str(months) if months > 0 else ""


def _http_url(v) -> str:
    if isinstance(v, str) and v.startswith("http"):
        return v
    if isinstance(v, dict):
        for key in ("url", "src", "href"):
            u = v.get(key)
            if isinstance(u, str) and u.startswith("http"):
                return u
    return ""


def _logo_from_website(site: str) -> str:
    site = (site or "").strip()
    if not site:
        return ""
    if not site.startswith("http"):
        site = f"https://{site}"
    host = (urlparse(site).netloc or urlparse(site).path).replace("www.", "").split("/")[0]
    return f"https://logo.clearbit.com/{host}" if host and "." in host else ""


def _company_logo(exp: dict) -> str:
    for key in ("companyLogoUrl", "company_logo_url", "companyLogo", "company_logo", "logoUrl", "logo"):
        u = _http_url(exp.get(key))
        if u:
            return u
    company = exp.get("company")
    if isinstance(company, dict):
        u = _http_url(company.get("logo") or company.get("logoUrl") or company.get("url"))
        if u:
            return u
    site = exp.get("company_website") or exp.get("companyWebsite") or ""
    if isinstance(site, str):
        return _logo_from_website(site)
    return ""


def _company_name(exp: dict) -> str:
    c = exp.get("companyName") or exp.get("company_name") or exp.get("company") or ""
    if isinstance(c, dict):
        c = c.get("name") or ""
    return str(c or "").strip()


def _job_title(exp: dict) -> str:
    return str(exp.get("title") or exp.get("job_title") or exp.get("position") or "").strip()


def _parse_date_range(raw: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", raw or "").strip()
    if not text:
        return "", ""
    parts = re.split(r"\s*[–—-]\s*", text, maxsplit=1)
    start = parts[0].strip()
    end = parts[1].strip() if len(parts) > 1 else "Present"
    return start, end or "Present"


def _entry_dates(exp: dict) -> tuple[str, str, str]:
    """Return (start, end, duration) from the many Apify date shapes."""
    still = bool(exp.get("jobStillWorking") or exp.get("job_still_working") or exp.get("current"))
    start_raw = exp.get("jobStartedOn") or exp.get("job_started_on") or ""
    end_raw = exp.get("jobEndedOn") or exp.get("job_ended_on") or ""
    if start_raw and (isinstance(start_raw, str) and re.match(r"^\d{4}-\d{2}", start_raw)):
        start_str = _fmt_yyyymm(start_raw)
        end_str = "Present" if still or not end_raw else _fmt_yyyymm(str(end_raw))
        duration = _duration_from_yyyymm(str(start_raw), None if still or not end_raw else str(end_raw))
        return start_str, end_str, duration
    if isinstance(start_raw, str) and start_raw and not isinstance(exp.get("startDate"), dict):
        # data-slayer "2-2014" or "Mar 2026"
        yyyymm = ""
        if re.match(r"^\d{1,2}-\d{4}$", start_raw):
            month, year = start_raw.split("-")
            yyyymm = f"{year}-{int(month):02d}"
            start_str = _fmt_yyyymm(yyyymm)
        else:
            start_str = start_raw
        end_yyyymm = None
        if still or not end_raw:
            end_str = "Present"
        elif re.match(r"^\d{1,2}-\d{4}$", str(end_raw)):
            month, year = str(end_raw).split("-")
            end_yyyymm = f"{year}-{int(month):02d}"
            end_str = _fmt_yyyymm(end_yyyymm)
        else:
            end_str = str(end_raw)
        duration = _duration_from_yyyymm(yyyymm, end_yyyymm) if yyyymm else ""
        return start_str, end_str, duration

    start = exp.get("startDate") or {}
    end = exp.get("endDate") or {}
    if isinstance(start, str) or isinstance(end, str):
        start_str = start if isinstance(start, str) else _fmt_date(start)
        if still:
            end_str = "Present"
        elif isinstance(end, str):
            end_str = end or "Present"
        else:
            end_str = _fmt_date(end) if (end and end.get("year")) else "Present"
        return start_str, end_str, _duration_from_dates(start if isinstance(start, dict) else None, end if isinstance(end, dict) else None)

    date = exp.get("date") or exp.get("startEndDate") or {}
    if isinstance(date, dict) and (date.get("start") or date.get("end")):
        s, e = date.get("start") or {}, date.get("end") or {}
        start_str = _fmt_date(s) if isinstance(s, dict) else str(s or "")
        end_str = "Present" if still or not (isinstance(e, dict) and e.get("year")) else _fmt_date(e)
        duration = _duration_from_dates(s if isinstance(s, dict) else None, e if isinstance(e, dict) else None)
        return start_str, end_str, duration

    range_text = exp.get("dateRange") or exp.get("date_range") or exp.get("duration") or ""
    if isinstance(range_text, str) and range_text:
        start_str, end_str = _parse_date_range(range_text)
        if still:
            end_str = "Present"
        return start_str, end_str, ""

    if isinstance(start, dict) or isinstance(end, dict):
        start_str = _fmt_date(start) if isinstance(start, dict) else ""
        end_str = "Present" if still or not (isinstance(end, dict) and end.get("year")) else _fmt_date(end)
        duration = _duration_from_dates(start if isinstance(start, dict) else None, end if isinstance(end, dict) else None)
        return start_str, end_str, duration
    return "", "Present" if still else "", ""


def _job_from_exp(exp: dict, company_fallback: str = "", logo_fallback: str = "") -> dict | None:
    if not isinstance(exp, dict):
        return None
    title = _job_title(exp)
    company = _company_name(exp) or company_fallback
    if not title and not company:
        return None
    start_str, end_str, duration = _entry_dates(exp)
    duration_months = exp.get("durationMonths")
    if duration_months and isinstance(duration_months, int) and duration_months > 0:
        duration = _months_str(duration_months)
    location = exp.get("location") or exp.get("jobLocation") or exp.get("job_location") or exp.get("geoLocationName") or ""
    if isinstance(location, dict):
        location = location.get("default") or location.get("name") or ""
    return {
        "title": title,
        "company": company,
        "company_logo": _company_logo(exp) or logo_fallback,
        "employment_type": exp.get("employmentType") or exp.get("employment_type") or "",
        "start_date": start_str,
        "end_date": end_str or "Present",
        "duration": duration,
        "location": str(location or ""),
        "description": str(exp.get("jobDescription") or exp.get("job_description") or exp.get("description") or ""),
        "company_industry": str(exp.get("company_industry") or exp.get("companyIndustry") or ""),
    }


def _extract_experience_any(record: dict) -> list[dict]:
    """Normalize work history from data-slayer, dev_fusion, atomus, bebity."""
    if not isinstance(record, dict):
        return []
    nested = record.get("profile")
    if isinstance(nested, dict) and (nested.get("position_groups") or nested.get("experience")):
        inner = _extract_experience_any(nested)
        if inner:
            return inner

    groups = record.get("position_groups")
    if isinstance(groups, list) and groups:
        atomus = _extract_experience_atomus(record)
        if atomus:
            return atomus

    rows = record.get("experiences") or record.get("experience") or record.get("positions") or []
    out: list[dict] = []
    seen: set[str] = set()
    for exp in rows:
        job = _job_from_exp(exp)
        if not job:
            continue
        key = f"{job['title']}|{job['company']}|{job['start_date']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(job)
    # data-slayer current role lives on the profile root when experience[] is thin
    top_title = str(record.get("job_title") or "").strip()
    top_company = str(record.get("current_company_name") or "").strip()
    if top_title or top_company:
        key = f"{top_title}|{top_company}|"
        if not any(j["title"] == top_title and j["company"] == top_company for j in out):
            loc = record.get("location") or ""
            out.insert(0, {
                "title": top_title,
                "company": top_company,
                "company_logo": _logo_from_website(str(record.get("company_website") or "")),
                "employment_type": "",
                "start_date": "",
                "end_date": "Present",
                "duration": "",
                "location": loc if isinstance(loc, str) else "",
                "description": "",
                "company_industry": str(record.get("company_industry") or ""),
            })
    return out


def _is_current_job(job: dict) -> bool:
    end = (job.get("end_date") or "").strip().lower()
    return end in ("", "present", "now", "current")


def _sort_jobs(jobs: list[dict]) -> list[dict]:
    current = [j for j in jobs if _is_current_job(j)]
    past = [j for j in jobs if not _is_current_job(j)]
    return current + past


def _attach_work_exp(linkedin_stats: dict | None, record: dict) -> dict | None:
    work_exp = _sort_jobs(_extract_experience_any(record))
    if not work_exp:
        return linkedin_stats
    if linkedin_stats is None:
        linkedin_stats = {}
    linkedin_stats["work_experience_raw"] = work_exp
    return linkedin_stats


def _extract_experience_dev_fusion(record: dict) -> list[dict]:
    """Extract structured work experience from dev_fusion actor response.

    dev_fusion returns a flat record with an experiences[] array. Dates are
    "YYYY-MM" strings; jobStillWorking=true means end_date is "Present".
    """
    entries = []
    for exp in (record.get("experiences") or []):
        if not isinstance(exp, dict):
            continue
        title = exp.get("title") or ""
        company = exp.get("companyName") or ""
        description = exp.get("jobDescription") or ""
        location = exp.get("jobLocation") or ""
        start_raw = exp.get("jobStartedOn") or ""
        end_raw = exp.get("jobEndedOn") or ""
        still_working = bool(exp.get("jobStillWorking"))
        start_str = _fmt_yyyymm(start_raw)
        end_str = "Present" if (still_working or not end_raw) else _fmt_yyyymm(end_raw)
        duration = _duration_from_yyyymm(start_raw, end_raw if end_raw else None)
        if title or company:
            entries.append({
                "title": title,
                "company": company,
                "company_logo": "",
                "employment_type": "",
                "start_date": start_str,
                "end_date": end_str,
                "duration": duration,
                "location": location,
                "description": description,
            })
    return entries


def _extract_experience_atomus(profile: dict) -> list[dict]:
    """Extract structured work experience from atomus nested actor response."""
    entries = []
    for group in (profile.get("position_groups") or []):
        if not isinstance(group, dict):
            continue
        company_info = group.get("company") or {}
        company_name = company_info.get("name") or ""
        company_logo = company_info.get("logo") or ""

        for pos in (group.get("profile_positions") or []):
            if not isinstance(pos, dict):
                continue
            title = pos.get("title") or ""
            employment_type = (pos.get("employment_type") or pos.get("employmentType") or "")
            location = pos.get("location") or pos.get("geoLocationName") or ""
            description = pos.get("description") or ""

            date = pos.get("date") or pos.get("startEndDate") or {}
            start = date.get("start") or {}
            end = date.get("end") or {}
            start_str = _fmt_date(start)
            end_str = _fmt_date(end) if (end and end.get("year")) else "Present"
            duration = _duration_from_dates(start, end)

            if title or company_name:
                entries.append({
                    "title": title,
                    "company": company_name,
                    "company_logo": company_logo,
                    "employment_type": employment_type,
                    "start_date": start_str,
                    "end_date": end_str,
                    "duration": duration,
                    "location": location,
                    "description": description,
                })
    return entries


def _parse_dev_fusion_profile(record: dict) -> tuple[str, dict | None]:
    """Parse dev_fusion/linkedin-profile-scraper flat response."""
    parts: list[str] = []

    full_name = (
        record.get("fullName")
        or f"{record.get('firstName', '')} {record.get('lastName', '')}".strip()
    )
    if full_name:
        parts.append(f"Name: {full_name}")
    if record.get("headline"):
        parts.append(f"Headline: {record['headline']}")

    about = record.get("summary") or record.get("about") or record.get("description") or ""
    if about:
        parts.append(f"About: {about}")

    loc = record.get("location") or record.get("jobLocation") or ""
    if isinstance(loc, dict):
        loc = loc.get("default") or loc.get("name") or ""
    if loc:
        parts.append(f"Location: {loc}")

    pic = (
        record.get("profilePicture") or record.get("pictureUrl")
        or record.get("profilePicUrl") or record.get("imgUrl") or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    skills = record.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    for exp in (record.get("experiences") or [])[:3]:
        if not isinstance(exp, dict):
            continue
        title = exp.get("title") or ""
        company = exp.get("companyName") or ""
        if title or company:
            parts.append(f"Experience: {title} at {company}".strip(" at"))

    connections_raw = (
        record.get("connections") or record.get("connectionsCount")
        or record.get("connectionCount")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None or pic:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw) if connections_raw is not None else "500+",
            "posts": 0,
        }
        if pic:
            linkedin_stats["avatar"] = pic

    linkedin_stats = _attach_work_exp(linkedin_stats, record)

    return "\n".join(parts), linkedin_stats


def _parse_bebity_profile(record: dict) -> tuple[str, dict | None]:
    """Parse flat bebity~linkedin-profile-scraper response."""
    parts: list[str] = []

    full_name = (
        record.get("fullName")
        or record.get("full_name")
        or f"{record.get('firstName', '')} {record.get('lastName', '')}".strip()
    )
    if full_name:
        parts.append(f"Name: {full_name}")
    headline = record.get("headline") or record.get("profile_headline") or record.get("job_title") or ""
    if headline:
        parts.append(f"Headline: {headline}")

    about = record.get("summary") or record.get("about") or record.get("description") or ""
    if about:
        parts.append(f"About: {about}")

    loc = record.get("location") or ""
    if isinstance(loc, dict):
        loc = loc.get("default") or loc.get("name") or ""
    if loc:
        parts.append(f"Location: {loc}")

    pic = (
        record.get("profilePicture")
        or record.get("pictureUrl")
        or record.get("profilePicUrl")
        or record.get("profile_pic_url")
        or record.get("imgUrl")
        or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    skills = record.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    experience = record.get("experience") or record.get("positions") or []
    for exp in experience[:3]:
        if not isinstance(exp, dict):
            continue
        title = exp.get("title") or exp.get("job_title") or exp.get("position") or ""
        company = exp.get("companyName") or exp.get("company_name") or exp.get("company") or ""
        if isinstance(company, dict):
            company = company.get("name") or ""
        if title or company:
            entry = f"{title} at {company}".strip(" at")
            parts.append(f"Experience: {entry}")

    connections_raw = (
        record.get("connections")
        or record.get("connectionsCount")
        or record.get("connectionCount")
        or record.get("connections_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None or pic:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw) if connections_raw is not None else "500+",
            "posts": 0,
        }
        if pic:
            linkedin_stats["avatar"] = pic

    linkedin_stats = _attach_work_exp(linkedin_stats, record)

    return "\n".join(parts), linkedin_stats


def _parse_atomus_profile(record: dict) -> tuple[str, dict | None]:
    """Parse atomus~linkedin-profile-scraper response — nested under 'profile' key.
    Does NOT check 'status' field — extracts whatever data is present."""
    profile = record.get("profile") or {}

    # If no nested profile object, the actor may have returned a flat structure
    if not profile and (record.get("headline") or record.get("fullName")):
        return _parse_bebity_profile(record)

    parts: list[str] = []
    if profile.get("full_name"):
        parts.append(f"Name: {profile['full_name']}")
    if profile.get("title"):
        parts.append(f"Title: {profile['title']}")
    if profile.get("headline"):
        parts.append(f"Headline: {profile['headline']}")
    if profile.get("summary"):
        parts.append(f"About: {profile['summary']}")

    loc = profile.get("location") or {}
    if isinstance(loc, dict) and loc.get("default"):
        parts.append(f"Location: {loc['default']}")
    elif isinstance(loc, str) and loc:
        parts.append(f"Location: {loc}")

    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")

    pic = (
        record.get("picture_url") or record.get("pictureUrl")
        or profile.get("picture_url") or profile.get("pictureUrl") or ""
    )
    if pic and pic.startswith("http"):
        parts.append(f"Avatar URL: {pic}")

    bg = (
        profile.get("background_url") or profile.get("backgroundUrl")
        or record.get("background_url") or ""
    )
    if bg and bg.startswith("http"):
        parts.append(f"Avatar BG URL: {bg}")

    skills = profile.get("skills") or []
    skill_names = [n for n in (_skill_name(s) for s in skills) if n]
    if skill_names:
        parts.append(f"Skills: {', '.join(skill_names[:30])}")

    for group in (profile.get("position_groups") or [])[:3]:
        company = (group.get("company") or {}).get("name") or ""
        for pos in (group.get("profile_positions") or [])[:1]:
            title = pos.get("title") or ""
            if title or company:
                parts.append(f"Experience: {title} at {company}".strip(" at"))

    connections_raw = (
        profile.get("connections_count") or profile.get("connectionsCount")
        or record.get("connections_count")
        or profile.get("followersCount") or profile.get("followers_count")
    )
    linkedin_stats: dict | None = None
    if connections_raw is not None or pic:
        linkedin_stats = {
            "connections": _compact_connections(connections_raw) if connections_raw is not None else "500+",
            "posts": 0,
        }
        if pic:
            linkedin_stats["avatar"] = pic

    linkedin_stats = _attach_work_exp(linkedin_stats, record)

    return "\n".join(parts), linkedin_stats


async def _run_actor(actor: str, payload: dict, timeout_secs: int = 90) -> list:
    async with httpx.AsyncClient(timeout=timeout_secs + 30) as client:
        resp = await client.post(
            f"{_APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
            params={"token": config.APIFY_API_KEY, "timeout": timeout_secs, "memory": 256},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_profile(url: str) -> tuple[str, dict | None]:
    # Primary: data-slayer (same vendor as X) — experience[] with current role + dates.
    try:
        items = await _run_actor(_ACTOR_PROFILE_PRIMARY, {"linkedin_urls": [url]}, timeout_secs=120)
        if items and isinstance(items, list):
            text, stats = _parse_bebity_profile(items[0])
            if not (stats or {}).get("work_experience_raw"):
                stats = _attach_work_exp(stats, items[0])
            if text or (stats or {}).get("work_experience_raw"):
                return text, stats
    except Exception:
        pass

    try:
        items = await _run_actor(_ACTOR_PROFILE_DEV_FUSION, {"profileUrls": [url]})
        if items and isinstance(items, list):
            text, stats = _parse_dev_fusion_profile(items[0])
            if text:
                return text, stats
    except Exception:
        pass

    try:
        items = await _run_actor(_ACTOR_PROFILE_FALLBACK, {"profileUrls": [url]})
        if items and isinstance(items, list):
            text, stats = _parse_atomus_profile(items[0])
            if text:
                return text, stats
    except Exception:
        pass

    return "", None


async def _fetch_posts(url: str) -> tuple[str, int, str | None, list[dict]]:
    """The profile's own recent posts, newest first, via the atomus posts actor.

    Only rows of type "post" whose author username matches the target handle
    are kept; reposts and quote-posts are dropped. Error rows (e.g. the
    account's free-tier event cap) are skipped so the caller can fall back
    to the Jina Activity parse.

    Returns (posts_text, own_post_count, author_avatar_or_None, structured_posts).
    """
    try:
        items = await _run_actor(
            _ACTOR_POSTS,
            {
                "profiles": [url],
                "maxPosts": _MAX_POSTS,
                "sortBy": "date",
                "includeReposts": False,
                "includeSharedPosts": False,
            },
        )
    except Exception:
        items = []
    if not isinstance(items, list):
        return "", 0, None, []

    handle = _handle_from_url(url)
    lines = ["Recent LinkedIn posts:"]
    posts: list[dict] = []
    avatar: str | None = None
    for post in items:
        if not isinstance(post, dict) or post.get("type") != "post":
            continue
        if post.get("is_repost") or post.get("reposted_by"):
            continue
        author = post.get("author") or {}
        author_username = author.get("username")
        if handle and author_username and author_username.lower() != handle.lower():
            continue
        if not avatar and author.get("avatar"):
            avatar = author["avatar"]
        content = (post.get("content") or post.get("text") or post.get("postText") or "").strip()
        if not content:
            continue
        posted = (post.get("posted_at") or "")[:10]
        post_url = post.get("post_url") or post.get("share_url") or ""
        line = f"- [{posted}] {content[:600]}" if posted else f"- {content[:600]}"
        if post_url:
            line += f" {post_url}"
        lines.append(line)
        posts.append({
            "platform": "linkedin",
            "excerpt": _strip_md(content)[:500],
            "url": post_url,
            "posted_at": posted,
        })
        if len(lines) > _MAX_POSTS + 1:
            break
    text = "\n".join(lines) if len(lines) > 1 else ""
    return text, len(posts), avatar, posts


def _parse_jina_activity(markdown: str) -> tuple[str, int, list[dict]]:
    """Extract the profile's own posts from Jina's LinkedIn Activity section.

    Public-profile Activity only contains the person's own posts. Jina renders
    each entry as a "[Name shared this](posts url)" marker line followed by the
    post text and a "[public_profile__posts]" terminator (after which reaction
    counts and images appear — skipped). Reposts are dropped.
    """
    idx = markdown.find("## Activity")
    if idx < 0:
        return "", 0, []
    section = markdown[idx + len("## Activity"):]

    lines = ["Recent LinkedIn posts:"]
    posts: list[dict] = []
    current_url: str | None = None
    current_kind: str | None = None
    current_text: list[str] = []
    in_reactions = False

    def flush() -> bool:
        if current_url is None or current_kind == "reposted":
            return False
        content = _JINA_MORE.sub("", " ".join(current_text)).strip()
        content = re.sub(r"\s+", " ", content)
        if not content:
            return False
        cleaned = _strip_md(content).lstrip("-–— ").strip()
        # Drop comment rows ("Name 7y", "Name 2d https://…") that leak between
        # posts, and short fragments with no real content.
        if re.match(r"^[A-Za-z][\w .'’-]{1,30}\s+\d{1,2}[dwmy]\b", cleaned[:40]):
            return False
        if len(cleaned) < 40:
            return False
        lines.append(f"- {content[:600]} {current_url}")
        posts.append({
            "platform": "linkedin",
            "excerpt": cleaned[:500],
            "url": current_url,
            "posted_at": "",
        })
        return len(posts) >= _MAX_POSTS

    for raw in section.split("\n"):
        line = raw.strip()
        m = _JINA_MARKER.match(line)
        if m:
            if flush():
                return "\n".join(lines), len(posts), posts
            current_url, current_kind, current_text = m.group(2), m.group(1), []
            in_reactions = False
            continue
        if current_url is None or in_reactions:
            continue
        if not line or line.startswith("[public_profile__posts]"):
            in_reactions = line.startswith("[public_profile__posts]")
            continue
        if line.startswith("[Report this post]") or line.startswith("[![") or line.startswith("### "):
            continue
        current_text.append(line)

    flush()
    return ("\n".join(lines) if posts else ""), len(posts), posts


def _parse_jina_avatar(markdown: str) -> str | None:
    """Profile display photo URL from Jina's LinkedIn markdown, if present."""
    m = re.search(
        r"!\[[^\]]*\]\(((?:https?://)?media\.licdn\.com/[^)]*profile-displayphoto[^)]*)\)",
        markdown,
    )
    if not m:
        return None
    url = m.group(1)
    return url if url.startswith("http") else f"https://{url}"


async def _fetch_posts_jina(url: str) -> tuple[str, int, str | None, list[dict]]:
    """Free fallback: parse the Activity section from Jina's render of the profile."""
    from scraping.website import _jina_fetch
    try:
        markdown = await _jina_fetch(url)
    except Exception:
        return "", 0, None, []
    text, count, posts = _parse_jina_activity(markdown)
    return text, count, _parse_jina_avatar(markdown), posts


async def _apify_fetch(url: str) -> tuple[str, dict | None]:
    profile_result, posts_result = await asyncio.gather(
        _fetch_profile(url),
        _fetch_posts(url),
        return_exceptions=True,
    )

    parts: list[str] = []
    linkedin_stats: dict | None = None
    posts_count = 0

    if isinstance(profile_result, tuple):
        profile_text, linkedin_stats = profile_result
        if profile_text:
            parts.append(profile_text)

    if isinstance(posts_result, tuple) and len(posts_result) == 4:
        posts_text, posts_count, posts_avatar, posts = posts_result
        if not posts_text:
            # Actor unavailable (billing caps, errors) — fall back to the free
            # Jina Activity parse so LinkedIn posts still flow.
            posts_text, posts_count, posts_avatar, posts = await _fetch_posts_jina(url)
        if posts_text:
            parts.append(posts_text)
        if linkedin_stats is None:
            linkedin_stats = {}
        if posts_count:
            linkedin_stats["posts"] = posts_count
        if posts:
            linkedin_stats["posts_raw"] = posts
        if posts_avatar and not linkedin_stats.get("avatar"):
            linkedin_stats["avatar"] = posts_avatar
    elif linkedin_stats is None and posts_count:
        linkedin_stats = {"connections": "500+", "posts": posts_count}

    return "\n\n".join(parts)[:_MAX_CHARS], linkedin_stats


async def fetch_linkedin_profile(url: str) -> tuple[str, dict | None]:
    """Scrape LinkedIn profile + recent posts. Returns (text, linkedin_stats)."""
    if config.APIFY_API_KEY:
        try:
            text, stats = await _apify_fetch(url)
            if text:
                return text, stats
        except Exception:
            pass
    from scraping.website import _jina_fetch
    try:
        markdown = await _jina_fetch(url)
        if len(markdown) >= 100:
            posts_text, posts_count, posts = _parse_jina_activity(markdown)
            avatar = _parse_jina_avatar(markdown)
            # Reserve room for the posts block so it isn't truncated away.
            head_limit = max(2000, _MAX_CHARS - len(posts_text) - 4) if posts_text else _MAX_CHARS
            parts = [markdown[:head_limit]]
            if posts_text:
                parts.append(posts_text)
            stats = None
            if posts_count or avatar:
                stats = {"connections": "500+", "posts": posts_count}
                if posts:
                    stats["posts_raw"] = posts
                if avatar:
                    stats["avatar"] = avatar
            return "\n\n".join(parts)[:_MAX_CHARS], stats
    except Exception:
        pass
    return "", None
