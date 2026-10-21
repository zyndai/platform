"""Check the reviewer path against a deployed server, the way ChatGPT would walk it.

The plugin is a public PKCE client, so this script holds the code verifier and needs no
ChatGPT session: authorize -> reviewer form on the login page -> password sign-in ->
consent -> code -> token -> the six plugin tools. It also confirms the same Supabase
session is refused at /token/exchange.

It writes to the reviewer account: a new connection row, and one temporary draft
proposal (expires in 24h, never saved). Run it after seed_review_account.py.

  REVIEW_ACCOUNT_EMAIL=... REVIEW_ACCOUNT_PASSWORD=... \\
  SUPABASE_URL=https://<project>.supabase.co SUPABASE_ANON_KEY=... \\
  uv run python scripts/verify_review_flow.py --base https://api.zynd.ai

SUPABASE_URL / SUPABASE_ANON_KEY must be the project behind /oauth/login (the first
entry of TRUSTED_SUPABASE_PROJECTS). Exits 1 if any check fails.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import os
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

import httpx
from fastmcp import Client

CLIENT_ID = "zynd-chatgpt-plugin"
SCOPES = "memory:recall memory:propose cards:review"
TOOLS = {"recall_memories", "propose_memory", "get_proposal_status",
         "list_pending_facts", "propose_card_fact", "get_public_card"}
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail and not ok else ''}")
    if not ok:
        failures.append(name)
    return ok


def payload(result):
    return getattr(result, "structured_content", None) or getattr(result, "data", None) or {}


async def run(args) -> int:
    email = os.environ["REVIEW_ACCOUNT_EMAIL"].strip().lower()
    password = os.environ["REVIEW_ACCOUNT_PASSWORD"]
    supabase_url, anon_key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"]
    base = args.base.rstrip("/")
    resource = f"{base}/chatgpt/mcp"

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
        authorize = await http.get(f"{base}/oauth/authorize", params={
            "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": args.redirect_uri,
            "state": "verify", "scope": SCOPES, "resource": resource,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        req = parse_qs(urlsplit(authorize.headers.get("location", "")).query).get("zynd_oauth", [""])[0]
        if not check("authorize redirects to the login page", authorize.status_code == 302 and bool(req),
                     f"HTTP {authorize.status_code}: {authorize.text[:120]}"):
            return 1

        login = await http.get(f"{base}/oauth/login", params={"zynd_oauth": req})
        check("login page offers the reviewer form", 'id="reviewer-form"' in login.text)

        signed_in = await http.post(f"{supabase_url}/auth/v1/token?grant_type=password",
                                    headers={"apikey": anon_key}, json={"email": email, "password": password})
        supabase_token = signed_in.json().get("access_token", "") if signed_in.status_code == 200 else ""
        if not check("reviewer password sign-in", bool(supabase_token), f"HTTP {signed_in.status_code}"):
            return 1

        consent = await http.post(f"{base}/oauth/consent", json={"req": req, "supabase_token": supabase_token})
        check("consent screen shows the plugin scopes",
              consent.status_code == 200 and consent.json().get("scope") == SCOPES,
              f"HTTP {consent.status_code}: {consent.text[:120]}")

        complete = await http.post(f"{base}/oauth/complete", json={
            "req": req, "supabase_token": supabase_token, "decision": "approve"})
        redirect = complete.json().get("redirect_url", "") if complete.status_code == 200 else ""
        callback = parse_qs(urlsplit(redirect).query)
        code = callback.get("code", [""])[0]
        if not check("approval mints a code", bool(code) and callback.get("state") == ["verify"],
                     f"HTTP {complete.status_code}: {complete.text[:120]}"):
            return 1

        token = await http.post(f"{base}/oauth/token", data={
            "grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code,
            "redirect_uri": args.redirect_uri, "code_verifier": verifier,
            "resource": resource, "scope": SCOPES})
        grant = token.json() if token.status_code == 200 else {}
        if not check("code exchanges for a plugin-scoped token",
                     bool(grant.get("access_token")) and grant.get("scope") == SCOPES,
                     f"HTTP {token.status_code}: {token.text[:120]}"):
            return 1

        exchange = await http.post(f"{base}/token/exchange", headers={"Authorization": f"Bearer {supabase_token}"})
        check("reviewer session is refused at /token/exchange", exchange.status_code == 401,
              f"HTTP {exchange.status_code}")

    async with Client(resource, auth=grant["access_token"]) as client:
        names = {tool.name for tool in await client.list_tools()}
        check("exactly the six plugin tools are exposed", names == TOOLS, str(sorted(names ^ TOOLS)))

        recall = payload(await client.call_tool("recall_memories", {"query": "current project"}))
        check("recall_memories finds the sample project", bool(recall.get("facts")))

        pending = payload(await client.call_tool("list_pending_facts", {}))
        private = [f for f in pending.get("data", []) if f.get("status") == "private"]
        check("list_pending_facts returns private card facts", len(private) >= 2, f"{len(private)} found")

        card = payload(await client.call_tool("get_public_card", {}))
        check("get_public_card returns public facts", bool(card.get("facts")))

        if private:
            fact = private[0]
            proposal = payload(await client.call_tool(
                "propose_card_fact", {"fact_id": fact["id"], "version": fact["version"]}))
            check("propose_card_fact queues a review", proposal.get("status") == "pending_review")

        draft = payload(await client.call_tool(
            "propose_memory", {"text": "Verification draft from verify_review_flow.py; safe to ignore."}))
        check("propose_memory returns a pending review link",
              draft.get("status") == "pending_review" and "/review/" in draft.get("review_url", ""))
        if draft.get("id"):
            status = payload(await client.call_tool("get_proposal_status", {"proposal_id": draft["id"]}))
            check("get_proposal_status reports pending_review", status.get("status") == "pending_review")

    print(f"\n{'ALL CHECKS PASSED' if not failures else str(len(failures)) + ' CHECK(S) FAILED'}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", default="https://api.zynd.ai")
    parser.add_argument("--redirect-uri", default=os.environ.get(
        "PLUGIN_OAUTH_REDIRECT_URIS", "https://chatgpt.com/connector_platform_oauth_redirect").split(",")[0].strip())
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
