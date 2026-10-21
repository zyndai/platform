"""Create or refresh the sample-data account OpenAI's plugin reviewers sign in with.

One dedicated account (REVIEW_ACCOUNT_EMAIL, which must also be listed in
PLUGIN_REVIEW_EMAILS so the server accepts it only through the plugin flow)
gets a Supabase email+password login, a memory user, and sample memory so every
plugin tool returns real data:

  recall_memories      "My current project is Atlas..." (a saved plugin fact) + assertion names
  list_pending_facts   >= MIN_PENDING private card facts
  propose_card_fact    those same facts (each maps to a non-empty public label)
  get_public_card      >= MIN_PUBLIC public facts
  get_proposal_status  one saved-privately and one rejected historical proposal

Reviewers keep re-testing and publishing consumes a pending fact, so the default
run only TOPS UP what is missing; --reset first retires everything the reviewer did.

  uv run python scripts/seed_review_account.py                  # dry run: print the plan, write nothing
  uv run python scripts/seed_review_account.py --apply          # create/refresh the account, top up data
  uv run python scripts/seed_review_account.py --apply --reset  # retire reviewer activity, then reseed

Env: REVIEW_ACCOUNT_EMAIL, REVIEW_ACCOUNT_PASSWORD (24+ chars, never printed),
SUPABASE_SERVICE_KEY, plus the memory service's own DATABASE_URL / REDIS_URL.
The auth user is created in the FIRST trusted Supabase project (the one behind
/oauth/login); pass --supabase-url if the service key belongs to a different one.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "chatgpt-plugin"))  # on PYTHONPATH in the Docker image

import httpx

from app.config import settings

MIN_PENDING = 4
MIN_PUBLIC = 2
MIN_PASSWORD_LENGTH = 24
DISPLAY_NAME = "Zynd Reviewer"

# Private facts the reviewer can review and publish. Predicates must be private-declarable and
# map onto the public card (checked in tests); the pool is larger than MIN_PENDING so a top-up
# can refill after reviewers publish some.
PENDING_POOL = (
    ("is_building", "Atlas project"),
    ("is_working_on", "Customer analytics dashboard"),
    ("has_skill", "Python"),
    ("uses_tool", "PostgreSQL"),
    ("is_learning", "Rust"),
    ("has_skill", "Data modeling"),
    ("uses_tool", "dbt"),
    ("is_working_on", "Onboarding checklist redesign"),
)
PUBLIC_POOL = (
    ("has_expertise_in", "Data engineering"),
    ("is_located_in", "Berlin"),
    ("has_expertise_in", "Analytics"),
)
# Saved through the real consent path. recall_facts is a literal ILIKE, so the first text must
# contain the words a model will search for ("current project").
RECALL_FACT = "My current project is Atlas, a data pipeline for customer analytics."
HISTORY_SAVED = "I prefer short written status updates over long meetings."
HISTORY_REJECTED = "I am considering moving to a new city next year."


def plan_facts(existing: set[tuple[str, str]], pending: int, public: int):
    """(private, public) (predicate, name) pairs to add so the card has MIN_PENDING pending and
    MIN_PUBLIC public facts. `existing` holds the active (predicate, lower-cased name) pairs."""
    def pick(pool, have, need):
        chosen = []
        for predicate, name in pool:
            if have + len(chosen) >= need:
                break
            if (predicate, name.lower()) not in existing:
                chosen.append((predicate, name))
        return chosen
    return pick(PENDING_POOL, pending, MIN_PENDING), pick(PUBLIC_POOL, public, MIN_PUBLIC)


# ── Supabase auth user ──────────────────────────────────────────────────────────

async def ensure_auth_user(base_url: str, service_key: str, email: str, password: str) -> str:
    """Create the confirmed email+password user, or reset its password. Returns the Supabase user id."""
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    admin = base_url.rstrip("/") + "/auth/v1/admin/users"
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        created = await client.post(admin, json={
            "email": email, "password": password, "email_confirm": True,
            "user_metadata": {"full_name": DISPLAY_NAME, "email_verified": True},
        })
        if created.status_code in (200, 201):
            return created.json()["id"]
        already_registered = created.status_code == 422 and created.json().get("error_code") == "email_exists"
        if not already_registered:
            raise RuntimeError(f"supabase create user -> {created.status_code}: {created.text[:200]}")
        page = 1
        while True:
            listing = await client.get(admin, params={"page": page, "per_page": 200})
            listing.raise_for_status()
            users = listing.json().get("users", [])
            for user in users:
                if (user.get("email") or "").lower() == email:
                    updated = await client.put(f"{admin}/{user['id']}", json={
                        "password": password, "email_confirm": True})
                    updated.raise_for_status()
                    return user["id"]
            if len(users) < 200:
                raise RuntimeError("supabase reported the email exists but it was not found")
            page += 1


# ── Memory data ─────────────────────────────────────────────────────────────────

async def active_facts(pool, uid: str) -> set[tuple[str, str]]:
    rows = await pool.fetch(
        """SELECT a.predicate, lower(e.canonical_name) AS name FROM assertions a
             JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1::uuid AND a.valid_until IS NULL""", uid)
    return {(row["predicate"], row["name"]) for row in rows}


async def reset(pool, redis, uid: str) -> None:
    """Retire everything the reviewer did. Assertions are retired (valid_until), never deleted."""
    for raw in await redis.smembers(f"plugin:pending:{uid}"):
        await redis.delete("plugin:proposal:" + (raw.decode() if isinstance(raw, bytes) else raw))
    await redis.delete(f"plugin:pending:{uid}")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """DELETE FROM memory_plugin_outbox WHERE publication_id IN
               (SELECT id FROM memory_plugin_publications WHERE user_id = $1::uuid)""", uid)
        await conn.execute("DELETE FROM memory_plugin_publications WHERE user_id = $1::uuid", uid)
        await conn.execute("DELETE FROM memory_plugin_facts WHERE user_id = $1::uuid", uid)
        await conn.execute("DELETE FROM memory_plugin_consents WHERE user_id = $1::uuid", uid)
        await conn.execute(
            "UPDATE mcp_clients SET revoked_at = now() WHERE user_id = $1::uuid AND revoked_at IS NULL", uid)
        await conn.execute(
            "UPDATE assertions SET valid_until = now() WHERE user_id = $1::uuid AND valid_until IS NULL", uid)


async def seed_plugin_history(pool, redis, uid: str) -> list[str]:
    """Save/reject sample proposals through the real consent path so memory_plugin_* rows stay
    consistent. Needs a live connection row; a throwaway one is created and revoked."""
    import plugin_consent
    from plugin_mcp import PLUGIN_SCOPES

    wanted = []
    for text, decision in ((RECALL_FACT, "approve"), (HISTORY_SAVED, "approve"), (HISTORY_REJECTED, "reject")):
        if decision == "approve":
            present = await pool.fetchval(
                "SELECT 1 FROM memory_plugin_facts WHERE user_id = $1::uuid AND text = $2", uid, text)
        else:
            present = await pool.fetchval(
                "SELECT 1 FROM memory_plugin_consents WHERE user_id = $1::uuid AND status = 'rejected'", uid)
        if not present:
            wanted.append((text, decision))
    if not wanted:
        return []

    jti = str(uuid.uuid4())
    await pool.execute("INSERT INTO mcp_clients (user_id, label, scopes, jti) VALUES ($1::uuid, $2, $3, $4::uuid)",
                       uid, "review account seed", list(PLUGIN_SCOPES), jti)
    try:
        for text, decision in wanted:
            proposal = await plugin_consent.create_proposal(
                pool, redis, uid, "save_memory", text, source_connection_id=jti)
            preview = await plugin_consent.preview(pool, redis, uid, proposal["id"])
            await plugin_consent.decide(pool, redis, uid, proposal["id"], preview["nonce"], decision)
    finally:
        await pool.execute("UPDATE mcp_clients SET revoked_at = now() WHERE jti = $1::uuid", jti)
    return [f"{decision}: {text}" for text, decision in wanted]


# ── Entry point ─────────────────────────────────────────────────────────────────

async def run(args) -> int:
    email = os.environ.get("REVIEW_ACCOUNT_EMAIL", "").strip().lower()
    password = os.environ.get("REVIEW_ACCOUNT_PASSWORD", "")
    if not email or email not in settings.plugin_review_email_set:
        print("REVIEW_ACCOUNT_EMAIL must be set and listed in PLUGIN_REVIEW_EMAILS; refusing to "
              "create a password login the server would not restrict to the plugin flow.")
        return 2
    if args.apply and len(password) < MIN_PASSWORD_LENGTH:
        print(f"REVIEW_ACCOUNT_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters.")
        return 2
    projects = settings.trusted_supabase_project_list
    supabase_url = args.supabase_url or (projects[0][0] if projects else "")
    if not supabase_url or not settings.supabase_service_key:
        print("A trusted Supabase project URL and SUPABASE_SERVICE_KEY are required.")
        return 2

    import redis.asyncio as aioredis
    from app.db import close_pool, get_pool, init_pool
    from app.services import findability
    from app.services.users import resolve_user
    import plugin_consent

    print(f"{'APPLY' if args.apply else 'DRY RUN'}: {email} in {supabase_url}"
          f"{' (with --reset)' if args.reset else ''}")
    await init_pool()
    redis = aioredis.from_url(settings.redis_url)
    try:
        pool = get_pool()
        uid = await pool.fetchval("SELECT id::text FROM users WHERE lower(email) = $1", email)
        pending = public = 0
        if args.apply:
            sub = await ensure_auth_user(supabase_url, settings.supabase_service_key, email, password)
            uid = await resolve_user(pool, email, DISPLAY_NAME, sub)
            print("account: ready")
            if args.reset:
                await reset(pool, redis, uid)
                print("reset: reviewer activity retired")
        elif not uid:
            print("account: would be created")
        if uid:
            pending = sum(1 for f in (await plugin_consent.list_pending(pool, redis, uid))["data"]
                          if f.get("status") == "private")
            public = len(await findability.get_card(pool, uid))
            private_add, public_add = plan_facts(await active_facts(pool, uid), pending, public)
        else:
            private_add, public_add = plan_facts(set(), 0, 0)
        print(f"facts: {len(private_add)} private + {len(public_add)} public to add")
        for predicate, name in private_add + public_add:
            print(f"  {predicate}: {name}")
        if args.apply:
            for predicate, name in private_add:
                await findability.declare_private(pool, uid, predicate, name)
            for predicate, name in public_add:
                await findability.declare(pool, uid, predicate, name)
            for line in await seed_plugin_history(pool, redis, uid):
                print(f"  plugin history, {line}")
        if args.apply and (len(private_add) < MIN_PENDING - pending or len(public_add) < MIN_PUBLIC - public):
            print("warning: sample pool exhausted; run with --reset to restore the full set")
        return 0
    finally:
        await redis.aclose()
        await close_pool()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    parser.add_argument("--reset", action="store_true", help="with --apply: retire reviewer activity first")
    parser.add_argument("--supabase-url", default="", help="override the first trusted Supabase project")
    args = parser.parse_args()
    if args.reset and not args.apply:
        parser.error("--reset requires --apply")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
