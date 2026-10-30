"""Email a card owner right after an AI agent reads their card.

Owners otherwise only learn about AI reads by opening /home. The trigger is a stored `view` or
`agent_fetch` card_event that
  - was reported by one of our servers (cards-web page and data.json reads, memory's MCP reads)
    with EVENTS_SERVER_TOKEN (services/events.py _insert_rows). A plain POST /events and the
    reads cards-api records itself (emit) never trigger: their actor_class comes from the
    caller's User-Agent, which anyone can set;
  - names an agent from ALERT_AGENTS, the clients that fetch a card because a person asked them
    something just now. Training and index crawlers (GPTBot, ClaudeBot, CCBot, OAI-SearchBot,
    PerplexityBot, ...) still count as AI reads on /home, but never email anyone; neither do
    search bots or unidentified clients;
  - came from an IP inside that agent's provider's published ranges (services/agent_ip_ranges.py).
    Our servers relay the visitor's User-Agent and MCP client name as given, so the token alone
    proves only that cards-web or memory saw the read, not who made it. The visitor IP travels in
    X-Zynd-Client-IP next to the token (api/events.py);
for a published, claimed card whose owner has not turned the morning digest off. Without
EVENTS_SERVER_TOKEN nothing is attested, so nothing is ever sent; without S10_MAILER=smtp the
mailer is a no-op.

Throttle: at most one email per card per COOLDOWN_HOURS. The last send is a
server-only `ai_read_alert_sent` row in card_events, so the limit needs no migration and holds
across restarts and workers. Two workers checking the same card in the same instant can both
send; an in-process guard keeps one worker to one check per card at a time.

Everything here runs on a small background pool, never on the request that stored the event,
and never raises into it. Logs carry the handle only: no recipient address and no email content
(services/mailer.py).
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import config
from services import agent_ip_ranges, digest, events, ua_class
from services.mailer import get_mailer

logger = logging.getLogger(__name__)

TRIGGER_EVENTS = frozenset({"view", "agent_fetch"})
_TRIGGER_ACTOR = "ai_agent"

# User-initiated fetchers only (ua_class tokens). A crawl reads every card in one pass, so a
# crawler here would mail every owner whenever it ran. OAI-SearchBot and PerplexityBot are left
# out: both build their provider's search index ahead of time rather than fetching for one
# question (OpenAI's per-question fetcher is ChatGPT-User). Only agents whose provider publishes
# egress ranges can be verified, so Codex (runs on the user's machine) and Zynd-MCP (an anonymous
# MCP client) are counted on /home but never email.
ALERT_AGENTS = frozenset(agent_ip_ranges.AGENT_RANGE_URLS)

# One email per card per day: a card an assistant keeps citing would otherwise mail its owner
# on every question.
COOLDOWN_HOURS = 24

# After a check that did not send (unclaimed card, opted out, already alerted, no mailer),
# skip that card's DB lookups for this long. Crawlers hit the same card in bursts, and an
# owner who claims a card or turns email back on waits at most this long for the next alert.
_RECHECK_SECONDS = 15 * 60
_MAX_TRACKED_HANDLES = 10_000
_WORKERS = 2

_lock = threading.Lock()
_inflight: set[str] = set()
_quiet_until: dict[str, float] = {}
_pool: ThreadPoolExecutor | None = None


def schedule(rows: list[dict], visitor_ip: str | None) -> None:
    """Queue an alert check for each card an AI agent just read. Called after server-observed
    rows are stored (never for a plain POST /events), with the visitor IP our server attested;
    never raises, never waits on the database, the provider lists or the mailer."""
    if not events.events_enabled() or agent_ip_ranges.parse_ip(visitor_ip) is None:
        return
    try:
        read_at = datetime.now(timezone.utc)
        for handle, agent in _ai_reads(rows).items():
            if _reserve(handle):
                _submit(_run, handle, agent, read_at, visitor_ip)
    except Exception:
        logger.exception("ai read alert scheduling failed")


def _ai_reads(rows: list[dict]) -> dict[str, str]:
    """handle -> advertised agent token, one entry per card."""
    reads: dict[str, str] = {}
    for row in rows:
        handle = row.get("handle")
        if row.get("event") not in TRIGGER_EVENTS or row.get("actor_class") != _TRIGGER_ACTOR or not handle:
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        name = meta.get("agent_name")
        if name in ALERT_AGENTS:
            reads.setdefault(handle, name)
    return reads


def _reserve(handle: str) -> bool:
    now = time.monotonic()
    with _lock:
        if handle in _inflight or _quiet_until.get(handle, 0.0) > now:
            return False
        if len(_quiet_until) > _MAX_TRACKED_HANDLES:
            _quiet_until.clear()
        _inflight.add(handle)
        return True


def _release(handle: str, quiet_seconds: float) -> None:
    with _lock:
        _inflight.discard(handle)
        if quiet_seconds > 0:
            _quiet_until[handle] = time.monotonic() + quiet_seconds


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="ai-read-alert")
        return _pool


def _submit(fn, *args) -> None:
    _executor().submit(fn, *args)


def _run(handle: str, agent: str | None, read_at: datetime, visitor_ip: str | None) -> None:
    quiet = 0.0
    try:
        if not agent_ip_ranges.is_provider_ip(agent, visitor_ip):
            # No quiet period: a spoofed read must not hold off the alert for the next real one.
            logger.info("ai read alert skipped handle=%s agent=%s: not from the provider's ranges", handle, agent)
            return
        outcome = deliver(handle, agent, read_at)
        quiet = cooldown().total_seconds() if outcome in ("sent", "send_failed") else _RECHECK_SECONDS
    except Exception:
        # Retry on the next AI read rather than going quiet: this is a DB or render failure,
        # not an answer about the owner.
        logger.exception("ai read alert failed handle=%s", handle)
    finally:
        _release(handle, quiet)


def cooldown() -> timedelta:
    return timedelta(hours=COOLDOWN_HOURS)


def deliver(handle: str, agent: str | None, read_at: datetime | None = None) -> str:
    """Send the alert for one AI read when it is due. Returns what happened:
    sent | send_failed | no_mailer | ineligible | opted_out | throttled | claim_failed."""
    read_at = read_at or datetime.now(timezone.utc)
    mailer = get_mailer()
    if not mailer.enabled:
        return "no_mailer"
    row = _owner_row(handle)
    # Claimed means an owner email is set (services/cards.py _claimed_from_row).
    email = ((row or {}).get("owner_email") or "").strip()
    if row is None or not email:
        return "ineligible"
    token = row.get("unsubscribe_token")
    if _opted_out(row) or not token:
        # No token means no working unsubscribe link, and this email always carries one.
        return "opted_out"
    if _alerted_since(row["handle"], read_at - cooldown()):
        return "throttled"
    # Claim the window before sending, like the digest: if the marker were written after SMTP
    # and that write failed, every following AI read would email the owner again.
    if not _record_sent(row["handle"], agent, read_at):
        return "claim_failed"
    unsubscribe_url = f"{config.API_BASE_URL.rstrip('/')}/cards/notifications/unsubscribe/{token}"
    subject, body, html = render(row, agent, read_at, unsubscribe_url)
    try:
        mailer.send(to=email, subject=subject, body=body, html=html, unsubscribe_url=unsubscribe_url)
    except Exception as exc:
        # Type only: SMTP errors can carry the recipient address.
        logger.warning("ai read alert send failed handle=%s err=%s", row["handle"], type(exc).__name__)
        return "send_failed"
    logger.info("ai read alert sent handle=%s", row["handle"])
    return "sent"


def _owner_row(handle: str) -> dict | None:
    rows = (config.get_supabase().table("agent_profile_cards")
            .select("handle,owner_email,notification_prefs,unsubscribe_token,card")
            .eq("handle", handle).eq("status", "published").limit(1).execute().data or [])
    return rows[0] if rows else None


def _opted_out(row: dict) -> bool:
    """The morning digest's rule (services/digest.py run_digest). The digest's unsubscribe
    link turns morning_digest off, so that link stops these emails too."""
    prefs = row.get("notification_prefs") if isinstance(row.get("notification_prefs"), dict) else {}
    return prefs.get("morning_digest") is False


def _alerted_since(handle: str, since: datetime) -> bool:
    rows = (config.get_supabase().table("card_events").select("id")
            .eq("event", events.AI_READ_ALERT_EVENT).eq("handle", handle)
            .gte("ts", since.isoformat()).limit(1).execute().data or [])
    return bool(rows)


def _record_sent(handle: str, agent: str | None, read_at: datetime) -> bool:
    row = events._build_row(event=events.AI_READ_ALERT_EVENT, handle=handle, actor_class="unknown",
                            ref=None, session_hash=None, meta={"agent_name": agent} if agent else None)
    # Explicit ts so the cooldown is measured on the same clock that checks it.
    row["ts"] = read_at.isoformat()
    return events._insert_rows([row])


def client_label(agent: str | None) -> str:
    """Provider name for the advertised agent, e.g. "Claude"; generic when there is none."""
    provider = ua_class.AGENT_PROVIDERS.get(agent or "")
    # "Unidentified MCP client" is a fact for the body, not a name to put in a subject line.
    if not provider or provider.startswith("Unidentified"):
        return "An AI agent"
    return provider


def _source(agent: str | None) -> str:
    """Why the client name is believable: _run only delivers once the visitor IP is inside the
    publisher's list. The fallback covers direct deliver() calls for agents with no list."""
    publisher = agent_ip_ranges.range_publisher(agent)
    return f"from {publisher}'s published IP range" if publisher else "as reported by the client"


