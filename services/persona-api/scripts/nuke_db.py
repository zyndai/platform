"""
Clean-slate script for local/dev testing.

Wipes ALL persona-related state so you can re-test registration from scratch:

  1. For every persona in `persona_agents`: deregister it from the Zynd
     DNS registry (so future registrations don't hit 409 "already exists").
  2. Delete every row from each table in WIPE_TABLES (FKs with CASCADE
     handle children automatically).
  3. Optional (`--wipe-users`): delete every row from `auth.users` via
     the Supabase admin API — fully resets sign-ins.

Usage (from the backend/ directory):
    python scripts/nuke_db.py                  # dry run, shows counts
    python scripts/nuke_db.py --yes            # actually wipe
    python scripts/nuke_db.py --yes --wipe-users   # + drop auth.users

Note: this script talks to Supabase via raw HTTP (requests) instead of
supabase-py, because supabase-py's bundled httpx client hangs on the TLS
handshake when the Supabase host is fronted by Cloudflare on the same
machine (no Happy Eyeballs IPv4 fallback). `requests` works fine on the
same path, so we use it everywhere.

DESTRUCTIVE. There is no undo. Meant for dev environments only.
"""

import argparse
import socket
import sys
import time
from pathlib import Path

# Make `config`, `agent.*`, etc. importable when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Python's getaddrinfo returns IPv6 records first when both AAAA and A
# exist. On boxes whose IPv6 path is broken (common with Cloudflare
# tunnels on residential networks), every connection hangs ~30s on the
# IPv6 attempt before falling back. curl avoids this with Happy Eyeballs;
# Python doesn't. We prefer IPv4 for every host the script talks to.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_first(host, *args, **kwargs):
    results = _orig_getaddrinfo(host, *args, **kwargs)
    v4 = [r for r in results if r[0] == socket.AF_INET]
    return v4 or results
socket.getaddrinfo = _ipv4_first  # type: ignore[assignment]

import requests

import config
from agent.zynd_identity import (
    keypair_from_seed,
    load_developer_seed,
    derive_agent_seed,
)


# (table, primary-key column) — the PK is used to drive the
# `not.is.null` DELETE filter, since PostgREST refuses to delete
# without a WHERE clause and not every table has `updated_at`.
WIPE_TABLES: list[tuple[str, str]] = [
    ("dm_messages",           "id"),
    ("dm_threads",            "id"),
    ("agent_tasks",           "id"),
    ("api_tokens",            "id"),
    ("chat_messages",         "id"),
    ("telegram_chat_history", "conversation_id"),
    ("telegram_links",        "user_id"),
    ("linkedin_profiles",     "user_id"),
    ("persona_agents",        "user_id"),
]


def _rest_url(path: str) -> str:
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1{path}"


def _auth_url(path: str) -> str:
    return f"{config.SUPABASE_URL.rstrip('/')}/auth/v1{path}"


def _service_headers() -> dict:
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


def count_rows(table: str) -> int:
    """Return row count via PostgREST's exact-count header."""
    try:
        r = requests.head(
            _rest_url(f"/{table}"),
            headers={**_service_headers(), "Prefer": "count=exact"},
            timeout=15,
        )
        if not r.ok:
            return -1
        rng = r.headers.get("Content-Range", "*/0")
        return int(rng.rsplit("/", 1)[-1])
    except Exception:
        return -1


def list_personas() -> list[dict]:
    try:
        r = requests.get(
            _rest_url("/persona_agents"),
            headers={**_service_headers(), "Accept": "application/json"},
            params={"select": "*"},
            timeout=20,
        )
        r.raise_for_status()
        return r.json() or []
    except Exception as e:
        print(f"  ! could not list personas: {e}")
        return []


def wipe_table(table: str, pk_col: str) -> tuple[bool, str]:
    """DELETE ... WHERE pk_col IS NOT NULL (i.e. all rows)."""
    try:
        r = requests.delete(
            _rest_url(f"/{table}"),
            headers={**_service_headers(), "Prefer": "return=minimal"},
            params={pk_col: "not.is.null"},
            timeout=60,
        )
        if r.ok:
            return True, "ok"
        return False, f"HTTP {r.status_code}: {r.text[:160]}"
    except Exception as e:
        return False, str(e)


