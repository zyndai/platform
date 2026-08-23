"""One-time migration: copy Google Doc brief content → persona_agents.brief_content.

Targets users who have brief_doc_id set but brief_content empty/null.
Idempotent — safe to re-run; already-migrated users are skipped.

Run from repo root:
    uv run python scripts/migrate_brief_gdoc_to_supabase.py [--dry-run]

Requires SUPABASE_URL, SUPABASE_SERVICE_KEY, GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET in environment (same .env the app uses).
"""
import argparse
import asyncio
import sys
import os

# allow importing app modules from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from app.config import settings
from app.tools.google.docs import read_google_doc


def _sb():
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _fetch_unmigrated(sb) -> list[dict]:
    """Users with a Google Doc brief but no brief_content yet."""
    result = (
        sb.table("persona_agents")
        .select("user_id, brief_doc_id, brief_doc_url, name")
        .not_.is_("brief_doc_id", "null")
        .or_("brief_content.is.null,brief_content.eq.")
        .execute()
    )
    return result.data or []


def _write_brief_content(sb, user_id: str, content: str) -> None:
    sb.table("persona_agents").update(
        {"brief_content": content}
    ).eq("user_id", user_id).execute()


async def migrate(dry_run: bool) -> None:
    sb = _sb()
    rows = _fetch_unmigrated(sb)

    if not rows:
        print("Nothing to migrate — all users with brief_doc_id already have brief_content.")
        return

    print(f"Found {len(rows)} user(s) to migrate{' (DRY RUN)' if dry_run else ''}.\n")

    ok = skipped = failed = 0

    for row in rows:
        user_id = row["user_id"]
        doc_id = row["brief_doc_id"]
        name = row.get("name") or user_id
        doc_url = row.get("brief_doc_url") or f"https://docs.google.com/document/d/{doc_id}"

        print(f"  [{name}] doc={doc_id}")

        result = await read_google_doc(user_id=user_id, document_id=doc_id)

        if not result.get("success"):
            err = result.get("error", "unknown error")
            if "Google not connected" in str(err) or "token" in str(err).lower():
                print(f"    SKIP — no Google token: {err}")
                skipped += 1
            else:
                print(f"    FAIL — {err}")
                failed += 1
            continue

        content = (result.get("content") or "").strip()
        if not content:
            print(f"    SKIP — Google Doc is empty (nothing to migrate)")
            skipped += 1
            continue

        print(f"    OK — {len(content)} chars from '{result.get('title', '')}' → brief_content")
        if not dry_run:
            _write_brief_content(sb, user_id, content)
        ok += 1

    print(f"\nDone: {ok} migrated, {skipped} skipped, {failed} failed.")
    if dry_run:
        print("(dry run — no writes performed)")
    if failed:
        print("Failed users could not be migrated automatically (expired/missing Google tokens).")
        print("They will need to re-paste their brief via the MCP brief tools.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Google Doc briefs to Supabase brief_content")
    parser.add_argument("--dry-run", action="store_true", help="Read only, no writes")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
