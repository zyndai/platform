"""Consent-bound named visits; identity always comes from a verified session."""
from uuid import UUID

from fastapi import HTTPException
from postgrest.exceptions import APIError

import config


def user_id(principal) -> str:
    # Foreign-project sessions may read legacy cards, but their UUID is not an
    # auth.users identity in this database and must never be used for preferences.
    if principal.iss != config.SUPABASE_URL.rstrip('/') + '/auth/v1':
        raise HTTPException(403, "Sign in with this database project's account to manage visitor privacy")
    try:
        return str(UUID(principal.sub))
    except (TypeError, ValueError) as exc:
        raise HTTPException(401, "Invalid user identity") from exc


def display_name(principal) -> str:
    metadata = principal.user_metadata or {}
    name = metadata.get("full_name") or metadata.get("name")
    if not isinstance(name, str) or not name.strip() or '@' in name:
        return "Zynd member"
    return ' '.join(name.split())[:80]


def rpc(name, params):
    try:
        return config.get_supabase().rpc(name, params).execute().data
    except APIError as exc:
        raise HTTPException(403 if str(exc.code) == '42501' else 503,
                            "Visitor operation refused" if str(exc.code) == '42501' else
                            "Visitor privacy is unavailable; check the approved visitor migrations") from exc


def preference(uid):
    try:
        rows = (config.get_supabase().table('visitor_preferences').select('anonymous_mode')
                .eq('user_id', uid).limit(1).execute().data or [])
    except APIError as exc:
        raise HTTPException(503, "Visitor privacy is unavailable; check the approved visitor migrations") from exc
    return {'anonymous_mode': rows[0]['anonymous_mode'] if rows else True}


def named_visitors(handle, owner_email):
    try:
        rows = rpc('s10_named_visitors', {'p_handle': handle, 'p_owner_email': owner_email})
        if not isinstance(rows, list):
            raise ValueError('Invalid visitor response')
        return {'available': True, 'items': rows}
    except Exception:
        # Missing migrations never break existing counts or expose partial identity data.
        return {'available': False, 'items': []}