def deregister_persona(persona: dict) -> tuple[bool, str]:
    """Deregister a single persona from the Zynd registry.

    Matches the canonical zyndai-agent SDK format (dns_registry.delete_entity):
    sign the raw entity_id bytes, send Authorization: Bearer ed25519:<sig>.
    """
    agent_id = persona.get("agent_id")
    index = persona.get("derivation_index")
    if agent_id is None or index is None:
        return False, "missing agent_id or derivation_index"

    try:
        developer_seed = load_developer_seed(config.ZYND_DEVELOPER_KEYPAIR_PATH)
        seed = derive_agent_seed(developer_seed, index)
        keypair = keypair_from_seed(seed)

        auth_sig = keypair.sign(agent_id.encode())

        resp = requests.delete(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}",
            headers={"Authorization": f"Bearer {auth_sig}"},
            timeout=10,
        )
        ok = resp.status_code in (200, 204, 404)
        detail = f"HTTP {resp.status_code}"
        if not ok and resp.text:
            detail += f" {resp.text[:120]}"
        return ok, detail
    except Exception as e:
        return False, str(e)


def list_auth_users() -> list[dict]:
    """Page through auth.admin.users via the admin REST API."""
    out: list[dict] = []
    page = 1
    while True:
        try:
            r = requests.get(
                _auth_url("/admin/users"),
                headers=_service_headers(),
                params={"page": page, "per_page": 200},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            users = data.get("users") if isinstance(data, dict) else data
            users = users or []
        except Exception as e:
            print(f"  ! list users failed on page {page}: {e}")
            break
        if not users:
            break
        out.extend(users)
        if len(users) < 200:
            break
        page += 1
    return out


def delete_auth_user(user_id: str) -> bool:
    try:
        r = requests.delete(
            _auth_url(f"/admin/users/{user_id}"),
            headers=_service_headers(),
            timeout=15,
        )
        return r.ok
    except Exception:
        return False


def wipe_auth_users(skip_user_ids: set[str] | None = None) -> tuple[int, int]:
    skip = skip_user_ids or set()
    users = list_auth_users()
    deleted = failed = skipped = 0
    for u in users:
        uid = u.get("id") if isinstance(u, dict) else None
        if not uid:
            continue
        if uid in skip:
            skipped += 1
            continue
        if delete_auth_user(uid):
            deleted += 1
        else:
            failed += 1
            print(f"  ! failed to delete user {uid}")
    if skipped:
        print(f"  ⋯ skipped {skipped} user(s) tied to personas whose deregister failed")
    return deleted, failed


def delete_persona_rows_by_user_ids(user_ids: list[str]) -> tuple[bool, str]:
    """Delete persona_agents rows for a specific list of users — used when
    we want to keep failed-deregister rows around so the user can retry."""
    if not user_ids:
        return True, "nothing to delete"
    in_list = "(" + ",".join(f'"{u}"' for u in user_ids) + ")"
    try:
        r = requests.delete(
            _rest_url("/persona_agents"),
            headers={**_service_headers(), "Prefer": "return=minimal"},
            params={"user_id": f"in.{in_list}"},
            timeout=60,
        )
        if r.ok:
            return True, f"deleted {len(user_ids)} row(s)"
        return False, f"HTTP {r.status_code}: {r.text[:160]}"
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(
        description="Wipe all persona/DM/token/LinkedIn data for a clean-slate dev test."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the wipe. Without this flag, prints a dry-run report only.",
    )
    parser.add_argument(
        "--wipe-users",
        action="store_true",
        help="Also delete every row from auth.users (fully reset sign-ins).",
    )
    parser.add_argument(
        "--skip-deregister",
        action="store_true",
        help="Skip registry deregister calls (useful if the registry is down). "
             "Implies --force for the persona_agents wipe — local rows go away "
             "even though the registry will keep its records.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Wipe persona_agents (and matching auth.users with --wipe-users) "
             "even when their registry deregister failed. Without this, failed "
             "rows are kept so you can retry.",
    )
    parser.add_argument(
        "--retry-deregister-only",
        action="store_true",
        help="Only attempt to deregister existing persona_agents rows from the "
             "registry. Skip every wipe step. Useful when a previous run left "
             "registry orphans and you've fixed whatever caused the 401s.",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Zynd clean-slate nuker")
    print(f"Supabase: {config.SUPABASE_URL}")
    print(f"Registry: {config.ZYND_REGISTRY_URL}")
    print("=" * 60)

    print("\nCurrent row counts:")
    for table, _pk in WIPE_TABLES:
        c = count_rows(table)
        label = f"{c}" if c >= 0 else "(missing or inaccessible)"
        print(f"  {table:25s} {label}")

    personas = list_personas()
    print(f"\nPersonas to deregister from registry: {len(personas)}")
    for p in personas:
        print(f"  - {p.get('agent_id')} (user {p.get('user_id')}, idx {p.get('derivation_index')})")

    if args.wipe_users:
        users_preview = list_auth_users()
        print(f"\nauth.users to delete: {len(users_preview)}")

    # Retry-only mode: just walk persona_agents and try to deregister.
    # Skip every wipe step. Useful for cleaning up registry orphans.
    if args.retry_deregister_only:
        if not personas:
            print("\nNothing in persona_agents to retry.")
            return
        print("\nRetrying deregister for existing persona_agents rows...")
        ok_count = fail_count = 0
        for p in personas:
            ok, msg = deregister_persona(p)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {p.get('agent_id')}: {msg}")
            if ok: ok_count += 1
            else:  fail_count += 1
        print(f"\nDone. {ok_count} succeeded, {fail_count} failed.")
        if fail_count:
            print("Failed rows are still in persona_agents — re-run after fixing the cause, or use --force to wipe locally anyway.")
        return

    if not args.yes:
        print("\nDry run. Re-run with --yes to actually wipe.")
        return

    print("\nProceeding with wipe...")

    # Track which deregisters succeeded so we can decide what local
    # state is safe to delete.
    successful_user_ids: list[str] = []
    failed_personas: list[dict]    = []

    if not args.skip_deregister:
        print("\n[1/3] Deregistering personas from registry...")
        for p in personas:
            ok, msg = deregister_persona(p)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {p.get('agent_id')}: {msg}")
            if ok:
                successful_user_ids.append(p["user_id"])
            else:
                failed_personas.append(p)
    else:
        # User explicitly told us not to talk to the registry — that's
        # equivalent to "I accept registry orphans".
        successful_user_ids = [p["user_id"] for p in personas]

    keep_failed = bool(failed_personas) and not args.force and not args.skip_deregister
    failed_user_ids = {p["user_id"] for p in failed_personas}

    print("\n[2/3] Wiping tables...")
    for table, pk in WIPE_TABLES:
        if table == "persona_agents":
            # Selective wipe — keep rows whose deregister failed unless --force.
            if keep_failed:
                ok, msg = delete_persona_rows_by_user_ids(successful_user_ids)
                print(f"  {'✓' if ok else '✗'} persona_agents: {msg} ({len(failed_personas)} kept for retry)")
            else:
                ok, msg = wipe_table(table, pk)
                print(f"  {'✓' if ok else '✗'} {table}: {msg}")
        else:
            ok, msg = wipe_table(table, pk)
            print(f"  {'✓' if ok else '✗'} {table}: {msg}")

    if args.wipe_users:
        print("\n[3/3] Wiping auth.users...")
        # Skip auth users whose persona is still in persona_agents (so
        # failed deregisters don't lose the user that owns them either).
        skip = failed_user_ids if keep_failed else set()
        deleted, failed = wipe_auth_users(skip_user_ids=skip)
        print(f"  Deleted {deleted} users, {failed} failures")
    else:
        print("\n[3/3] Skipped auth.users wipe (pass --wipe-users to include it)")

    if keep_failed:
        print("\n" + "─" * 60)
        print(f"⚠ Kept {len(failed_personas)} persona row(s) whose registry deregister failed:")
        for p in failed_personas:
            print(f"  - {p.get('agent_id')} (user {p.get('user_id')[:8]}…, idx {p.get('derivation_index')})")
        print("\nFix the root cause (most often a developer-key mismatch — see")
        print("  ZYND_DEVELOPER_KEYPAIR_PATH in your .env), then run:")
        print("    python scripts/nuke_db.py --retry-deregister-only")
        print("Or accept the orphans and run with --force to wipe locally.")
    print("\nDone.")


if __name__ == "__main__":
    main()
