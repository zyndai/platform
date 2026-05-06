"""
Seed the local network with placeholder personas for testing.

Creates synthetic auth.users + persona_agents + linkedin_profiles rows so
matching, discovery, and intro flows can be exercised without real OAuth
signups or Apify credits.

Each seed user has a synthesized email like `seed-ravi@zynd-seed.local`.
Re-runs skip already-seeded users (matched by email). `--reset` deletes
all existing seeds first (cascades through persona_agents + linkedin_profiles
via the FK).

Usage (from the backend/ directory):
    python scripts/seed_personas.py                  # add the default set
    python scripts/seed_personas.py --reset          # wipe prior seeds first
    python scripts/seed_personas.py --no-linkedin    # skip linkedin_profiles
    python scripts/seed_personas.py --with-threads   # also create accepted
                                                     #   threads between pairs

A2A v3 note: each seeded persona is registered with a v3 JSON-RPC URL
(`/api/persona/{user_id}/a2a/v1`), so peers fetching the registry get the
new transport directly. The seeded user_metadata.seeded=true flag also
makes the orchestrator's external-mode bypass the approval gate for these
personas (otherwise propose_meeting would dead-end on a card no human
will resolve).

NOTE: After seeding, restart the backend so its heartbeat manager picks
up the new personas. Without heartbeats, the registry eventually marks
them inactive and search_zynd_personas stops returning them.
"""

import argparse
import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force IPv4 for outbound DNS — the Cloudflare-tunnel'd Supabase host
# returns AAAA records that hang on this network. Same patch as nuke_db.py;
# config.py also installs it but apply here pre-import too.
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_first(host, *args, **kwargs):
    results = _orig_getaddrinfo(host, *args, **kwargs)
    v4 = [r for r in results if r[0] == socket.AF_INET]
    return v4 or results
socket.getaddrinfo = _ipv4_first  # type: ignore[assignment]

import requests
from supabase import create_client

import config
from agent.persona_manager import create_persona


SEED_EMAIL_DOMAIN = "zynd-seed.local"


# 8 placeholder personas. Diverse enough to make matching feel real:
# a few founders, a designer, a customer-side person, an investor, a
# senior engineer at a large AI shop. The bios reference specific things
# (recent posts, raises, etc.) so Aria's "why I picked them" lines have
# something to latch on to.
SEEDS: list[dict] = [
    {
        "slug": "ravi",
        "name": "Ravi Shah",
        "headline": "Co-founder at Lattice Labs",
        "bio": "Building agent-to-agent protocol handoffs. Spent the weekend wiring up the dispatcher.",
        "skills": ["agent infrastructure", "developer tools", "protocol design", "fundraising"],
    },
    {
        "slug": "maya",
        "name": "Maya Ortiz",
        "headline": "Product designer, ex-Figma",
        "bio": "Thinking about AI interfaces that don't announce themselves. Lately: how do agents become invisible.",
        "skills": ["AI interfaces", "design systems", "Figma", "user research"],
    },
    {
        "slug": "alex",
        "name": "Alex Reyes",
        "headline": "Head of talent at Cohere",
        "bio": "Looking at agentic tools for the recruiting workflow. Most are overbuilt.",
        "skills": ["recruiting", "talent operations", "evaluating AI tools", "hiring"],
    },
    {
        "slug": "priya",
        "name": "Priya Iyer",
        "headline": "Solo founder, indie SaaS",
        "bio": "Shipping a developer note-taking tool. Bootstrapped, profitable, lonely.",
        "skills": ["indie hacking", "developer tools", "marketing for technical products"],
    },
    {
        "slug": "kenji",
        "name": "Kenji Tanaka",
        "headline": "Senior engineer, Anthropic",
        "bio": "Distributed systems person. Recently writing about long-context models in production.",
        "skills": ["distributed systems", "ML infrastructure", "long-context models", "Rust"],
    },
    {
        "slug": "amara",
        "name": "Amara Okafor",
        "headline": "Partner at Spark Ventures",
        "bio": "Seed-stage. Investing in agent infrastructure and AI-native developer tools.",
        "skills": ["seed investing", "agent infrastructure", "developer tools", "B2B SaaS"],
    },
    {
        "slug": "jonas",
        "name": "Jonas Mueller",
        "headline": "Marketing lead at a late-stage AI startup",
        "bio": "Trying to figure out how to market a product where the moat keeps moving.",
        "skills": ["product marketing", "AI positioning", "content strategy", "growth"],
    },
    {
        "slug": "harini",
        "name": "Harini Krishnan",
        "headline": "Research engineer, Stanford",
        "bio": "PhD studying agent communication protocols. Looking for industry collaborators.",
        "skills": ["agent protocols", "research", "academic publishing", "open source"],
    },
]


