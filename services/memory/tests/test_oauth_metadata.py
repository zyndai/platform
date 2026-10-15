"""Network-isolated security tests for URL client ID metadata fetching."""

import asyncio
import json
import socket
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import oauth


URL = "https://metadata.example/client.json"
ADDRESS = "93.184.216.34"
REDIRECT = "https://app.example/callback"


def _document(**overrides):
    return {"client_id": URL, "redirect_uris": [REDIRECT], **overrides}


class _Stream:
    def __init__(self, response, *, stalled=False):
        self.chunks = list(response)
        self.stalled = stalled
        self.tls_hostnames = []
        self.requests = []

    async def read(self, max_bytes, timeout=None):
        if self.chunks:
            return self.chunks.pop(0)
        if self.stalled:
            await asyncio.Event().wait()
        return b""

    async def write(self, buffer, timeout=None):
        self.requests.append(buffer)

    async def aclose(self):
        pass

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info):
        return None


def _response(body=b"", *, status=200, headers=None, stalled=False):
    headers = headers or {}
    lines = [f"HTTP/1.1 {status} OK", "Connection: close"]
    if "Content-Type" not in headers:
        lines.append("Content-Type: application/json")
    if stalled:
        lines.append("Transfer-Encoding: chunked")
    else:
        lines.append(f"Content-Length: {len(body)}")
    lines.extend(f"{key}: {value}" for key, value in headers.items())
    prefix = ("\r\n".join(lines) + "\r\n\r\n").encode()
    return _Stream([prefix, body] if body else [prefix], stalled=stalled)


@pytest.fixture
async def network(monkeypatch):
    oauth._metadata_cache.clear()
    loop = asyncio.get_running_loop()
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ADDRESS, 443))])
    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    streams = []
    connects = []

    class Backend:
        async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
            connects.append((host, port))
            return streams.pop(0)

    monkeypatch.setattr(oauth.httpcore._backends.auto, "AutoBackend", Backend)
    yield lookup, streams, connects
    oauth._metadata_cache.clear()


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["10.2.3.4"], ["169.254.169.254"],
    ["93.184.216.34", "192.168.1.1"], ["::1"], ["fc00::1"],
])
async def test_resolved_private_address_rejected_before_connect(network, addresses):
    lookup, _, connects = network
    lookup.return_value = [(socket.AF_INET6 if ":" in addr else socket.AF_INET,
                            socket.SOCK_STREAM, 6, "", (addr, 443)) for addr in addresses]
    with pytest.raises(HTTPException, match="private host") as error:
        await oauth._fetch_metadata_document(URL)
    assert error.value.status_code == 400
    assert connects == []
    lookup.assert_awaited_once_with("metadata.example", 443, type=socket.SOCK_STREAM)


async def test_validated_address_is_connected_without_second_lookup_and_tls_uses_url_host(network):
    lookup, streams, connects = network
    stream = _response(json.dumps(_document()).encode())
    streams.append(stream)
    assert await oauth._fetch_metadata_document(URL) == _document()
    lookup.assert_awaited_once()
    assert connects == [(ADDRESS, 443)]
    assert stream.tls_hostnames == ["metadata.example"]
    assert any(b"Host: metadata.example" in data for data in stream.requests)


async def test_pinned_backend_does_not_connect_unvalidated_host_or_unix_socket(monkeypatch):
    backend = oauth._PinnedBackend("metadata.example", [ADDRESS])
    connect = AsyncMock()
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    with pytest.raises(OSError, match="host changed"):
        await backend.connect_tcp("other.example", 443)
    with pytest.raises(OSError, match="unix sockets unavailable"):
        await backend.connect_unix_socket("/tmp/socket")
    connect.assert_not_awaited()


@pytest.mark.parametrize("url", [
    "http://metadata.example/client.json", "https://localhost/client.json",
    "https://127.0.0.1/client.json", "https://metadata.example:8443/client.json",
    "https://user@metadata.example/client.json", "https://metadata.example/client.json#fragment",
    "https://metadata.example:bad/client.json", "https://[::1]/client.json",
])
async def test_invalid_metadata_urls_do_not_resolve(network, url):
    lookup, _, connects = network
    with pytest.raises(HTTPException) as error:
        await oauth._fetch_metadata_document(url)
    assert error.value.status_code == 400
    lookup.assert_not_awaited()
    assert connects == []


async def test_unclosed_ipv6_bracket_returns_bad_request(network):
    lookup, _, connects = network
    with pytest.raises(HTTPException) as error:
        await oauth._fetch_metadata_document("https://[::1/client.json")
    assert error.value.status_code == 400
    lookup.assert_not_awaited()
    assert connects == []


@pytest.mark.parametrize("stream,detail", [
    (_response(status=302, headers={"Location": "https://other.example/client.json"}), "returned 302"),
    (_response(b"{}", headers={"Content-Type": "text/html"}), "not JSON"),
    (_response(b"{}", headers={"Content-Encoding": "gzip"}), "encoded metadata document unsupported"),
    (_response(b"x" * (oauth._METADATA_MAX_BYTES + 1)), "exceeds size limit"),
    (_response(b"not json"), "not valid JSON"),
    (_response(b"[]"), "must be a JSON object"),
    (_response(json.dumps(_document(client_id="https://other.example/client.json")).encode()), "client_id mismatch"),
    (_response(json.dumps(_document(redirect_uris=[])).encode()), "missing redirect_uris"),
    (_response(json.dumps(_document(redirect_uris=["https://user@app.example/callback"])).encode()), "invalid metadata redirect_uris"),
    (_response(json.dumps(_document(redirect_uris=["https://app.example/callback#fragment"])).encode()), "invalid metadata redirect_uris"),
])
async def test_untrusted_response_rejected_without_caching(network, stream, detail):
    _, streams, connects = network
    streams.append(stream)
    with pytest.raises(HTTPException, match=detail) as error:
        await oauth._fetch_metadata_document(URL)
    assert error.value.status_code == 400
    assert connects == [(ADDRESS, 443)]
    assert URL not in oauth._metadata_cache


async def test_total_deadline_cancels_stalled_body(network, monkeypatch):
    _, streams, _ = network
    streams.append(_response(stalled=True))
    monkeypatch.setattr(oauth, "_METADATA_FETCH_TIMEOUT", 0.02)
    with pytest.raises(HTTPException, match="fetch timed out") as error:
        await oauth._fetch_metadata_document(URL)
    assert error.value.status_code == 400
    assert URL not in oauth._metadata_cache
