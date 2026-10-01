"""export_xmfj.py against a fake xmfj (no network)."""
import importlib.util
import json
import stat
from pathlib import Path

import httpx

_spec = importlib.util.spec_from_file_location(
    "export_xmfj", Path(__file__).resolve().parent.parent / "scripts" / "migrate_to_persona" / "export_xmfj.py"
)
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

RealXmfj = ex.Xmfj
URL = "https://xmfjvixclgqcmjmtecwv.supabase.co"
CARDS = [
    {"id": "c1", "status": "published", "owner_email": "Alice@Example.com", "card": {}},
    {"id": "c2", "status": "draft", "owner_email": None, "card": {}},
    {"id": "c3", "status": "archived", "owner_email": "ghost@example.com", "card": {}},
]
USERS = [
    {"id": "u1", "email": "alice@example.com", "identities": [{"provider": "google", "identity_id": "i1", "identity_data": {"sub": "g"}}],
     "app_metadata": {"provider": "google"}, "factors": [{"id": "f"}]},
    {"id": "u2", "email": "dev@zynd.ai", "identities": [], "app_metadata": {}},   # dashboard dev: must not be exported
]


def fake(many_cards: int = 0, bucket: bool = False):
    cards = CARDS + [{"id": f"x{i:04}", "status": "draft", "owner_email": None, "card": {}} for i in range(many_cards)]

    def handler(req: httpx.Request) -> httpx.Response:
        p, q = req.url.path, dict(req.url.params)
        if p == "/rest/v1/agent_profile_cards":
            off, lim = int(q["offset"]), int(q["limit"])
            return httpx.Response(200, json=cards[off:off + lim])
        if p.startswith("/rest/v1/x_"):
            return httpx.Response(200, json=[])
        if p == "/auth/v1/admin/users":
            return httpx.Response(200, json={"users": USERS})
        if p == "/storage/v1/bucket/avatars":
            return httpx.Response(200 if bucket else 404, json={})
        if p == "/storage/v1/object/list/avatars":
            return httpx.Response(200, json=[{"name": "a.png", "id": "o", "metadata": {"size": 3, "mimetype": "image/png"}}])
        return httpx.Response(500, text=p)

    return RealXmfj(URL, "key", httpx.Client(transport=httpx.MockTransport(handler)))


def test_pages_through_a_table():
    assert len(fake(many_cards=ex.PAGE + 7).table("agent_profile_cards", "id")) == ex.PAGE + 7 + len(CARDS)


def test_only_owners_are_exported_and_missing_ones_reported():
    owners = ex.owner_emails(CARDS)
    assert owners == {"alice@example.com", "ghost@example.com"}
    accounts, missing = ex.pick_owner_accounts(fake().auth_users(), owners)
    assert [a["email"] for a in accounts] == ["alice@example.com"]      # dev@zynd.ai is not an owner
    assert accounts[0]["providers"] == ["google"] and accounts[0]["factors"] == 1
    assert missing == ["ghost@example.com"]


def test_avatars_listing_handles_missing_and_present_bucket():
    assert fake(bucket=False).avatars_listing() == {"bucket_exists": False, "objects": []}
    got = fake(bucket=True).avatars_listing()
    assert got["bucket_exists"] and got["objects"][0]["path"] == "a.png"


def test_main_writes_private_files_and_refuses_other_projects(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ex, "Xmfj", lambda url, key: fake())
    monkeypatch.setenv("XMFJ_SUPABASE_URL", URL)
    monkeypatch.setenv("XMFJ_SERVICE_KEY", "secret")
    monkeypatch.delenv("XMFJ_DB_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["export_xmfj.py", "--out", str(tmp_path / "out")])
    assert ex.main() == 0
    out = tmp_path / "out"
    assert len(json.loads((out / "agent_profile_cards.json").read_text())) == 3
    assert json.loads((out / "owners_without_account.json").read_text()) == ["ghost@example.com"]
    assert stat.S_IMODE((out / "owner_accounts.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert "secret" not in capsys.readouterr().out

    monkeypatch.setenv("XMFJ_SUPABASE_URL", "https://aafoguuvmaxymrtnfafn.supabase.co")
    assert ex.main() == 2