def _auth_url(path: str) -> str:
    return f"{config.SUPABASE_URL.rstrip('/')}/auth/v1{path}"


def _service_headers() -> dict:
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }


def list_seed_users() -> list[dict]:
    """Page through auth.users and return the ones with our seed email domain."""
    out: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            _auth_url("/admin/users"),
            headers=_service_headers(),
            params={"page": page, "per_page": 200},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        users = (data.get("users") if isinstance(data, dict) else data) or []
        if not users:
            break
        for u in users:
            email = (u.get("email") or "").lower()
            if email.endswith(f"@{SEED_EMAIL_DOMAIN}"):
                out.append(u)
        if len(users) < 200:
            break
        page += 1
    return out


def find_existing(seeds_by_email: dict[str, dict]) -> dict[str, str]:
    """Return {email → user_id} for already-seeded users."""
    have = {}
    for u in list_seed_users():
        email = (u.get("email") or "").lower()
        if email in seeds_by_email:
            have[email] = u["id"]
    return have


def create_auth_user(email: str, name: str) -> str:
    """Create an auth.users row via the admin API. Returns the new user_id."""
    r = requests.post(
        _auth_url("/admin/users"),
        headers=_service_headers(),
        json={
            "email": email,
            "email_confirm": True,
            "user_metadata": {"full_name": name, "seeded": True},
        },
        timeout=20,
    )
    if not r.ok:
        # If the user already exists (rare race), fetch them.
        if r.status_code == 422 or "already" in r.text.lower():
            existing = list_seed_users()
            for u in existing:
                if (u.get("email") or "").lower() == email.lower():
                    return u["id"]
        raise RuntimeError(f"create_user failed [{r.status_code}]: {r.text[:200]}")
    return r.json()["id"]


def delete_auth_user(user_id: str) -> bool:
    r = requests.delete(
        _auth_url(f"/admin/users/{user_id}"),
        headers=_service_headers(),
        timeout=20,
    )
    return r.ok


def reset_seeds() -> int:
    """Delete every seed auth.user; FK cascades nuke persona_agents +
    linkedin_profiles for those users. Returns count deleted."""
    seeds = list_seed_users()
    n = 0
    for u in seeds:
        if delete_auth_user(u["id"]):
            n += 1
    return n


def insert_linkedin_profile(user_id: str, seed: dict) -> None:
    """Drop a mock linkedin_profiles row so the 'What I've picked up'
    surface and any future LLM bio-synth has something to read."""
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    sb.table("linkedin_profiles").upsert(
        {
            "user_id": user_id,
            "profile_url": f"https://www.linkedin.com/in/{seed['slug']}-seed",
            "raw_profile": {
                "headline": seed["headline"],
                "summary": seed["bio"],
                "skills": seed["skills"],
                "_seeded": True,
            },
            "raw_posts": [],
        },
        on_conflict="user_id",
    ).execute()


def _persona_row_for(user_id: str) -> dict | None:
    """Return the persona_agents row for a seeded user, or None if missing."""
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    r = sb.table("persona_agents").select("*").eq("user_id", user_id).execute()
    return r.data[0] if r.data else None


def seed_accepted_thread_pairs(persona_pairs: list[tuple[dict, dict]]) -> int:
    """Create one accepted dm_thread per pair of personas.

    Idempotent: if a thread (in either direction) already exists between
    the two agent_ids, skip it. Returns the number of new threads created.

    Threads start in 'agent' mode on both sides (so the AI handles
    inbound traffic) with the default permission set — a useful starting
    point for testing the A2A v3 flow without manual UI clicks.
    """
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    created = 0
    for a, b in persona_pairs:
        a_id, b_id = a["agent_id"], b["agent_id"]
        # Existing thread in either direction?
        r1 = sb.table("dm_threads").select("id").eq("initiator_id", a_id).eq("receiver_id", b_id).execute()
        r2 = sb.table("dm_threads").select("id").eq("initiator_id", b_id).eq("receiver_id", a_id).execute()
        if (r1.data or r2.data):
            print(f"  ~ thread {a['name']} ↔ {b['name']}: already exists, skipping")
            continue

        sb.table("dm_threads").insert({
            "initiator_id": a_id,
            "receiver_id": b_id,
            "initiator_name": a["name"],
            "receiver_name": b["name"],
            "status": "accepted",
            "lifecycle": "pending",
            "initiator_mode": "agent",
            "receiver_mode": "agent",
            # permissions JSONB has the conservative default already
            # (can_request_meetings only).
        }).execute()
        created += 1
        print(f"  ✓ thread {a['name']} ↔ {b['name']} (accepted, both in agent mode)")
    return created


