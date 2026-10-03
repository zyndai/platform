"""copy_avatars.py against two in-memory fake Storage APIs (no network)."""
import importlib.util
import json
from pathlib import Path

import httpx

_spec = importlib.util.spec_from_file_location(
    "copy_avatars", Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_persona" / "copy_avatars.py"
)
copy_avatars = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(copy_avatars)


class FakeStorage:
    """Minimal Supabase Storage: {path: (bytes, mimetype)} behind the REST routes the script uses."""

    def __init__(self, files: dict[str, tuple[bytes, str]] | None = None, has_bucket: bool = True):
        self.files = dict(files or {})
        self.has_bucket = has_bucket
        self.uploads: list[tuple[str, dict]] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/storage/v1")
        if req.method == "GET" and path == "/bucket/avatars":
            return httpx.Response(200 if self.has_bucket else 404, json={"id": "avatars"})
        if req.method == "POST" and path == "/object/list/avatars":
            body = json.loads(req.content)
            prefix = body["prefix"].strip("/")
            seen, items = set(), []
            for p in sorted(self.files):
                if prefix and not p.startswith(prefix + "/"):
                    continue
                rest = p[len(prefix) + 1:] if prefix else p
                head = rest.split("/")[0]
                if head in seen:
                    continue
                seen.add(head)
                if "/" in rest:
                    items.append({"name": head, "id": None, "metadata": None})
                else:
                    data, mime = self.files[p]
                    items.append({"name": head, "id": "x", "metadata": {"size": len(data), "mimetype": mime}})
            return httpx.Response(200, json=items[body["offset"]: body["offset"] + body["limit"]])
        if path.startswith("/object/avatars/"):
            key = path.removeprefix("/object/avatars/")
            if req.method == "GET":
                return httpx.Response(200, content=self.files[key][0]) if key in self.files else httpx.Response(404)
            if req.method == "POST":
                self.files[key] = (req.content, req.headers["content-type"])
                self.uploads.append((key, dict(req.headers)))
                return httpx.Response(200, json={"Key": key})
        return httpx.Response(500, text=f"unexpected {req.method} {req.url}")

    def api(self) -> "copy_avatars.Storage":
        return copy_avatars.Storage("https://x.supabase.co", "key", httpx.Client(transport=httpx.MockTransport(self.handler)))


def test_copies_nested_objects_with_content_type_and_skips_same_size():
    src = FakeStorage({
        "u1/a.png": (b"AAAA", "image/png"),
        "u1/deep/b.jpg": (b"BBBBBB", "image/jpeg"),
        "root.webp": (b"C", "image/webp"),
    })
    dst = FakeStorage({"u1/a.png": (b"ZZZZ", "image/png")})  # same size: considered already there

    report = copy_avatars.copy_bucket(src.api(), dst.api(), apply=True)

    assert report["source_objects"] == 3 and report["already_on_dst"] == 1
    assert report["copied"] == 2 and report["failed"] == []
    assert dst.files["u1/deep/b.jpg"] == (b"BBBBBB", "image/jpeg")
    assert dst.files["root.webp"][1] == "image/webp"
    assert dst.files["u1/a.png"][0] == b"ZZZZ"  # untouched
    assert all(h["x-upsert"] == "true" for _, h in dst.uploads)


def test_changed_size_is_recopied_and_dry_run_writes_nothing():
    src = FakeStorage({"a.png": (b"new-bigger", "image/png")})
    dst = FakeStorage({"a.png": (b"old", "image/png")})

    dry = copy_avatars.copy_bucket(src.api(), dst.api(), apply=False)
    assert dry["to_copy"] == 1 and dry["copied"] == 0 and dst.uploads == []

    copy_avatars.copy_bucket(src.api(), dst.api(), apply=True)
    assert dst.files["a.png"][0] == b"new-bigger"


def test_failed_upload_is_reported_not_raised():
    src = FakeStorage({"a.png": (b"A", "image/png"), "b.png": (b"B", "image/png")})
    dst = FakeStorage()
    real = dst.handler

    def flaky(req):
        if req.method == "POST" and req.url.path.endswith("/a.png"):
            return httpx.Response(500, text="boom")
        return real(req)

    dst_api = copy_avatars.Storage("https://y.supabase.co", "k", httpx.Client(transport=httpx.MockTransport(flaky)))
    report = copy_avatars.copy_bucket(src.api(), dst_api, apply=True)
    assert report["copied"] == 1 and [p for p, _ in report["failed"]] == ["a.png"]


def test_pagination_past_one_page():
    src = FakeStorage({f"f{i:03}.png": (b"x", "image/png") for i in range(copy_avatars.PAGE + 5)})
    report = copy_avatars.copy_bucket(src.api(), FakeStorage().api(), apply=False)
    assert report["source_objects"] == copy_avatars.PAGE + 5


def test_bucket_exists_detects_missing_bucket():
    assert FakeStorage(has_bucket=True).api().bucket_exists() is True
    assert FakeStorage(has_bucket=False).api().bucket_exists() is False
