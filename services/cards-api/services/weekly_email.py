"""Weekly receipt HTML: inline styling and presentation tables for mail clients."""
import html

import config

INK = "#172033"
MUTED = "#788396"
BORDER = "#e5e9f0"
ACCENT = "#4f46e5"
DASHBOARD_URL = "https://cards.zynd.ai/home"


def visitor_profile_url(visitor: dict) -> str | None:
    handle = visitor.get("handle")
    if not isinstance(handle, str) or not handle.strip():
        return None
    return config.profile_url(handle.strip())


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def initials(name: str) -> str:
    words = [word for word in name.split() if word[0].isalnum()]
    return esc("".join(word[0] for word in words[:2]).upper() or "Z")


def table(content: str, style: str = "") -> str:
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;{style}">{content}</table>'


def section(title: str, description: str, content: str) -> str:
    return (f'<div style="margin-top:22px;border:1px solid {BORDER};border-radius:16px;padding:20px;">'
            f'<h2 style="margin:0 0 6px;font-size:16px;line-height:1.4;color:{INK};">{esc(title)}</h2>'
            f'<p style="margin:0 0 16px;font-size:12px;line-height:1.7;color:{MUTED};">{esc(description)}</p>{content}</div>')


def empty(message: str) -> str:
    return f'<p style="margin:0;padding:14px;border-radius:10px;background:#f7f8fb;font-size:12px;color:{MUTED};">{esc(message)}</p>'


def row(avatar: str, title: str, detail: str, count: str, *, color: str = ACCENT,
        wash: str = "#eef2ff", share: str = "", profile_url: str | None = None) -> str:
    title_html = esc(title)
    detail_html = esc(detail)
    if profile_url:
        title_html = f'<a href="{esc(profile_url)}" style="color:{INK};text-decoration:none;">{title_html}</a>'
        detail_html += f' &middot; <a href="{esc(profile_url)}" style="color:{ACCENT};text-decoration:none;">View profile &rarr;</a>'
    return table(
        '<tr><td width="42" valign="middle">'
        f'<div style="width:32px;height:32px;line-height:32px;text-align:center;border-radius:10px;background:{wash};color:{color};font-size:11px;font-weight:700;">{avatar}</div></td>'
        f'<td valign="middle" style="word-break:break-word;padding-right:8px;"><p style="margin:0 0 3px;font-size:13px;font-weight:600;color:{INK};">{title_html}</p>'
        f'<p style="margin:0;font-size:11px;line-height:1.5;color:{MUTED};">{detail_html}</p></td>'
        f'<td width="92" align="right" valign="middle"><span style="font-size:12px;font-weight:600;white-space:nowrap;color:{INK};">{esc(count)}</span>'
        + (f'<p style="margin:4px 0 0;font-size:10px;color:{MUTED};">{esc(share)}</p>' if share else '') + '</td></tr>',
        f'background:#f8f9fc;border:1px solid #edf0f5;border-radius:11px;padding:12px;margin-top:8px;')


def provider_color(provider: str) -> tuple[str, str]:
    if "OpenAI" in provider:
        return "#238472", "#e8f7f1"
    return {"Claude": ("#bb704c", "#fff0e7"), "Perplexity": ("#218799", "#e7f7fa"),
            "Amazon": ("#b27a21", "#fff6df"), "Google": ("#467cc8", "#edf4ff")}.get(provider, ("#75839a", "#edf0f5"))


