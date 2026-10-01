"""Export the CARDS data (not the zynd dashboard's) from xmfj into local JSON files.

Read-only: it only issues GET/list requests against xmfj, and writes nothing to
any database. Run it yourself, then point Claude (or anyone) at the output folder.

    export XMFJ_SUPABASE_URL=https://<xmfj-ref>.supabase.co
    export XMFJ_SERVICE_KEY=…            # xmfj service-role key
    python export_xmfj.py [--out DIR]

    # or take both from the dashboard's .env without typing them:
    python export_xmfj.py --env-file ../../../../../dashboard/.env

Optional, for password hashes (the Admin API never returns them):
    export XMFJ_DB_URL='postgresql://postgres.<ref>:<password>@…pooler.supabase.com:5432/postgres'
needs `psql`. Without it everything else is still exported.

What lands in --out (default ./xmfj_export_<date>/, git-ignored):
    agent_profile_cards.json   every card, every column (incl. embedding, claim_token_hash)
    x_accounts.json  x_conversations.json  x_mentions.json
    owner_accounts.json        Supabase Auth accounts of people who own a card
                               (id, email, providers, metadata, timestamps)
    owners_without_account.json  owner emails with no xmfj account
    avatars_listing.json       what is in the `avatars` storage bucket (listing only)
    auth_rows_sql.json         [only with XMFJ_DB_URL] raw auth.users + identities rows
                               for those owners, incl. password hashes
    manifest.json              counts and what was skipped

Not exported: dashboard tables (developer_keys, entities, …), other users, the
persona copy tables, sessions/tokens. The output holds emails and, with
XMFJ_DB_URL, password hashes: it is created owner-only (0700/0600). Delete it
when the restore is done.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

PAGE = 200
CARD_TABLES = {  # table -> primary key used for stable paging
    "agent_profile_cards": "id",
    "x_accounts": "x_user_id",
    "x_conversations": "id",
    "x_mentions": "tweet_id",
}


class Xmfj:
    def __init__(self, base_url: str, service_key: str, client: httpx.Client | None = None):
        self.base = base_url.rstrip("/")
        self.http = client or httpx.Client(timeout=120)
        self.headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    def table(self, name: str, pk: str) -> list[dict]:
        rows: list[dict] = []
        while True:
            r = self.http.get(
                f"{self.base}/rest/v1/{name}",
                headers=self.headers,
                params={"select": "*", "order": f"{pk}.asc", "limit": PAGE, "offset": len(rows)},
            )
            r.raise_for_status()
            page = r.json()
            rows += page
            if len(page) < PAGE:
                return rows

    def auth_users(self) -> list[dict]:
        users, page = [], 1
        while True:
            r = self.http.get(f"{self.base}/auth/v1/admin/users", headers=self.headers,
                              params={"page": page, "per_page": PAGE})
            r.raise_for_status()
            batch = r.json().get("users", [])
            users += batch
            if len(batch) < PAGE:
                return users
            page += 1

    def avatars_listing(self) -> dict:
        b = self.http.get(f"{self.base}/storage/v1/bucket/avatars", headers=self.headers)
        if b.status_code == 404 or (b.status_code == 400 and "not found" in b.text.lower()):
            return {"bucket_exists": False, "objects": []}
        b.raise_for_status()
        objects: list[dict] = []

        def walk(prefix: str) -> None:
            offset = 0
            while True:
                r = self.http.post(f"{self.base}/storage/v1/object/list/avatars", headers=self.headers,
                                   json={"prefix": prefix, "limit": PAGE, "offset": offset,
                                         "sortBy": {"column": "name", "order": "asc"}})
                r.raise_for_status()
                items = r.json()
                for it in items:
                    path = f"{prefix}/{it['name']}" if prefix else it["name"]
                    if it.get("id") is None:
                        walk(path)
                    else:
                        meta = it.get("metadata") or {}
                        objects.append({"path": path, "size": meta.get("size"), "mimetype": meta.get("mimetype"),
                                        "updated_at": it.get("updated_at")})
                if len(items) < PAGE:
                    return
                offset += PAGE

        walk("")
        return {"bucket_exists": True, "objects": objects}


def owner_emails(cards: list[dict]) -> set[str]:
    return {c["owner_email"].strip().lower() for c in cards if c.get("owner_email")}


def pick_owner_accounts(users: list[dict], owners: set[str]) -> tuple[list[dict], list[str]]:
    by_email = {}
    for u in users:
        if u.get("email"):
            by_email.setdefault(u["email"].lower(), []).append(u)
    found = [u for e in sorted(owners) for u in by_email.get(e, [])]
    missing = sorted(e for e in owners if e not in by_email)
    slim = [{
        "id": u["id"], "email": u.get("email"),
        "providers": sorted({i.get("provider") for i in (u.get("identities") or []) if i.get("provider")}
                            | ({u["app_metadata"]["provider"]} if u.get("app_metadata", {}).get("provider") else set())),
        "identities": [{"provider": i.get("provider"), "provider_id": i.get("identity_id") or i.get("id"),
                        "identity_data": i.get("identity_data")} for i in (u.get("identities") or [])],
        "email_confirmed_at": u.get("email_confirmed_at"), "created_at": u.get("created_at"),
        "last_sign_in_at": u.get("last_sign_in_at"), "app_metadata": u.get("app_metadata"),
        "user_metadata": u.get("user_metadata"), "is_anonymous": u.get("is_anonymous"),
        "banned_until": u.get("banned_until"), "factors": len(u.get("factors") or []),
    } for u in found]
    return slim, missing


def sql_auth_rows(db_url: str, owners: set[str]) -> list[dict]:
    """auth.users + identities for the owners, straight from Postgres (has password hashes)."""
    emails = ",".join("'" + e.replace("'", "''") + "'" for e in sorted(owners)) or "''"
    query = (
        "select coalesce(json_agg(t), '[]'::json) from ("
        " select to_jsonb(u) as user, "
        "  (select coalesce(json_agg(to_jsonb(i)), '[]'::json) from auth.identities i where i.user_id = u.id) as identities"
        f" from auth.users u where lower(u.email) in ({emails})) t"
    )
    out = subprocess.run(["psql", db_url, "-X", "-At", "-v", "ON_ERROR_STOP=1",
                          "-c", "set default_transaction_read_only = on", "-c", query],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def load_env_file(path: str) -> dict[str, str]:
    env = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return env


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    path.chmod(0o600)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="output directory (default ./xmfj_export_<date>)")
    ap.add_argument("--env-file", help="read the xmfj URL/service key from a dashboard .env instead of XMFJ_* env vars")
    args = ap.parse_args()

    url, key = os.environ.get("XMFJ_SUPABASE_URL", ""), os.environ.get("XMFJ_SERVICE_KEY", "")
    db_url = os.environ.get("XMFJ_DB_URL", "")
    if args.env_file:
        e = load_env_file(args.env_file)
        url = url or e.get("NEXT_PUBLIC_SUPABASE_URL", "") or e.get("SUPABASE_URL", "")
        key = key or e.get("SUPABASE_SERVICE_ROLE_KEY", "") or e.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("set XMFJ_SUPABASE_URL and XMFJ_SERVICE_KEY (or pass --env-file), see the header.", file=sys.stderr)
        return 2
    if "xmfjvixclgqcmjmtecwv" not in url:
        print(f"refusing: {url} is not the xmfj project (xmfjvixclgqcmjmtecwv).", file=sys.stderr)
        return 2

    out = Path(args.out or f"xmfj_export_{dt.date.today().isoformat()}")
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)

    x = Xmfj(url, key)
    manifest: dict = {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(), "source": url, "files": {}, "skipped": []}

    data = {}
    for table, pk in CARD_TABLES.items():
        data[table] = x.table(table, pk)
        write_json(out / f"{table}.json", data[table])
        manifest["files"][f"{table}.json"] = len(data[table])
        print(f"{table}: {len(data[table])} rows")

    owners = owner_emails(data["agent_profile_cards"])
    accounts, missing = pick_owner_accounts(x.auth_users(), owners)
    write_json(out / "owner_accounts.json", accounts)
    write_json(out / "owners_without_account.json", missing)
    manifest["files"]["owner_accounts.json"] = len(accounts)
    manifest["files"]["owners_without_account.json"] = len(missing)
    print(f"owners: {len(owners)} distinct emails, {len(accounts)} accounts found, {len(missing)} without an account")

    av = x.avatars_listing()
    write_json(out / "avatars_listing.json", av)
    manifest["files"]["avatars_listing.json"] = len(av["objects"])
    print(f"avatars bucket: {'exists' if av['bucket_exists'] else 'does not exist'}, {len(av['objects'])} objects")

    if db_url:
        if not shutil.which("psql"):
            manifest["skipped"].append("auth_rows_sql.json: psql not found")
        else:
            try:
                rows = sql_auth_rows(db_url, owners)
                write_json(out / "auth_rows_sql.json", rows)
                manifest["files"]["auth_rows_sql.json"] = len(rows)
                print(f"auth rows with password hashes: {len(rows)}")
            except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                err = (getattr(exc, "stderr", "") or str(exc)).strip().splitlines()[-1:]  # never echo the URL
                manifest["skipped"].append(f"auth_rows_sql.json: {err}")
                print(f"could not read auth rows over SQL ({err}); continuing without them", file=sys.stderr)
    else:
        manifest["skipped"].append("auth_rows_sql.json: XMFJ_DB_URL not set (password hashes unavailable)")

    write_json(out / "manifest.json", manifest)
    print(f"\ndone -> {out.resolve()}  (contains emails; delete when the restore is finished)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
