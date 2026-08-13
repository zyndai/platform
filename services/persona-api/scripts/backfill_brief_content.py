from __future__ import annotations

"""
Backfill `persona_agents.brief_content` from the existing Google Docs briefs.

Run BEFORE deploying Phase 1 (which removes the Google-Docs read path). For
every persona that still has a brief Google Doc, copy its body text into the
`brief_content` TEXT column so the plain-text brief becomes the single source
of truth. Also rescues the onboarding "My brief" doc stored on
`auth.users.user_metadata.brief_doc` for users whose persona row predates it.

Never raises — logs every migration / skip / failure so a partial run is
still useful and safe to re-run (idempotent: only fills rows whose
`brief_content` is null/empty).

Usage (from the backend/ directory):
    python -m scripts.backfill_brief_content
    # or: python scripts/backfill_brief_content.py
"""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force IPv4 for outbound DNS — same patch as config.py / seed_personas.py;
# the Cloudflare-tunnel'd Supabase host returns AAAA records that hang here.
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first(host, *args, **kwargs):
    results = _orig_getaddrinfo(host, *args, **kwargs)
    v4 = [r for r in results if r[0] == socket.AF_INET]
    return v4 or results


socket.getaddrinfo = _ipv4_first  # type: ignore[assignment]

import requests  # noqa: E402

import config  # noqa: E402


def _read_user_metadata(user_id: str) -> dict:
    """Fetch fresh user_metadata from auth.users via the admin API.

    Mirrors api/brief.py:_read_user_metadata so the backfill keys off the
    same `user_metadata.brief_doc` shape the onboarding flow writes.
    """
    url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if not r.ok:
            return {}
        return (r.json() or {}).get("user_metadata") or {}
    except Exception as e:
        print(f"[backfill] metadata read failed for {user_id}: {e}")
        return {}


def _already_filled(brief_content) -> bool:
    return bool((brief_content or "").strip())


def _write_brief(user_id: str, content: str, source: str) -> None:
    sb = config.get_supabase()
    sb.table("persona_agents").update(
        {"brief_content": content.strip()}
    ).eq("user_id", user_id).execute()
    print(f"[backfill] persona {user_id}: migrated {len(content.strip())} chars ({source})")


def main():
    from mcp.tools.google.docs import read_document

    sb = config.get_supabase()

    # ── 1. persona_agents.brief_doc_id -> brief_content ──────────────
    rows = (
        sb.table("persona_agents")
        .select("user_id,brief_doc_id,brief_content")
        .not_.is_("brief_doc_id", "null")
        .execute()
    )
    for r in rows.data or []:
        if _already_filled(r.get("brief_content")):
            continue
        try:
            got = read_document(user_id=r["user_id"], document_id=r["brief_doc_id"])
            if got.get("success") and (got.get("content") or "").strip():
                _write_brief(r["user_id"], got["content"], "brief_doc_id")
            else:
                print(f"[backfill] persona {r['user_id']}: read failed: {got.get('error')}")
        except Exception as e:
            print(f"[backfill] persona {r['user_id']}: ERROR {e}")

    # ── 2. user_metadata.brief_doc -> brief_content ──────────────────
    # Only for users who have a persona row (join key: persona_agents.user_id
    # == auth.users.id). Fill their brief_content from the onboarding doc if
    # it is still empty.
    personas = (
        sb.table("persona_agents")
        .select("user_id,brief_content")
        .execute()
    )
    for r in personas.data or []:
        user_id = r.get("user_id")
        if not user_id or _already_filled(r.get("brief_content")):
            continue
        meta = _read_user_metadata(user_id)
        brief = meta.get("brief_doc")
        if not isinstance(brief, dict) or not brief.get("doc_id"):
            continue
        try:
            got = read_document(user_id=user_id, document_id=brief["doc_id"])
            if got.get("success") and (got.get("content") or "").strip():
                _write_brief(user_id, got["content"], "user_metadata.brief_doc")
            else:
                print(f"[backfill] persona {user_id}: metadata brief read failed: {got.get('error')}")
        except Exception as e:
            print(f"[backfill] persona {user_id}: ERROR (metadata) {e}")

    print("[backfill] done")


if __name__ == "__main__":
    main()
