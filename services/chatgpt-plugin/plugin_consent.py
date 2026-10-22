"""Temporary plugin proposals and transaction-bound owner consent."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.services.findability import DECLARE_ENTITY_TYPE, _APPROVE_AS
from app.services.quality import public_label_for
from app.taxonomy import FINDABILITY_PREDICATES, decay_fn_for

PROPOSAL_TTL = 24 * 3600
PREVIEW_TTL = 15 * 60
MAX_TEXT = 2000


# The skills tell the model never to propose credentials; this is the server-side
# backstop so a key or password can never become a draft the owner might save.
_SECRET_PATTERNS = [re.compile(p) for p in (
    r"\bsk-[A-Za-z0-9_-]{10,}",                                  # OpenAI-style keys
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_\w{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",                                     # AWS access key id
    r"\bAIza[0-9A-Za-z_-]{30,}",                                 # Google API key
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",                           # Slack tokens
    r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.",           # JWTs
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)\b(?:password|passcode|passwd|pwd)\s*(?:is|[:=])\s*\S",
    r"(?i)\b(?:api[_ -]?key|access[_ -]?key|secret[_ -]?key|client[_ -]?secret|auth[_ -]?token)\s*(?:is|[:=])\s*\S",
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}",
)]
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")


def looks_like_secret(text: str) -> bool:
    """True for recognizable credentials, or any 32+ character run mixing letters and digits."""
    if any(p.search(text) for p in _SECRET_PATTERNS):
        return True
    return any(re.search(r"[A-Za-z]", m) and re.search(r"\d", m) for m in _LONG_TOKEN.findall(text))


class ConsentError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _key(proposal_id: str) -> str:
    return f"plugin:proposal:{proposal_id}"


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read(raw) -> dict | None:
    return json.loads(raw) if raw else None


def _view(data: dict) -> dict:
    return {key: data[key] for key in ("id", "action", "text", "expires_at", "status", "version")}


async def create_proposal(
    pool, redis, uid: str, action: str, text: str, *, source_connection_id: str | None = None,
    connection_jti: str | None = None, source_client_id: str = "zynd-chatgpt-plugin",
    assertion_id: str | None = None,
    assertion_version: int | None = None, predicate: str | None = None,
    value: str | None = None,
) -> dict:
    """Create a private, owner-bound, short-lived draft; never write a fact here."""
    if action not in ("save_memory", "publish_card_fact"):
        raise ConsentError(422, "unsupported action")
    if not text or not text.strip() or len(text) > MAX_TEXT:
        raise ConsentError(422, "fact must contain 1 to 2000 characters")
    if looks_like_secret(text):
        raise ConsentError(422, "this looks like a password, key or token; Zynd does not store secrets")
    connection_jti = source_connection_id or connection_jti
    if not connection_jti or not await _connection_valid(pool, uid, connection_jti):
        raise ConsentError(403, "connection revoked")
    proposal_id = str(uuid.uuid4())
    data = {
        "id": proposal_id, "uid": str(uid), "action": action, "text": text,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=PROPOSAL_TTL)).isoformat(),
        "status": "pending_review", "version": 1, "connection_jti": connection_jti,
        "source_client_id": source_client_id,
    }
    if action == "publish_card_fact":
        if not assertion_id:
            raise ConsentError(422, "public proposal requires an existing fact")
        try:
            assertion_id = str(uuid.UUID(assertion_id))
        except ValueError:
            raise ConsentError(422, "invalid fact identifier") from None
        row = await pool.fetchrow(
            """SELECT a.id, a.version, a.predicate, e.canonical_name AS value
                 FROM assertions a JOIN entities e ON e.id = a.object_entity_id
                WHERE a.id = $1::uuid AND a.user_id = $2::uuid
                  AND a.valid_until IS NULL AND a.is_public = false""",
            assertion_id, uid,
        )
        if not row or (assertion_version is not None and row["version"] != assertion_version):
            raise ConsentError(409, "fact missing or changed")
        original = row["predicate"]
        mapped = _APPROVE_AS.get(original, original)
        if mapped not in FINDABILITY_PREDICATES or mapped not in DECLARE_ENTITY_TYPE:
            raise ConsentError(422, "fact cannot be represented on the public card")
        if (predicate is not None and predicate != original) or (value is not None and value != row["value"]):
            raise ConsentError(409, "fact differs from stored value")
        label = public_label_for(mapped, row["value"])
        if not label or label != text:
            raise ConsentError(422, "public text must match the final card wording")
        data.update(assertion_id=assertion_id, assertion_version=row["version"],
                    predicate=mapped, value=row["value"], public_text=label)
    data["content_hash"] = _digest({key: data[key] for key in data if key not in ("content_hash", "status")})
    if not await redis.set(_key(proposal_id), json.dumps(data), ex=PROPOSAL_TTL, nx=True):
        raise ConsentError(503, "proposal unavailable")
    await redis.sadd(f"plugin:pending:{uid}", proposal_id)
    await redis.expire(f"plugin:pending:{uid}", PROPOSAL_TTL)
    return {"id": proposal_id, "status": "pending_review", "expires_at": data["expires_at"],
            "review_url": f"{settings.cards_site_base_url.rstrip('/')}/review/{proposal_id}"}


async def create_card_proposal(pool, redis, uid: str, fact_id: str, version: int, *,
                               source_connection_id: str | None = None,
                               connection_jti: str | None = None,
                               source_client_id: str = "zynd-chatgpt-plugin") -> dict:
    try:
        fact_id = str(uuid.UUID(fact_id))
    except (ValueError, TypeError):
        raise ConsentError(404, "private fact not found") from None
    row = await pool.fetchrow(
        """SELECT a.id, a.version, a.predicate, e.canonical_name AS value
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1::uuid AND a.id = $2::uuid AND a.version = $3
              AND a.valid_until IS NULL AND a.is_public = false
            LIMIT 1""", uid, fact_id, version)
    if not row:
        raise ConsentError(404, "private fact not found")
    mapped = _APPROVE_AS.get(row["predicate"], row["predicate"])
    return await create_proposal(pool, redis, uid, "publish_card_fact",
                                 public_label_for(mapped, row["value"]),
                                 source_connection_id=source_connection_id or connection_jti,
                                 source_client_id=source_client_id, assertion_id=str(row["id"]),
                                 assertion_version=row["version"], predicate=row["predicate"],
                                 value=row["value"])


async def _connection_valid(pool, uid: str, jti: str) -> bool:
    try:
        uuid.UUID(jti)
    except (ValueError, TypeError):
        return False
    return bool(await pool.fetchval(
        "SELECT 1 FROM mcp_clients WHERE jti = $1::uuid AND user_id = $2::uuid AND revoked_at IS NULL",
        jti, uid))


async def get_status(pool, redis, uid: str, proposal_id: str) -> dict:
    try:
        uuid.UUID(proposal_id)
    except ValueError:
        raise ConsentError(404, "proposal not found") from None
    raw = _read(await redis.get(_key(proposal_id)))
    if raw and raw["uid"] != str(uid):
        raise ConsentError(404, "proposal not found")
    row = await pool.fetchrow(
        "SELECT status, user_id FROM memory_plugin_consents WHERE proposal_id = $1::uuid",
        proposal_id)
    if row:
        if str(row["user_id"]) != str(uid):
            raise ConsentError(404, "proposal not found")
        return {"id": proposal_id, "status": row["status"]}
    if not raw:
        raise ConsentError(404, "proposal not found")
    if datetime.fromisoformat(raw["expires_at"]) <= datetime.now(timezone.utc):
        await redis.delete(_key(proposal_id))
        return {"id": proposal_id, "status": "expired"}
    return {"id": proposal_id, "status": "pending_review", "expires_at": raw["expires_at"]}


async def list_pending(pool, redis, uid: str) -> dict:
    ids = await redis.smembers(f"plugin:pending:{uid}")
    result = []
    rows = await pool.fetch(
        """SELECT a.id, a.version, a.predicate, e.canonical_name AS object
             FROM assertions a JOIN entities e ON e.id = a.object_entity_id
            WHERE a.user_id = $1::uuid AND a.valid_until IS NULL AND NOT a.is_public
              AND a.dismissed_at IS NULL AND a.predicate = ANY($2::text[])
            ORDER BY a.extracted_at DESC LIMIT 30""",
        uid, list(FINDABILITY_PREDICATES | _APPROVE_AS.keys()))
    result.extend({"id": str(r["id"]), "version": r["version"], "predicate": r["predicate"],
                   "object": r["object"], "public_text": public_label_for(
                       _APPROVE_AS.get(r["predicate"], r["predicate"]), r["object"]),
                   "status": "private"} for r in rows)
    for raw_id in ids:
        proposal_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        data = _read(await redis.get(_key(proposal_id)))
        if data and data["uid"] == str(uid) and datetime.fromisoformat(data["expires_at"]) > datetime.now(timezone.utc):
            result.append({"id": proposal_id, "action": data["action"],
                           "status": "pending_review", "expires_at": data["expires_at"]})
        else:
            await redis.srem(f"plugin:pending:{uid}", proposal_id)
    return {"ok": True, "data": result}


async def get_review(pool, redis, uid: str, proposal_id: str) -> dict:
    status = await get_status(pool, redis, uid, proposal_id)
    data = _read(await redis.get(_key(proposal_id)))
    if not data:
        return status
    view = _view(data)
    view["status"] = status["status"]
    if data.get("public_text") is not None:
        view["public_text"] = data["public_text"]
    return view


async def preview(pool, redis, uid: str, proposal_id: str, public_text: str | None = None) -> dict:
    data = _read(await redis.get(_key(proposal_id)))
    status = await get_status(pool, redis, uid, proposal_id)
    if not data or status["status"] != "pending_review":
        raise ConsentError(409, "proposal is no longer pending")
    if public_text is not None and public_text != data.get("public_text"):
        raise ConsentError(409, "public wording changed; create a new exact proposal")
    if not await _connection_valid(pool, uid, data["connection_jti"]):
        raise ConsentError(403, "connection revoked")
    if data["action"] == "publish_card_fact":
        row = await pool.fetchrow(
            """SELECT a.version, a.is_public, a.valid_until, e.canonical_name AS value
                 FROM assertions a JOIN entities e ON e.id = a.object_entity_id
                WHERE a.id = $1::uuid AND a.user_id = $2::uuid""",
            data["assertion_id"], uid)
        if not row or row["version"] != data["assertion_version"] or row["is_public"] or row["valid_until"] or row["value"] != data["value"]:
            raise ConsentError(409, "fact changed; request a new review")
    nonce = secrets.token_urlsafe(32)
    binding = {"uid": str(uid), "proposal_id": proposal_id, "hash": data["content_hash"],
               "version": data["version"], "action": data["action"]}
    await redis.set(f"plugin:preview:{hashlib.sha256(nonce.encode()).hexdigest()}",
                    json.dumps(binding), ex=PREVIEW_TTL)
    result = {key: data[key] for key in ("action", "text", "expires_at", "version")}
    result["expires_at"] = min(datetime.fromisoformat(data["expires_at"]),
                               datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_TTL)).isoformat()
    result["nonce"] = nonce
    if data.get("public_text") is not None:
        result["public_text"] = data["public_text"]
    return result


async def decide(pool, redis, uid: str, proposal_id: str, nonce: str, decision: str) -> dict:
    if decision not in ("approve", "reject") or not nonce or len(nonce) > 128:
        raise ConsentError(422, "invalid decision")
    try:
        uuid.UUID(proposal_id)
    except ValueError:
        raise ConsentError(404, "proposal not found") from None
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    # A completed retry is allowed only with the very same nonce and decision.
    existing = await pool.fetchrow(
        "SELECT user_id, nonce_hash, decision, status FROM memory_plugin_consents WHERE proposal_id = $1::uuid",
        proposal_id)
    if existing:
        if str(existing["user_id"]) != str(uid):
            raise ConsentError(404, "proposal not found")
        if existing["nonce_hash"] == nonce_hash and existing["decision"] == decision:
            return {"status": existing["status"]}
        raise ConsentError(409, "proposal already decided")
    binding = _read(await redis.get(f"plugin:preview:{nonce_hash}"))
    data = _read(await redis.get(_key(proposal_id)))
    if not data or data["uid"] != str(uid):
        raise ConsentError(404, "proposal not found")
    if (not binding or binding != {"uid": str(uid), "proposal_id": proposal_id,
                                  "hash": data["content_hash"], "version": data["version"],
                                  "action": data["action"]}):
        raise ConsentError(409, "preview expired or changed")
    if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
        raise ConsentError(410, "proposal expired")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", proposal_id)
            existing = await conn.fetchrow(
                "SELECT user_id, nonce_hash, decision, status FROM memory_plugin_consents WHERE proposal_id = $1::uuid",
                proposal_id)
            if existing:
                if str(existing["user_id"]) == str(uid) and existing["nonce_hash"] == nonce_hash and existing["decision"] == decision:
                    return {"status": existing["status"]}
                raise ConsentError(409, "proposal already decided")
            if not await _connection_valid(conn, uid, data["connection_jti"]):
                raise ConsentError(403, "connection revoked")
            if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
                raise ConsentError(410, "proposal expired")
            status = "rejected" if decision == "reject" else ("saved_privately" if data["action"] == "save_memory" else "sync_pending")
            assertion = None
            if decision == "approve" and data["action"] == "publish_card_fact":
                assertion = await conn.fetchrow(
                    """SELECT a.id, a.version, a.predicate, a.object_entity_id, a.is_public,
                              a.valid_until, e.canonical_name AS value
                         FROM assertions a JOIN entities e ON e.id = a.object_entity_id
                        WHERE a.id = $1::uuid AND a.user_id = $2::uuid FOR UPDATE OF a""",
                    data["assertion_id"], uid)
                if not assertion or assertion["version"] != data["assertion_version"] or assertion["is_public"] or assertion["valid_until"] or assertion["value"] != data["value"]:
                    raise ConsentError(409, "fact changed; request a new review")
            consent_id = await conn.fetchval(
                """INSERT INTO memory_plugin_consents
                   (proposal_id, user_id, source_connection_id, source_client_id, action,
                    content_hash, version, decision, status, nonce_hash, expires_at)
                   VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11::timestamptz) RETURNING id""",
                proposal_id, uid, data["connection_jti"], data["source_client_id"], data["action"],
                data["content_hash"], data["version"], decision, status, nonce_hash,
                datetime.fromisoformat(data["expires_at"]))
            if decision == "approve" and data["action"] == "save_memory":
                subject = await conn.fetchval(
                    "INSERT INTO memory_plugin_facts (user_id, text, consent_id) VALUES ($1::uuid,$2,$3) RETURNING id",
                    uid, data["text"], consent_id)
            elif decision == "approve":
                if assertion["predicate"] == data["predicate"]:
                    subject = assertion["id"]
                    await conn.execute(
                        """UPDATE assertions SET is_public = true, approved_at = now(),
                                  version = version + 1 WHERE id = $1""", subject)
                else:
                    duplicate = await conn.fetchval(
                        """SELECT id FROM assertions WHERE user_id = $1::uuid AND predicate = $2
                             AND object_entity_id = $3 AND valid_until IS NULL AND is_public = true
                             LIMIT 1 FOR UPDATE""", uid, data["predicate"], assertion["object_entity_id"])
                    if duplicate:
                        raise ConsentError(409, "public fact already exists")
                    subject = await conn.fetchval(
                        """INSERT INTO assertions
                           (user_id, predicate, object_entity_id, confidence, source_system,
                            source, is_public, approved_at, decay_fn)
                           VALUES ($1::uuid,$2,$3,0.97,'user_confirmed','declared',true,now(),$4)
                           RETURNING id""", uid, data["predicate"], assertion["object_entity_id"],
                        decay_fn_for(data["predicate"]))
                publication_id = await conn.fetchval(
                    """INSERT INTO memory_plugin_publications
                       (user_id, predicate, value, public_text, assertion_id, consent_id)
                       VALUES ($1::uuid,$2,$3,$4,$5,$6) RETURNING id""",
                    uid, data["predicate"], data["value"], data["public_text"], subject, consent_id)
                await conn.execute("INSERT INTO memory_plugin_outbox (publication_id) VALUES ($1)", publication_id)
            else:
                subject = None
            if subject:
                await conn.execute("UPDATE memory_plugin_consents SET subject_id = $2 WHERE id = $1", consent_id, subject)
    # Removing Redis data is best-effort. A committed DB decision always wins on retry.
    try:
        await redis.delete(_key(proposal_id))
        await redis.srem(f"plugin:pending:{uid}", proposal_id)
    except Exception:
        pass
    return {"status": status}


_RECALL_STOPWORDS = frozenset("""
    about all also and any are but can could did does for from has have how into just
    know like may more not now off one only other our out should some than that the
    their them then there these they this those too was were what when where which who
    whom why will with would you your
    current else remember remembered remembers recall tell show zynd
