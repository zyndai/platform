"""Professional tenure from the union of supported work-history date ranges."""
from datetime import date, datetime
import re


def _month(value: object, today: date) -> int | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.casefold() in {"present", "current", "now"}:
        return today.year * 12 + today.month - 1
    for fmt in ("%b %Y", "%B %Y", "%Y-%m-%d", "%Y-%m", "%Y", "%m/%Y", "%m-%Y"):
        try:
            stamp = datetime.strptime(raw, fmt)
            return stamp.year * 12 + stamp.month - 1
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", raw):
        return _month(raw[:10], today)
    return None


def experience_years(jobs: list[dict] | None, today: date | None = None) -> int | None:
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    spans = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        start, end = _month(job.get("start_date"), today), _month(job.get("end_date"), today)
        # A missing end is ambiguous; never assume a historic role is current.
        if start is not None and end is not None and start <= end and start <= now:
            spans.append((start, min(end, now)))
    if not spans:
        return None
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged) // 12