def _when(read_at: datetime) -> str:
    at = read_at.astimezone(timezone.utc)
    return f"{at.day} {at:%b %Y, %H:%M} UTC"


def _cadence() -> str:
    hours = COOLDOWN_HOURS
    return "a day" if hours == 24 else f"every {hours} {'hour' if hours == 1 else 'hours'}"


# The IP check proves which provider's network fetched the card, nothing more: not which person,
# if any, asked the agent to, and not what the agent did with it.
NOTE = "This shows that an AI agent read your card, not who (if anyone) asked it to or why."


def render(row: dict, agent: str | None, read_at: datetime, unsubscribe_url: str) -> tuple[str, str, str]:
    """(subject, plain text, html)."""
    handle = row["handle"]
    label = client_label(agent)
    client = ua_class.AGENT_PROVIDERS.get(agent or "", "Unknown AI client")
    if agent:
        client += f" ({agent})"
    source = _source(agent)
    first = digest._first_name(digest._identity_name(row.get("card")), handle)
    card_url = digest._card_url(handle)
    home_url = f"{digest._base()}/home"
    when = _when(read_at)
    subject = f"{label} just read your Zynd card"
    body = "\n".join([
        f"Hi {first},",
        "",
        f"{label} just read your Zynd card.",
        "",
        f"Client: {client}, {source}",
        f"When: {when}",
        f"Your card: {card_url}",
        "",
        f"See your AI reads: {home_url}",
        "",
        NOTE,
        f"You get at most one of these {_cadence()} for each card.",
        "",
        f"Unsubscribe: {unsubscribe_url}",
    ])
    return subject, body, _html(first, label, client, source, when, card_url, home_url, unsubscribe_url)


