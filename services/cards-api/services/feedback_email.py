"""Feedback invitation markup, with inline styles and no browser-only assets."""
import config
from services.weekly_email import ACCENT, BORDER, DASHBOARD_URL, INK, MUTED, esc, table


def render_feedback_html(name: str, paragraphs: list[str], calendar_url: str, form_url: str,
                         unsubscribe_url: str | None, *, handle: str | None = None,
                         preview_label: str | None = None) -> str:
    header = table(
        '<tr><td width="44"><div style="width:34px;height:34px;line-height:34px;text-align:center;border-radius:10px;background:#4f46e5;color:#ffffff;font-size:20px;font-weight:700;">Z</div></td>'
        f'<td><strong style="font-size:19px;letter-spacing:-.7px;">zynd</strong><br><span style="font-size:9px;letter-spacing:1.3px;color:{MUTED};">A NOTE FROM THE TEAM</span></td>'
        '<td align="right"><span style="display:inline-block;border:1px solid #d9ece0;border-radius:20px;background:#edf8f1;padding:5px 8px;font-size:10px;color:#347653;white-space:nowrap;">Team check-in</span></td></tr>')

    account = esc(name.strip() or "Your Zynd profile")
    if handle:
        profile = config.profile_url(handle)
        account += f' &middot; <a href="{esc(profile)}" style="color:{ACCENT};text-decoration:none;">@{esc(handle)}</a>'
    greeting = (f'<p style="display:inline-block;max-width:100%;box-sizing:border-box;margin:0 0 18px;padding:6px 9px;background:#f1f3f7;border-radius:6px;color:#687489;font-size:11px;line-height:1.6;word-break:break-word;">{account}</p>'
                f'<h1 style="margin:0 0 16px;font-size:26px;line-height:1.3;letter-spacing:-.6px;color:{INK};">{esc(paragraphs[0])}</h1>'
                + ''.join(f'<p style="margin:0 0 16px;font-size:15px;line-height:1.8;color:#536078;">{esc(p)}</p>' for p in paragraphs[1:3]))

    notice = ('<div style="margin:22px 0;padding:14px 16px;background:#fffaed;border:1px solid #f2e5c3;border-radius:11px;color:#89652d;font-size:12px;line-height:1.7;">'
              '<strong>Your feedback matters.</strong> Tell us what’s working, what’s missing, and what would make your profile more useful.</div>')
    booking_header = table(
        f'<tr><td style="font-size:10px;font-weight:700;letter-spacing:1px;color:{ACCENT};">LET’S TALK</td>'
        f'<td align="right"><span style="padding:4px 8px;background:#e8e8ff;border-radius:20px;color:{ACCENT};font-size:10px;white-space:nowrap;">15 minutes</span></td></tr>')
    booking = (f'<div class="action-card" style="margin:22px 0;padding:24px;background:#f6f6ff;border:1px solid #e0e5ff;border-radius:16px;">{booking_header}'
               f'<h2 style="margin:18px 0 10px;font-size:19px;line-height:1.5;letter-spacing:-.3px;color:{INK};">Would you be open to a quick 15-minute call with us?</h2>'
               '<p style="margin:0 0 20px;font-size:14px;line-height:1.8;color:#536078;">We’d love to see how you’re using your profile, hear your thoughts, and learn what would make it more useful for you.</p>'
               f'<a class="feedback-cta" href="{esc(calendar_url)}" style="display:inline-block;padding:13px 20px;background:{ACCENT};border:1px solid {ACCENT};border-radius:10px;color:#ffffff;font-size:13px;font-weight:600;text-decoration:none;">Book a quick chat &rarr;</a>'
               f'<p style="margin:14px 0 0;font-size:10px;line-height:1.8;color:{MUTED};word-break:break-all;">Direct calendar link: <a href="{esc(calendar_url)}" style="color:{ACCENT};">{esc(calendar_url)}</a></p></div>')

    form = (f'<div class="action-card" style="margin:22px 0;padding:24px;background:#f8f9fc;border:1px solid {BORDER};border-radius:16px;">'
            f'<p style="margin:0 0 14px;font-size:10px;font-weight:700;letter-spacing:1px;color:{MUTED};">PREFER TO WRITE?</p>'
            f'<h2 style="margin:0 0 8px;font-size:17px;line-height:1.5;color:{INK};">Can’t make a call? No worries!</h2>'
            '<p style="margin:0 0 18px;font-size:14px;line-height:1.8;color:#536078;">You can share your thoughts in this quick form instead.</p>'
            f'<a class="feedback-cta" href="{esc(form_url)}" style="display:inline-block;padding:11px 17px;background:#ffffff;border:1px solid #d5dce7;border-radius:10px;color:#33405a;font-size:12px;font-weight:600;text-decoration:none;">Share your thoughts &rarr;</a>'
            f'<p style="margin:13px 0 0;font-size:10px;line-height:1.8;color:{MUTED};word-break:break-all;">Form URL: <a href="{esc(form_url)}" style="color:#687489;">{esc(form_url)}</a></p></div>')

    signoff = (f'<div style="margin-top:26px;padding-top:22px;border-top:1px solid #edf0f5;">'
               f'<p style="margin:0 0 20px;font-size:13px;line-height:1.8;color:#536078;">{esc(paragraphs[6])}</p>'
               + table('<tr><td width="44"><div style="width:32px;height:32px;line-height:32px;text-align:center;border-radius:50%;background:#eef2ff;color:#4f46e5;font-size:10px;font-weight:700;">ZY</div></td>'
                       f'<td><span style="font-size:11px;color:{MUTED};">Best,</span><br><strong style="font-size:13px;color:{INK};">Team Zynd</strong></td></tr>') + '</div>')

    footer = f'<p style="margin:0 0 12px;font-size:11px;line-height:1.8;color:{MUTED};">A check-in from Team Zynd about your profile experience.</p>'
    if preview_label or not unsubscribe_url:
        footer += f'<div style="padding:12px;border:1px solid #e4e8ef;border-radius:8px;background:#f0f2f6;font-size:11px;line-height:1.8;color:{MUTED};">{esc(preview_label or "Preview only")}</div>'
    if unsubscribe_url:
        footer += (f'<a href="{DASHBOARD_URL}" style="font-size:11px;color:#687489;">Manage preferences</a> &nbsp;·&nbsp; '
                   f'<a href="{esc(unsubscribe_url)}" style="font-size:11px;color:#687489;">Unsubscribe</a>')
    card = table(
        f'<tr><td class="feedback-header" style="padding:25px 28px;border-bottom:1px solid #edf0f5;">{header}</td></tr>'
        f'<tr><td class="feedback-content" style="padding:28px;">{greeting}{notice}{booking}{form}{signoff}</td></tr>'
        f'<tr><td style="padding:22px 28px;background:#f8f9fc;border-top:1px solid #edf0f5;text-align:center;">{footer}</td></tr>',
        'max-width:640px;margin:auto;background:#ffffff;border:1px solid #e0e6ef;border-radius:18px;overflow:hidden;')
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Your experience on Zynd</title><style>@media only screen and (max-width:520px){.feedback-content,.feedback-header{padding:22px 18px!important}.action-card{padding:20px 16px!important}.feedback-cta{display:block!important;text-align:center!important}}</style></head>'
            f'<body style="margin:0;background:#f4f5f8;color:{INK};font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">'
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">How’s your Zynd profile experience so far? We’d love to hear your thoughts.</div>'
            + table(f'<tr><td align="center" style="padding:28px 12px;">{card}</td></tr>', 'background:#f4f5f8;')
            + '</body></html>')
