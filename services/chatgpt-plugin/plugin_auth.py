"""Resource metadata shared by the ChatGPT and Claude plugin servers."""
import json

from fastmcp.server.auth import RemoteAuthProvider
from pydantic import AnyHttpUrl


class ExactIssuerAuth(RemoteAuthProvider):
    """Advertise the authorization server exactly as its own metadata spells `issuer`.

    AnyHttpUrl appends "/" to a bare origin, and OpenAI compares the issuer in the resource
    metadata with the authorization server's `issuer` as exact strings, so the stock
    metadata (https://host/ against https://host) would not match."""

    def __init__(self, issuer: str, **kwargs):
        super().__init__(authorization_servers=[AnyHttpUrl(issuer)], **kwargs)
        self.issuer = issuer

    def get_routes(self, mcp_path: str | None = None):
        routes = super().get_routes(mcp_path)
        for route in routes:
            route.app = _with_issuer(route.app, self.issuer)
        return routes


def _with_issuer(app, issuer: str):
    """Wrap the metadata ASGI app so a GET response names `issuer` verbatim in authorization_servers.

    The body is a few hundred bytes of JSON; everything else (status, headers, CORS preflights) passes through."""
    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "GET":
            return await app(scope, receive, send)
        start, body = None, b""

        async def capture(message):
            nonlocal start, body
            if message["type"] == "http.response.start":
                start = message
            else:
                body += message.get("body", b"")

        await app(scope, receive, capture)
        document = json.loads(body)
        document["authorization_servers"] = [issuer]
        body = json.dumps(document, separators=(",", ":")).encode()
        headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await send({**start, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return wrapped