""".split())
_MAX_RECALL_TERMS = 8


def recall_terms(query: str) -> list[str]:
    """Search words from a natural-language question; falls back to the whole phrase.

    ChatGPT sends phrases like "what else am I building", which never appear verbatim
    in a saved fact, so recall matches on the meaningful words instead.
    """
    words = re.findall(r"\w+", query.lower())
    terms = [w for w in dict.fromkeys(words) if len(w) >= 3 and w not in _RECALL_STOPWORDS]
    return terms[:_MAX_RECALL_TERMS] or [query.strip().lower()[:100]]


def _like_pattern(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def recall_facts(pool, uid: str, query: str, limit: int = 5) -> list[dict]:
    """Read exact approved private facts only; proposals never enter retrieval.

    A fact matches when it contains any search word; facts matching more words rank first.
    """
    if not query or not query.strip():
        return []
    patterns = [_like_pattern(term) for term in recall_terms(query[:200])]
    rows = await pool.fetch(
        """SELECT facts.text FROM (
               SELECT text, created_at AS occurred_at FROM memory_plugin_facts WHERE user_id = $1::uuid
               UNION ALL
               SELECT e.canonical_name AS text, a.extracted_at AS occurred_at
                 FROM assertions a JOIN entities e ON e.id = a.object_entity_id
                WHERE a.user_id = $1::uuid AND a.valid_until IS NULL
             ) facts
             CROSS JOIN LATERAL (
               SELECT count(*) AS hits FROM unnest($2::text[]) AS p
                WHERE facts.text ILIKE p ESCAPE '\\'
             ) m
            WHERE m.hits > 0
            ORDER BY m.hits DESC, facts.occurred_at DESC LIMIT $3""",
        uid, patterns, min(max(limit, 1), 10))
    return [{"text": row["text"]} for row in rows]


async def process_outbox(pool, *, limit: int = 20) -> int:
    """Retry committed public-card refreshes; mark synced only after HTTP confirmation."""
    import httpx

    if not settings.memory_service_token:
        return 0
    count = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT o.id, o.attempts, p.user_id, u.email FROM memory_plugin_outbox o
                 JOIN memory_plugin_publications p ON p.id = o.publication_id
                 JOIN users u ON u.id = p.user_id
                WHERE o.status = 'pending' AND o.attempts < 10
                ORDER BY o.created_at LIMIT $1""", limit)
        for row in rows:
            try:
                async with httpx.AsyncClient(timeout=8) as client:
                    response = await client.post(
                        settings.cards_api_url.rstrip("/") + "/internal/refresh-card-memory",
                        headers={"Authorization": "Bearer " + settings.memory_service_token},
                        json={"email": row["email"]})
                    response.raise_for_status()
                    snapshot = response.json().get("zynd_memory")
                    if not isinstance(snapshot, list):
                        raise ValueError("card snapshot missing")
                    publication = await conn.fetchrow(
                        """SELECT p.predicate, p.value FROM memory_plugin_publications p
                             JOIN memory_plugin_outbox o ON o.publication_id = p.id WHERE o.id = $1""", row["id"])
                    if not any(f.get("predicate") == publication["predicate"] and
                               f.get("object") == publication["value"] for f in snapshot):
                        raise ValueError("approved fact not visible in snapshot")
            except (httpx.HTTPError, ValueError):
                await conn.execute("UPDATE memory_plugin_outbox SET attempts = attempts + 1 WHERE id = $1", row["id"])
                continue
            await conn.execute(
                "UPDATE memory_plugin_outbox SET status = 'synced', processed_at = now(), attempts = attempts + 1 WHERE id = $1", row["id"])
            count += 1
    return count
