"""
Clean-slate script for local/dev testing.

Wipes ALL persona-related state so you can re-test registration from scratch:

  1. For every persona in `persona_agents`: deregister it from the Zynd
     DNS registry (so future registrations don't hit 409 "already exists").
  2. Delete every row from: persona_agents, dm_threads, dm_messages,
     agent_tasks, api_tokens, chat_messages, telegram_links,
     telegram_chat_history.
  3. Optional (`--wipe-users`): delete every row from `auth.users` via
     the Supabase admin API — fully resets sign-ins.

Usage (from the backend/ directory):
    python scripts/nuke_db.py                  # dry run, shows counts
    python scripts/nuke_db.py --yes            # actually wipe
    python scripts/nuke_db.py --yes --wipe-users   # + drop auth.users

DESTRUCTIVE. There is no undo. Meant for dev environments only.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# Make `config`, `agent.*`, etc. importable when running from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from supabase import create_client

import config
from agent.zynd_identity import (
    keypair_from_seed,
    load_developer_seed,
    derive_agent_seed,
)


TABLES_TO_WIPE = [
    # Order matters only for display — Supabase/PostgREST doesn't truncate,
    # so we do DELETE ... WHERE true. FKs with CASCADE will handle children.
    "dm_messages",
    "dm_threads",
    "agent_tasks",
    "api_tokens",
    "chat_messages",
    "telegram_chat_history",
    "telegram_links",
    "persona_agents",
]


def supabase_client():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def deregister_persona(sb, persona: dict) -> tuple[bool, str]:
    """
    Deregister a single persona from the Zynd registry.
    Returns (success, message).
    """
    agent_id = persona.get("agent_id")
    index = persona.get("derivation_index")
    if agent_id is None or index is None:
        return False, "missing agent_id or derivation_index"

    try:
        developer_seed = load_developer_seed(config.ZYND_DEVELOPER_KEYPAIR_PATH)
        seed = derive_agent_seed(developer_seed, index)
        keypair = keypair_from_seed(seed)

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sign_message = f"{agent_id}:{timestamp}"
        signature = keypair.sign(sign_message.encode())

        resp = requests.delete(
            f"{config.ZYND_REGISTRY_URL}/v1/entities/{agent_id}",
            headers={
                "X-Agent-Signature": signature,
                "X-Timestamp": timestamp,
            },
            timeout=10,
        )
        return resp.status_code in (200, 204, 404), f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def count_rows(sb, table: str) -> int:
    try:
        r = sb.table(table).select("*", count="exact").limit(1).execute()
        return r.count or 0
    except Exception:
        return -1  # table doesn't exist or can't access


def wipe_table(sb, table: str) -> tuple[bool, str]:
    """Delete every row. Uses a harmless 'always true' filter since PostgREST
    requires a filter on delete()."""
    try:
        # neq on a column that will never be NULL for any row — this
        # translates to "delete everything". `updated_at` is not null
        # on every table we wipe.
        sb.table(table).delete().neq("updated_at", "1970-01-01T00:00:00Z").execute()
        return True, "ok"
    except Exception as e:
        return False, str(e)


def wipe_auth_users(sb) -> tuple[int, int]:
    """
    Delete every user via the admin API. Returns (deleted, failed).

    We paginate manually because list_users() returns at most `per_page`
    users per call (default ~50).
    """
    deleted = 0
    failed = 0
    page = 1
    while True:
        try:
            users = sb.auth.admin.list_users(page=page, per_page=200)
        except TypeError:
            # Older client signature — fall back to positional
            users = sb.auth.admin.list_users()
        if not users:
            break
        for u in users:
            uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)
            if not uid:
                continue
            try:
                sb.auth.admin.delete_user(uid)
                deleted += 1
            except Exception as e:
                failed += 1
                print(f"  ! failed to delete user {uid}: {e}")
        if len(users) < 200:
            break
        page += 1
    return deleted, failed


def main():
    parser = argparse.ArgumentParser(
        description="Wipe all persona/DM/token data for a clean-slate local test."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the wipe. Without this flag, the script prints a dry-run report only.",
    )
    parser.add_argument(
        "--wipe-users",
        action="store_true",
        help="Also delete every row from auth.users (fully reset sign-ins).",
    )
    parser.add_argument(
        "--skip-deregister",
        action="store_true",
        help="Skip registry deregister calls (useful if the registry is down).",
    )
    args = parser.parse_args()

    sb = supabase_client()

    print("=" * 60)
    print("Zynd clean-slate nuker")
    print(f"Supabase: {config.SUPABASE_URL}")
    print(f"Registry: {config.ZYND_REGISTRY_URL}")
    print("=" * 60)

    # Snapshot row counts
    print("\nCurrent row counts:")
    for t in TABLES_TO_WIPE:
        c = count_rows(sb, t)
        label = f"{c}" if c >= 0 else "(missing or inaccessible)"
        print(f"  {t:30s} {label}")

    personas = sb.table("persona_agents").select("*").execute().data or []
    print(f"\nPersonas to deregister from registry: {len(personas)}")
    for p in personas:
        print(f"  - {p.get('agent_id')} (user {p.get('user_id')}, idx {p.get('derivation_index')})")

    if not args.yes:
        print("\nDry run. Re-run with --yes to actually wipe.")
        return

    print("\nProceeding with wipe...")

    # 1. Deregister each persona
    if not args.skip_deregister:
        print("\n[1/3] Deregistering personas from registry...")
        for p in personas:
            ok, msg = deregister_persona(sb, p)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {p.get('agent_id')}: {msg}")

    # 2. Wipe tables
    print("\n[2/3] Wiping tables...")
    for t in TABLES_TO_WIPE:
        ok, msg = wipe_table(sb, t)
        mark = "✓" if ok else "✗"
        print(f"  {mark} {t}: {msg}")

    # 3. Optionally wipe auth.users
    if args.wipe_users:
        print("\n[3/3] Wiping auth.users...")
        deleted, failed = wipe_auth_users(sb)
        print(f"  Deleted {deleted} users, {failed} failures")
    else:
        print("\n[3/3] Skipped auth.users wipe (pass --wipe-users to include it)")

    print("\nDone. Clean slate.")


if __name__ == "__main__":
    main()
