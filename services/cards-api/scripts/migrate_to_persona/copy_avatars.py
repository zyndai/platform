"""Copy the `avatars` storage bucket from xmfj to aafo, same object paths.

    SRC_SUPABASE_URL=https://<xmfj-ref>.supabase.co  SRC_SERVICE_KEY=…  \\
    DST_SUPABASE_URL=https://<aafo-ref>.supabase.co  DST_SERVICE_KEY=…  \\
    python copy_avatars.py [--apply]

Dry run by default: lists both buckets and says what would be copied.
With --apply it downloads each object from xmfj and uploads it to aafo with
the same path and content-type. Objects already on aafo with the same size are
skipped, so it is safe to re-run. xmfj is only read. Nothing is deleted.

Afterwards run rewrite_avatar_urls.sql (the command is printed at the end) so
the avatar URLs inside the cards point at aafo.
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import quote

import httpx

BUCKET = "avatars"
PAGE = 100


class Storage:
    """Just the three Storage REST calls this script needs."""

    def __init__(self, base_url: str, service_key: str, client: httpx.Client | None = None):
        self.base = base_url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}
        self.http = client or httpx.Client(timeout=60)

    def bucket_exists(self) -> bool:
        r = self.http.get(f"{self.base}/bucket/{BUCKET}", headers=self.headers)
        if r.status_code == 404 or (r.status_code == 400 and "not found" in r.text.lower()):
            return False
        r.raise_for_status()
        return True

    def _list_dir(self, prefix: str) -> list[dict]:
        out, offset = [], 0
        while True:
            r = self.http.post(
                f"{self.base}/object/list/{BUCKET}",
                headers=self.headers,
                json={"prefix": prefix, "limit": PAGE, "offset": offset,
                      "sortBy": {"column": "name", "order": "asc"}},
            )
            r.raise_for_status()
            page = r.json()
            out += page
            if len(page) < PAGE:
                return out
            offset += PAGE

    def walk(self, prefix: str = "") -> dict[str, dict]:
        """Every object in the bucket as {path: {"size": int, "mimetype": str}}."""
        files: dict[str, dict] = {}
        for item in self._list_dir(prefix):
            path = f"{prefix}/{item['name']}" if prefix else item["name"]
            if item.get("id") is None:  # a folder
                files.update(self.walk(path))
            else:
                meta = item.get("metadata") or {}
                files[path] = {"size": meta.get("size"), "mimetype": meta.get("mimetype") or "application/octet-stream"}
        return files

    def download(self, path: str) -> bytes:
        r = self.http.get(f"{self.base}/object/{BUCKET}/{quote(path)}", headers=self.headers)
        r.raise_for_status()
        return r.content

    def upload(self, path: str, data: bytes, mimetype: str) -> None:
        r = self.http.post(
            f"{self.base}/object/{BUCKET}/{quote(path)}",
            headers={**self.headers, "Content-Type": mimetype, "x-upsert": "true"},
            content=data,
        )
        r.raise_for_status()


def copy_bucket(src: Storage, dst: Storage, apply: bool) -> dict:
    src_files = src.walk()
    dst_files = dst.walk()
    todo = {p: m for p, m in src_files.items()
            if p not in dst_files or dst_files[p]["size"] != m["size"]}
    report = {"source_objects": len(src_files), "already_on_dst": len(src_files) - len(todo),
              "to_copy": len(todo), "copied": 0, "failed": []}
    if not apply:
        return report
    for path, meta in sorted(todo.items()):
        try:
            dst.upload(path, src.download(path), meta["mimetype"])
            report["copied"] += 1
        except httpx.HTTPError as exc:
            report["failed"].append((path, str(exc)))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="really copy (default is a dry run)")
    args = ap.parse_args()

    env = {k: os.environ.get(k, "") for k in
           ("SRC_SUPABASE_URL", "SRC_SERVICE_KEY", "DST_SUPABASE_URL", "DST_SERVICE_KEY")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        print(f"set {', '.join(missing)} (see the header of this file)", file=sys.stderr)
        return 2
    if env["SRC_SUPABASE_URL"].rstrip("/") == env["DST_SUPABASE_URL"].rstrip("/"):
        print("SRC and DST are the same project, refusing.", file=sys.stderr)
        return 2

    src = Storage(env["SRC_SUPABASE_URL"], env["SRC_SERVICE_KEY"])
    dst = Storage(env["DST_SUPABASE_URL"], env["DST_SERVICE_KEY"])
    if not src.bucket_exists():
        print("source has no `avatars` bucket, nothing to copy.", file=sys.stderr)
        return 1
    if not dst.bucket_exists():
        print("destination has no `avatars` bucket. Create it first (plan §5.5).", file=sys.stderr)
        return 1

    report = copy_bucket(src, dst, args.apply)
    print(f"xmfj objects: {report['source_objects']}   already on aafo: {report['already_on_dst']}   "
          f"{'copied' if args.apply else 'would copy'}: {report['copied'] if args.apply else report['to_copy']}")
    for path, err in report["failed"]:
        print(f"FAILED {path}: {err}", file=sys.stderr)
    if not args.apply:
        print("DRY RUN: nothing written. Re-run with --apply.")
        return 0

    s = env["SRC_SUPABASE_URL"].rstrip("/") + "/storage/v1/object/public/avatars/"
    d = env["DST_SUPABASE_URL"].rstrip("/") + "/storage/v1/object/public/avatars/"
    print("\nNext, point the card JSON at the new host (run on aafo):")
    print(f"  psql \"$AAFO_URL\" -X -v ON_ERROR_STOP=1 -v src='{s}' -v dst='{d}' -f rewrite_avatar_urls.sql")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