def render_matches(matches: list[dict]) -> str:
    if not matches:
        return ""
    cards = []
    for person in matches[:3]:
        name = person.get("name") or person.get("handle") or "Zynd member"
        profile = visitor_profile_url(person)
        title = esc(name)
        if profile:
            title = f'<a href="{esc(profile)}" style="color:{INK};text-decoration:none;">{title}</a>'
        detail = " · ".join(v for v in (person.get("headline"), person.get("location")) if v)
        reasons = ''.join(f'<li style="margin:4px 0;">{esc(reason)}</li>' for reason in (person.get("why") or [])[:2])
        identity = table(
            f'<tr><td width="48" valign="top"><div style="width:36px;height:36px;line-height:36px;text-align:center;background:#ede9fe;color:{ACCENT};border-radius:11px;font-size:12px;font-weight:700;">{initials(name)}</div></td>'
            f'<td valign="top" style="overflow-wrap:anywhere;word-break:break-word;"><h3 style="margin:0;font-size:15px;line-height:1.5;color:{INK};">{title}</h3>'
            + (f'<p style="margin:3px 0 0;font-size:11px;line-height:1.6;color:{MUTED};">{esc(detail)}</p>' if detail else '') + '</td></tr>')
        why = (f'<p style="margin:14px 0 5px;font-size:9px;font-weight:700;letter-spacing:1px;color:{ACCENT};">WHY CONNECT</p>'
               f'<ul style="margin:0;padding-left:17px;font-size:12px;line-height:1.7;color:#46516a;">{reasons}</ul>') if reasons else ''
        view = f'<p style="margin:12px 0 0;"><a href="{esc(profile)}" style="font-size:11px;font-weight:600;color:{ACCENT};text-decoration:none;">View profile &rarr;</a></p>' if profile else ''
        cards.append(table(f'<tr><td style="padding:16px;">{identity}{why}{view}</td></tr>',
                           f'margin-top:10px;background:white;border:1px solid #e6e1fb;border-radius:12px;'))
    content = (f'<p style="margin:0 0 8px;font-size:9px;letter-spacing:1.5px;font-weight:700;color:{ACCENT};">GOOD PEOPLE. A REASON TO CONNECT.</p>'
               f'<h2 style="margin:0 0 6px;font-size:23px;letter-spacing:-.6px;line-height:1.3;color:{INK};">Zynd matches</h2>'
               '<p style="margin:0 0 16px;font-size:12px;line-height:1.8;color:#65708a;">People who fit what you’re looking for. Let DearAgent help you make the first move.</p>'
               + ''.join(cards)
               + f'<p style="margin:20px 0 0;"><a href="{DASHBOARD_URL}#zynd-matches" style="display:inline-block;padding:13px 18px;background:{ACCENT};border-radius:9px;color:white;text-decoration:none;font-size:12px;font-weight:700;line-height:1.5;">Review matches and draft an intro &rarr;</a></p>'
               '<p style="margin:12px 0 0;font-size:11px;line-height:1.7;color:#65708a;">You approve the request; they decide whether to connect.</p>')
    return table(f'<tr><td class="match-content" style="padding:22px;">{content}</td></tr>',
                 'margin-top:24px;margin-bottom:24px;background:#f5f3ff;border:1px solid #ddd6fe;border-radius:16px;')