def _detail(i: int, name: str, value_html: str) -> str:
    top = f"border-top:1px solid {digest._LINE};" if i else ""
    return (f'<tr><td width="96" valign="top" style="{top}padding:12px 16px;font:400 13px/20px {digest._FONT};'
            f'color:{digest._MUTED}">{digest._esc(name)}</td>'
            f'<td valign="top" style="{top}padding:12px 16px 12px 0;font:400 13px/20px {digest._FONT};'
            f'color:{digest._INK}">{value_html}</td></tr>')


def _html(first: str, label: str, client: str, source: str, when: str, card_url: str, home_url: str,
          unsubscribe_url: str) -> str:
    d, esc = digest, digest._esc
    base = d._base()
    card_text = card_url.split("://", 1)[-1]
    header = d._table(
        f'<tr><td width="28" valign="middle"><img src="{esc(base)}/assets/zynd-logo.png" width="28" height="28" alt="Zynd" '
        f'style="display:block;width:28px;height:28px;border:0"></td>'
        f'<td valign="middle" style="padding-left:8px;font:700 16px/20px {d._WORDMARK_FONT};letter-spacing:.02em;'
        f'text-transform:uppercase;color:{d._INK}">Zynd<span style="color:{d._WORDMARK_ACCENT}">Cards</span></td></tr>')
    details = d._box(
        _detail(0, "Client", f'{esc(client)}<div style="color:{d._MUTED}">{esc(source)}</div>')
        + _detail(1, "When", esc(when))
        + _detail(2, "Your card", f'<a href="{esc(card_url)}" style="color:{d._ACCENT};text-decoration:none">{esc(card_text)}</a>'))
    cta = d._table(
        f'<tr><td style="padding-top:24px"><a href="{esc(home_url)}" style="display:block;padding:0 16px;border-radius:8px;'
        f'background:{d._ACCENT};color:{d._WHITE};text-decoration:none;text-align:center;font:600 14px/44px {d._FONT}">'
        f"See your AI reads</a></td></tr>")
    main = d._table(
        f'<tr><td class="i" style="padding:24px">{header}'
        f'<div style="font:600 20px/28px {d._FONT};color:{d._INK};padding-top:24px">{esc(label)} just read your Zynd card</div>'
        f'<div style="font:400 14px/22px {d._FONT};color:{d._BODY};padding:4px 0 16px">Hi {esc(first)}, an AI agent '
        f"just read your card.</div>"
        f"{details}{cta}"
        f'<div style="font:400 12px/18px {d._FONT};color:{d._MUTED};padding-top:16px">'
        f"{esc(NOTE)}</div></td></tr>",
        f"max-width:600px;background:{d._WHITE};border-radius:12px", cls="s")
    footer = d._table(
        f'<tr><td align="center" style="padding:16px 8px 0;font:400 12px/18px {d._FONT};color:{d._MUTED}">'
        f'You get this because you own <a href="{esc(card_url)}" style="color:{d._MUTED}">{esc(card_text)}</a>, '
        f"at most once {esc(_cadence())}.<br>"
        f'<a href="{esc(base)}/home" style="color:{d._MUTED}">Email settings</a> &nbsp;&middot;&nbsp; '
        f'<a href="{esc(unsubscribe_url)}" style="color:{d._MUTED}">Unsubscribe</a></td></tr>',
        "max-width:600px")
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<style>{d._MOBILE_CSS}</style></head>"
        f'<body style="margin:0;padding:0;background:{d._BG}">'
        + d._table(f'<tr><td class="o" align="center" style="padding:24px 16px">{main}{footer}</td></tr>', f"background:{d._BG}")
        + "</body></html>"
    )