async def seed_one(seed: dict, with_linkedin: bool) -> dict:
    email = f"seed-{seed['slug']}@{SEED_EMAIL_DOMAIN}"

    user_id = create_auth_user(email, seed["name"])

    try:
        result = await create_persona(
            user_id=user_id,
            name=seed["name"],
            description=seed["bio"],
            capabilities=seed["skills"][:3],
        )
    except ValueError as e:
        # Already-has-persona — happens on idempotent re-runs.
        return {"slug": seed["slug"], "user_id": user_id, "skipped": str(e)}

    if with_linkedin:
        insert_linkedin_profile(user_id, seed)

    return {
        "slug": seed["slug"],
        "user_id": user_id,
        "agent_id": result["agent_id"],
        "derivation_index": result["derivation_index"],
    }


async def main_async(args) -> None:
    print("=" * 60)
    print("Zynd persona seeder")
    print(f"Supabase: {config.SUPABASE_URL}")
    print(f"Registry: {config.ZYND_REGISTRY_URL}")
    print("=" * 60)

    if args.reset:
        print("\nDeleting existing seeds…")
        n = reset_seeds()
        print(f"  Removed {n} prior seed user(s) (FKs cascaded).")

    seeds_by_email = {
        f"seed-{s['slug']}@{SEED_EMAIL_DOMAIN}": s for s in SEEDS[: args.count]
    }
    existing = find_existing(seeds_by_email)
    if existing:
        print(f"\nSkipping {len(existing)} already-seeded user(s):")
        for e in existing:
            print(f"  - {e}")

    to_create = [s for s in SEEDS[: args.count]
                 if f"seed-{s['slug']}@{SEED_EMAIL_DOMAIN}" not in existing]
    print(f"\nCreating {len(to_create)} persona(s)…")

    for seed in to_create:
        try:
            r = await seed_one(seed, with_linkedin=not args.no_linkedin)
            if "skipped" in r:
                print(f"  ~ {seed['slug']}: {r['skipped']}")
            else:
                print(f"  ✓ {seed['slug']:8s} → {r['agent_id']} (idx {r['derivation_index']})")
        except Exception as e:
            print(f"  ✗ {seed['slug']}: {type(e).__name__}: {e}")

    if args.with_threads:
        print("\nCreating accepted threads between consecutive pairs…")
        # Re-read every active seed persona row (handles both freshly
        # created and pre-existing-skipped users uniformly).
        seed_personas: list[dict] = []
        for s in SEEDS[: args.count]:
            email = f"seed-{s['slug']}@{SEED_EMAIL_DOMAIN}"
            uid = (existing.get(email)
                   or next((u["id"] for u in list_seed_users()
                            if (u.get("email") or "").lower() == email), None))
            if not uid:
                continue
            row = _persona_row_for(uid)
            if row:
                seed_personas.append(row)

        # Pair consecutively: (0,1), (2,3), (4,5), ...
        pairs = [
            (seed_personas[i], seed_personas[i + 1])
            for i in range(0, len(seed_personas) - 1, 2)
        ]
        if not pairs:
            print("  (need at least 2 seeded personas to make a pair)")
        else:
            n = seed_accepted_thread_pairs(pairs)
            print(f"  Created {n} new accepted thread(s).")

    print("\nDone. Restart the backend so the heartbeat manager picks up the new personas.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Seed placeholder personas for testing matching/discovery flows."
    )
    p.add_argument("--count", type=int, default=len(SEEDS),
                   help=f"How many to seed (max {len(SEEDS)}).")
    p.add_argument("--reset", action="store_true",
                   help="Delete all prior seeds first (FKs cascade through persona_agents + linkedin_profiles).")
    p.add_argument("--no-linkedin", action="store_true",
                   help="Skip the linkedin_profiles mock rows.")
    p.add_argument("--with-threads", action="store_true",
                   help="After seeding, also create accepted dm_threads between "
                        "consecutive pairs (seed[0]↔seed[1], seed[2]↔seed[3], …) "
                        "with default permissions and both sides in agent mode. "
                        "Useful for one-shot A2A v3 testing.")
    args = p.parse_args()

    if args.count < 1 or args.count > len(SEEDS):
        p.error(f"--count must be 1..{len(SEEDS)}")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