def render_weekly_html(data: dict, insights: dict, agent_fallback: list[str], visitor_fallback: list[str],
                       unsubscribe_url: str | None, preview_label: str, network_html: str) -> str:
    base = config.SITE_BASE_URL.rstrip("/")
    home = DASHBOARD_URL
    profile = config.profile_url(data["handle"])
    inbox = profile + "/edit#inbox"
    name = data.get("name") or data["handle"]
    metrics = data["activity"]
    matches = (data.get("suggestions") or {}).get("people") or []
    matches_html = render_matches(matches)
    available = metrics.get("available", False)
    score = max(0, min(100, int(data["completeness"]["score"])))
    status = "Public profile" if data.get("visibility") == "public" else "Your profile"
    pending = data.get("inbox_count")
    preheader = f"Your weekly profile activity, {name}. See people, AI clients, and recent assistant questions."
    if matches:
        preheader = f"Your Zynd matches are here, {name}. Review people to meet and draft an introduction."

    header = table(
        '<tr><td width="42"><div style="width:32px;height:32px;line-height:32px;text-align:center;border-radius:9px;background:#4f46e5;color:white;font-weight:700;font-size:20px;">Z</div></td>'
        f'<td><strong style="font-size:19px;letter-spacing:-.7px;">zynd</strong><br><span style="font-size:9px;letter-spacing:1.4px;color:{MUTED};">YOUR WEEKLY RECAP</span></td>'
        f'<td align="right"><span style="display:inline-block;background:#edf8f1;color:#34815e;border:1px solid #d8ede1;padding:5px 9px;border-radius:20px;font-size:10px;">{status}</span></td></tr>')
    greeting = table(
        f'<tr><td width="58" valign="middle"><div style="width:44px;height:44px;line-height:44px;text-align:center;border-radius:13px;background:#eef2ff;color:{ACCENT};font-size:15px;font-weight:700;">{initials(name)}</div></td>'
        f'<td><h1 style="font-size:24px;line-height:1.3;letter-spacing:-.7px;margin:0 0 6px;color:{INK};">Your week on Zynd</h1>'
        f'<p style="margin:0;font-size:12px;color:{MUTED};">{esc(name)} &middot; Last 7 days</p>'
        f'<a href="{esc(profile)}" style="display:inline-block;margin-top:5px;font-size:11px;color:{ACCENT};text-decoration:none;">@{esc(data["handle"])}</a></td></tr>')

    cells = []
    for title, value, detail in [
        ("Human audience", metrics.get("views") if available else None, "Recorded browser visits"),
        ("AI requests", metrics.get("agent_hits") if available else None, "AI clients and crawlers"),
        ("Profile completeness", f"{score}%", "Make your profile easier to discover"),
    ]:
        shown = "—" if value is None else f"{value:,}" if isinstance(value, int) else str(value)
        progress = (f'<div style="height:4px;background:#e5e9f1;border-radius:4px;margin-top:10px;">'
                    f'<div style="height:4px;width:{score}%;background:#14a38b;border-radius:4px;"></div></div>') if title == "Profile completeness" else ""
        cells.append(f'<td class="metric" width="33.33%" valign="top" style="padding:5px;">'
                     f'<div style="padding:15px 12px;background:#f8f9fc;border:1px solid {BORDER};border-radius:12px;">'
                     f'<p style="margin:0 0 8px;font-size:10px;color:{MUTED};">{title}</p>'
                     f'<strong style="font-size:28px;line-height:1.2;letter-spacing:-1px;color:{INK};">{esc(shown)}</strong>'
                     f'{progress}<p style="margin:9px 0 0;font-size:10px;line-height:1.6;color:{MUTED};">{detail}</p></div></td>')
    stats = table('<tr>' + ''.join(cells) + '</tr>', 'margin:20px -5px 0;width:calc(100% + 10px);')

    visitor_data = data.get("visitors") or {}
    people = [v for v in (visitor_data.get("items") or []) if (v.get("name") or "").strip()][:10] if visitor_data.get("available") else []
    people_html = "".join(row(initials(v["name"]), v["name"], "Chose to share their name",
                            f'{v["visits"]} {"visit" if v["visits"] == 1 else "visits"}' if isinstance(v.get("visits"), int) else "Visitor",
                            profile_url=visitor_profile_url(v)) for v in people)
    people_html = section("People who viewed your profile", "Last 7 days · Names appear only for visitors who chose to share them; anonymous visits remain private.",
                          people_html or empty(visitor_fallback[0]))

    clients = metrics.get("agent_clients") or []
    total = sum(a["count"] for a in clients)
    composition = ""
    if total:
        segments = ''.join(f'<td width="{a["count"] / total * 100:.3f}%" height="7" bgcolor="{provider_color(a["provider"])[0]}" style="height:7px;background:{provider_color(a["provider"])[0]};font-size:0;line-height:0;">&nbsp;</td>'
                           for a in clients if a["count"] > 0)
        composition = (f'<p style="margin:0 0 8px;font-size:10px;color:{MUTED};">{total:,} requests in this breakdown</p>'
                       + table('<tr>' + segments + '</tr>', 'border-radius:4px;overflow:hidden;margin-bottom:16px;'))
    client_rows = []
    for client in clients:
        provider, client_name, count = client["provider"], client["name"], client["count"]
        color, wash = provider_color(provider)
        mark = "AI" if "OpenAI" in provider else "CL" if provider == "Claude" else "?" if provider == "Unknown" else initials(provider)
        client_rows.append(row(mark, provider, client_name, f'{count:,} {"request" if count == 1 else "requests"}',
                               color=color, wash=wash, share=f'{count / total * 100:.1f}% of listed requests' if total else ""))
    agents_html = section("AI clients that accessed your profile", "Last 7 days · Reported client identities, not verified model names. Breakdown covers the latest 1,000 AI requests.",
                          composition + (''.join(client_rows) or empty(agent_fallback[0])))

    topics_html = ""
    if insights["topics"]:
        chips = ''.join(f'<span style="display:inline-block;margin:4px 6px 4px 0;padding:5px 10px;background:#eef2ff;border:1px solid #e0e7ff;border-radius:20px;color:{ACCENT};font-size:12px;">{esc(topic)}</span>' for topic in insights["topics"])
        topics_html = section("Topics asked about in your profile assistant", "Based on recorded assistant questions this week.", chips)
    questions_html = ''.join(f'<li style="padding:12px 0;border-bottom:1px solid #edf0f5;font-size:13px;line-height:1.7;color:{INK};">{esc(question)}</li>' for question in insights["questions"])
    questions_html = section("Recent profile-assistant questions", "The latest questions from the last 7 days, with contact details redacted.",
                             ('<ol style="margin:0;padding-left:20px;">' + questions_html + '</ol>' if questions_html else empty("No profile-assistant questions recorded this week."))
                             + f'<p style="margin:15px 0 0;font-size:11px;line-height:1.7;color:{MUTED};">AI requests and assistant questions are separate measurements; crawler requests may not include a question.</p>')

    notices = ""
    if not available:
        notices += '<p style="padding:12px 14px;background:#fffaeb;border:1px solid #f3e6bf;border-radius:10px;font-size:12px;color:#8a6824;">Activity measurement is unavailable this week.</p>'
    if pending is None:
        notices += '<p style="padding:12px 14px;background:#fffaeb;border:1px solid #f3e6bf;border-radius:10px;font-size:12px;color:#8a6824;">Review queue is temporarily unavailable.</p>'
    elif pending:
        notices += f'<p style="padding:12px 14px;background:#f3f1ff;border-radius:10px;font-size:12px;color:{ACCENT};">{esc(pending)} facts waiting for review. <a href="{esc(inbox)}" style="color:{ACCENT};">Review your inbox</a></p>'
    extras = network_html
    if data.get("intro_inbox_count") is not None:
        extras += f'<p style="font-size:12px;color:{MUTED};">{esc(data["intro_inbox_count"])} intro requests waiting. <a href="{esc(base + "/intros")}" style="color:{ACCENT};">Review introductions</a></p>'
    cta = (f'<div style="text-align:center;margin-top:26px;"><a href="{esc(home)}" style="display:inline-block;padding:13px 24px;border-radius:10px;background:{ACCENT};color:#ffffff;font-size:13px;font-weight:600;text-decoration:none;">Open your analytics dashboard &rarr;</a>'
           f'<p style="margin:10px 0 0;font-size:11px;color:{MUTED};">See your activity and manage your profile.</p></div>')
    footer = (f'<strong style="color:#46516a;font-size:12px;">Zynd · Your profile, discovered</strong>'
              f'<p style="margin:10px 0;font-size:11px;line-height:1.7;color:{MUTED};">You receive this email because weekly digests are enabled for your Zynd profile.</p>'
              f'<a href="{esc(home)}" style="color:#69748a;font-size:11px;">Manage preferences</a>') if unsubscribe_url else f'<p style="font-size:11px;line-height:1.7;color:{MUTED};">{esc(preview_label)}</p>'
    if unsubscribe_url:
        footer += f' &nbsp;·&nbsp; <a href="{esc(unsubscribe_url)}" style="color:#69748a;font-size:11px;">Unsubscribe</a>'
    card = table(
        f'<tr><td style="padding:24px 28px;border-bottom:1px solid #edf0f5;">{header}</td></tr>'
        f'<tr><td class="content" style="padding:26px 28px;">{greeting}{matches_html}{notices}{stats}{people_html}{agents_html}{topics_html}{questions_html}{extras}{cta}</td></tr>'
        f'<tr><td style="padding:22px 28px;background:#f8f9fc;border-top:1px solid #edf0f5;">{footer}</td></tr>',
        'max-width:800px;margin:auto;background:white;border:1px solid #e1e6ef;border-radius:18px;overflow:hidden;')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Your week on Zynd</title><style>@media only screen and (max-width:520px){.content{padding:20px 16px!important}.match-content{padding:18px 14px!important}.metric{display:block!important;width:auto!important}}</style></head>'
            f'<body style="margin:0;background:#f4f5f8;color:{INK};font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">'
            f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">{esc(preheader)}</div>'
            + table(f'<tr><td align="center" style="padding:28px 12px;">{card}</td></tr>', 'background:#f4f5f8;')
            + '</body></html>')
