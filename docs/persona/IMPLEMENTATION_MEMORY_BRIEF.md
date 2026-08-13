# Implementation Plan — Consolidate user-info, retire the Google-Doc Brief

Status: **approved architecture**. Implement in phases. Each phase is
independently deployable; stop and verify at the end of each phase.

## Goal & boundary (do not re-litigate during implementation)

- **Conversation transcript stays in `agent-persona` (`chat_messages`).** Do NOT move it to the memory layer.
- **Memory layer stays a separate fact/recall/matching engine** (`/home/ubuntu/memory-layer`).
- **The Brief becomes a plain text field** on `persona_agents.brief_content` (column already exists, migration `db/migrations/0001_persona_fts/migration.sql`). Google Docs is retired for the brief.
- **Memory layer gains one new endpoint**: private fact "declare" (Phase 3).

Out of scope (do NOT touch): group briefs (`persona_groups.brief_doc_*`, `api/groups.py`, `agent/group_dispatch.py`). Group briefs remain Google Docs for now.

---

## Current state map (why we're changing this)

| Path | Endpoint / code | Store |
|---|---|---|
| Onboarding brief (Google Doc "My brief") | `webapp/.../onboarding/brief/page.tsx` → `POST /api/brief/create` (`api/brief.py`) | `auth.users.user_metadata.brief_doc` |
| Dashboard brief editor (Google Doc "Brief — {name}") | `BriefPanel.tsx` → `GET/PATCH /api/persona/{id}/brief`, `POST .../brief/init` (`api/persona.py`) | `persona_agents.brief_doc_id/url/revision_id` |
| Agent reads brief for prompt | `orchestrator._format_user_brief` → `_fetch_brief_doc_content` | reads `persona_agents.brief_doc_id` |
| MCP tools `read/append/replace/clear_my_brief` | `mcp/tools/brief.py` → `persona_manager` | `persona_agents.brief_doc_id` + Google Docs |
| Todo extraction from brief | `brief_watcher.py`, `api/todos.py` | `persona_agents.brief_doc_id` + Drive polling |
| Duplicate brief code in memory-layer | `memory-layer/app/services/persona_brief.py` | same `persona_agents.brief_doc_id` |

The `brief_content` TEXT column already exists and is written by
`save_brief_content`/`brief_watcher` as a *mirror* of the Google Doc body. We
promote it to the single source of truth.

---

## Phase 0 — Backfill `brief_content` (RUN FIRST, before deleting Google-Docs read paths)

Because Phase 1 removes the Google-Docs *read* path, you must copy any existing
brief text into `brief_content` while `read_document` still works.

1. Create `backend/scripts/backfill_brief_content.py` (sibling of existing `scripts/`). It must:

   - Load Supabase via `config.get_supabase()`.
   - For each `persona_agents` row where `brief_doc_id` is not null and `brief_content` is null/empty: call `mcp.tools.google.docs.read_document(user_id, document_id=brief_doc_id)`; on `success`, write `content` into `persona_agents.brief_content`.
   - For each `auth.users` row with `user_metadata.brief_doc.doc_id` set (via the Supabase admin API, same pattern as `api/brief.py:_read_user_metadata`): read that doc and write into `persona_agents.brief_content` for the matching `supabase_user_id` (join on `persona_agents.user_id`). Use the admin `GET /auth/v1/admin/users` listing (or iterate known users) — simplest: read `user_metadata.brief_doc` the same way `api/brief.py:my_brief` does, keyed off `persona_agents.user_id`.
   - Log every user migrated and every skip/failure; never raise.

   Minimal skeleton (fill in the Supabase admin-user listing to match how your
   env exposes it):

   ```python
   # backend/scripts/backfill_brief_content.py
   import config
   from mcp.tools.google.docs import read_document

   def main():
       sb = config.get_supabase()
       # 1. persona_agents.brief_doc_id -> brief_content
       rows = sb.table("persona_agents").select("user_id,brief_doc_id,brief_content").not_.is_("brief_doc_id", "null").execute()
       for r in rows.data or []:
           if (r.get("brief_content") or "").strip():
               continue
           try:
               got = read_document(user_id=r["user_id"], document_id=r["brief_doc_id"])
               if got.get("success") and (got.get("content") or "").strip():
                   sb.table("persona_agents").update({"brief_content": got["content"].strip()}).eq("user_id", r["user_id"]).execute()
                   print(f"[backfill] persona {r['user_id']}: migrated {len(got['content'])} chars")
               else:
                   print(f"[backfill] persona {r['user_id']}: read failed: {got.get('error')}")
           except Exception as e:
               print(f"[backfill] persona {r['user_id']}: ERROR {e}")
       # 2. user_metadata.brief_doc -> brief_content (only for users with a persona row)
       #    Use the admin API as in api/brief.py:_read_user_metadata to get user_metadata.brief_doc
       #    for each persona_agents.user_id, read the doc, and upsert brief_content if still empty.
       print("[backfill] done")

   if __name__ == "__main__":
       main()
   ```

2. Run it once in the prod backend env: `python -m scripts.backfill_brief_content`.
3. Verify: `SELECT count(*) FROM persona_agents WHERE brief_content IS NOT NULL AND brief_content <> '';`

Do NOT null out `brief_doc_id` / `user_metadata.brief_doc` yet — keep them until
Phase 1 is deployed and verified (rollback path).

---

## Phase 1 — Backend: brief becomes `persona_agents.brief_content`

### 1a. `backend/agent/persona_manager.py`

**(i)** In `get_persona_status` (currently lines ~554–576), add one key to the
returned dict:

```python
        "brief_content": persona.get("brief_content"),
```

**(ii)** Replace `get_brief` (lines ~670–708) with:

```python
def get_brief(user_id: str) -> dict:
    """Return the persona's brief text (single source of truth: persona_agents.brief_content).

    The brief is now a plain text field, not a Google Doc. `exists` is True
    whenever the persona is deployed (the field always exists; it may be empty).
    """
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona.")

    content = (persona.get("brief_content") or "").strip()
    return {
        "exists": True,
        "content": content,
        "fallback_description": persona.get("description") or "",
    }
```

**(iii)** Replace `save_brief_content` (lines ~710–732) with:

```python
def save_brief_content(user_id: str, content: str) -> dict:
    """Store the persona's brief body as plain text on persona_agents.brief_content."""
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona.")

    sb = _get_supabase()
    sb.table("persona_agents").update({
        "brief_content": content or None,
    }).eq("user_id", user_id).execute()

    logger.info(f"[persona] saved brief for {user_id} ({len(content or '')} chars)")
    return {"success": True, "content": content}
```

**(iv)** Replace `init_brief_doc` (lines ~621–668) with a no-op ensure (keeps the
name so callers don't churn; the brief needs no creation step anymore):

```python
def init_brief_doc(user_id: str) -> dict:
    """Legacy shim. The brief is a text field now — nothing to create.

    Returns the current brief state so existing callers (the old /brief/init
    endpoint, MCP _ensure_brief_doc) behave as a read instead of a Google call.
    """
    persona = get_persona_status(user_id)
    if not persona.get("deployed"):
        raise ValueError("No active persona — create a persona before using the brief.")
    return {
        "doc_id": None,
        "url": "",
        "created": False,
        "exists": True,
        "content": (persona.get("brief_content") or "").strip(),
    }
```

Remove the `from mcp.tools.google.docs import ...` inside these functions (they no
longer touch Google).

### 1b. `backend/agent/orchestrator.py`

**(i)** Delete `_BRIEF_DOC_CACHE`, `_BRIEF_DOC_CACHE_TTL_SECONDS`, and
`_fetch_brief_doc_content` (lines ~1671–1695).

**(ii)** Replace `_format_user_brief` (lines ~1697–1764) — change only the source
of the description text; keep the `redact_profile` / `redact_brief` logic and the
profile-field rendering intact:

```python
def _format_user_brief(
    persona: dict,
    redact_profile: bool = False,
    redact_brief: bool = False,
    user_id: str | None = None,
) -> str:
    # Source priority: brief_content (plain text) -> persona.description.
    # `user_id` is kept for call-signature compatibility; it is unused now that
    # the brief is a field rather than a Google Doc fetch.
    brief_text = None
    if not redact_brief:
        brief_text = (persona.get("brief_content") or "").strip()

    desc = (brief_text or persona.get("description") or "").strip()
    profile = persona.get("profile") or {}

    lines = []
    if desc:
        lines.append(desc)

    if redact_profile:
        return "\n".join(lines) if lines else "(no profile details set yet)"

    # ... (existing profile_lines block unchanged: title/organization/location/
    #      interests/socials) ...

    return "\n".join(lines) if lines else "(no profile details set yet)"
```

(The `_build_system_prompt` caller already passes `persona = get_persona_status(...)`
which now includes `brief_content`, so no change there.)

### 1c. `backend/api/persona.py`

**(i)** Remove `init_brief_doc` from the import list (lines ~19–28) if it's no longer
referenced by an endpoint; keep `get_brief`, `save_brief_content`, `get_persona_status`.

**(ii)** Replace the brief endpoints (lines ~373–440):

```python
# ── Brief (plain text) ─────────────────────────────────────────────
@router.get("/{user_id}/brief")
async def read_brief(user_id: str):
    """Return the persona's brief text (single field, no Google Docs)."""
    try:
        return get_brief(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class BriefSave(BaseModel):
    content: str


@router.patch("/{user_id}/brief")
async def save_brief(user_id: str, req: BriefSave):
    """Store the persona's brief body as plain text."""
    try:
        result = save_brief_content(user_id, req.content)
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error") or "Couldn't save the brief.")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Delete the `POST /{user_id}/brief/init` endpoint and `_classify_google_error`
(no longer used).

### 1d. Delete `backend/api/brief.py` and unregister it

- Delete the file `backend/api/brief.py`.
- In `backend/main.py`: remove `from api.brief import router as brief_router` (line 26) and `app.include_router(brief_router, prefix="/api/brief", tags=["Brief"])` (line 132).

### 1e. `backend/mcp/tools/brief.py` (the chat tools the LLM calls)

These are the durable-fact write tools. Point them at `brief_content`:

**(i)** `_ensure_brief_doc` (lines ~32–101) — simplify to a persona check (no Google):

```python
def _ensure_brief_doc(user_id: str) -> dict:
    """Return {"ok": True} if the user has a deployed persona, else a no_persona error."""
    from agent import persona_manager
    try:
        persona = persona_manager.get_persona_status(user_id)
        if persona.get("deployed"):
            return {"ok": True}
        return {
            "ok": False,
            "code": "no_persona",
            "message": "You haven't deployed a persona yet. Open the Zynd dashboard and finish onboarding.",
        }
    except Exception as e:
        logger.warning(f"[brief] ensure failed: {e}")
        return {"ok": False, "code": "no_persona", "message": "Couldn't confirm your persona is ready. Try again."}
```

**(ii)** `read_my_brief` (lines ~104–149) — return the field content:

```python
def read_my_brief(user_id: str) -> dict:
    from agent import persona_manager
    try:
        result = persona_manager.get_brief(user_id)
    except ValueError as e:
        return friendly_error("read your brief", e)
    except Exception as e:
        logger.exception(f"[brief] read_my_brief failed: {e}")
        return friendly_error("read your brief", e)

    return {
        "success": True,
        "exists": result.get("exists", True),
        "content": result.get("content") or "",
        "fallback_description": result.get("fallback_description") or "",
    }
```

**(iii)** `append_to_my_brief` (lines ~152–206) — append to the field:

```python
def append_to_my_brief(user_id: str, text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        return friendly_error_message(
            "add to your brief", "Nothing to append — `text` was empty.",
            hint="Tell me what you'd like me to add.",
        )
    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {"success": False, "error": ensured["message"], "code": ensured["code"]}

    from agent import persona_manager
    try:
        current = persona_manager.get_brief(user_id)
    except ValueError as e:
        return friendly_error("add to your brief", e)

    existing = current.get("content") or ""
    body = text if text.endswith("\n") else text + "\n"
    new_content = (existing.rstrip() + "\n\n" + body.rstrip() + "\n") if existing else body
    result = persona_manager.save_brief_content(user_id, new_content)
    if not result.get("success"):
        return friendly_error_message("add to your brief", result.get("error") or "Append failed.")
    return {"success": True, "appended": text.strip()}
```

**(iv)** `replace_my_brief` (lines ~209–249) — drop the `doc_id`/`url` in the return;
keep calling `persona_manager.save_brief_content`. Remove the `get_persona_status`
lookup for `brief_doc_url`:

```python
def replace_my_brief(user_id: str, content: str) -> dict:
    if content is None:
        content = ""
    ensured = _ensure_brief_doc(user_id)
    if not ensured.get("ok"):
        return {"success": False, "error": ensured["message"], "code": ensured["code"]}

    from agent import persona_manager
    try:
        result = persona_manager.save_brief_content(user_id, content)
    except ValueError as e:
        return friendly_error("replace your brief", e)
    except Exception as e:
        logger.exception(f"[brief] replace_my_brief failed: {e}")
        return friendly_error("replace your brief", e)

    if not result.get("success"):
        return friendly_error_message("replace your brief", result.get("error") or "Replace failed.")
    return {"success": True, "content": content}
```

`clear_my_brief` and `add_todo` are unchanged.

### 1f. `backend/agent/brief_watcher.py` (todo extraction from the brief)

Rewire `_poll_all` / `_poll_one` to read `brief_content` instead of Drive.

Replace the class body polling (lines ~218–293) with a hash-based sweep:

```python
    def _poll_all(self):
        sb = self._supabase()
        rows = (
            sb.table("persona_agents")
            .select("user_id,brief_content")
            .eq("active", True)
            .not_.is_("brief_content", "null")
            .execute()
        )
        for row in rows.data or []:
            try:
                self._poll_one(sb, row)
            except Exception as e:
                logger.warning(f"[brief_watcher] Poll failed for user {row.get('user_id')}: {e}")

    def _poll_one(self, sb, row: dict):
        user_id = row["user_id"]
        content = (row.get("brief_content") or "").strip()
        if not content:
            return
        digest = hashlib.sha256(content.encode()).hexdigest()
        if self._last_seen.get(user_id) == digest:
            return  # unchanged since last extraction

        llm_titles = extract_todo_titles_llm(content)
        if llm_titles is None:
            titles = extract_todo_titles(content)
            extractor = "regex_fallback"
        else:
            titles = llm_titles
            extractor = "llm"
        if titles:
            self._upsert_todos(sb, user_id, titles)
        self._last_seen[user_id] = digest
        logger.info(f"[brief_watcher] {user_id}: {len(titles)} todos via {extractor}")
```

Add `import hashlib` and an instance dict `self._last_seen: dict[str, str] = {}` in
`__init__`. Keep `extract_todo_titles`, `extract_todo_titles_llm`, `_upsert_todos`
unchanged. Remove the `brief_doc_revision_id` write and the Google `build`/`get_google_creds` imports.

### 1g. `backend/api/todos.py` — `/extract` endpoint

Replace the doc-fetch block (lines ~86–103) with a field read:

```python
        persona = get_persona_status(user_id)
        if not persona.get("deployed"):
            raise HTTPException(status_code=404, detail="No active persona.")
        content = (persona.get("brief_content") or "").strip()
        if not content:
            raise HTTPException(
                status_code=400,
                detail="Your brief is empty — add some text first.",
            )

        titles = extract_todo_titles_llm(content)
        extractor = "llm"
        if titles is None:
            titles = extract_todo_titles(content)
            extractor = "regex_fallback"
```

Remove the `read_document` import in that function.

### Phase 1 verification

```bash
cd /home/ubuntu/agent-persona/backend
python -m pytest tests/test_brief_tools.py -q        # after updating tests (Phase 6)
# Manual: GET /api/persona/{id}/brief returns {exists, content, fallback_description}
#         PATCH /api/persona/{id}/brief with {content} persists; GET reflects it
#         Chat "add to my brief: X" -> read_my_brief shows X; /api/brief/* now 404s
```

---

## Phase 2 — Frontend

### 2a. `webapp/src/components/BriefPanel.tsx`

- Remove the `exists`-gating branch (`if (!brief?.exists)`) and `handleCreate`, plus the `BriefState.doc_id/url/title/error` fields and the "Open in Google Docs ↗" link.
- `BriefState` becomes `{ content?: string; fallback_description?: string }`.
- `initialIsSynced` in `<SaveStatus>` becomes `!!brief.content && brief.content.length > 1`; change the label "Synced from Google Docs" (line 369) to "Saved".
- Update the empty-state copy: no mention of Google Docs ("Your brief is the long-form context your agent uses to represent you. Edit here any time.").
- Keep the `apiPatch('/api/persona/{id}/brief', { content })` save path unchanged.
- Remove the now-dead `friendlySaveError`/`summarizeRawGoogleError` Google-mapping (optional; harmless to keep).

### 2b. `webapp/src/app/onboarding/brief/page.tsx`

- Remove `postCreateBrief` and the `POST /api/brief/create` + Google OAuth redirect logic.
- Replace `handleCreate` with a no-op that just marks onboarding complete (no doc to create), or seed `brief_content` via `PATCH /api/persona/{id}/brief` with a starter template. Simplest: keep the screen as an informational step and make the button set `brief_created: true` then continue. Keep `handleSkip`.
- Remove the `created` view that links to Google Docs.

### 2c. `webapp/src/app/dashboard/settings/accounts/page.tsx`

- The "brief" connector (lines ~516–530 and the `handleConnect("brief")` branch) only triggered Google `docs,calendar` OAuth. Remove the "brief" connector card; keep `calendar` and `email` Google connectors. Remove `brief` from `ConnId` and the `googleSiblingsNote` self-type (`brief`), so brief is no longer listed as a Google-scope sibling.

### Phase 2 verification

```bash
cd /home/ubuntu/agent-persona/webapp
npm run build   # REQUIRED before restart (AGENTS.md)
```

Manual: Dashboard → "Your brief" loads an editable text box (no create step); save persists; onboarding brief step no longer calls `/api/brief/create`.

---

## Phase 3 — Memory layer: private fact "declare" endpoint (`/home/ubuntu/memory-layer`)

### 3a. `app/services/findability.py` — generalize declare for private memory

Add a predicate→entity-type map for private predicates and a `declare_private`
function (alongside the existing `declare`):

```python
# Private-memory declarable predicates -> entity family. Literal/enum predicates
# (has_age, is_seeking, open_to) are intentionally excluded — they need literal
# storage, not entity resolution.
PRIVATE_DECLARE_ENTITY_TYPE: dict[str, str] = {
    "is_building": "project_venture",
    "is_working_on": "project_venture",
    "is_creating": "artifact_creative",
    "wants_to_preserve": "concept_topic",
    "is_learning": "skill_domain",
    "has_expertise_in": "skill_domain",
    "has_skill": "skill_technical",
    "intends_to": "intent_project",
    "is_preparing_for": "intent_project",
    "fears": "concept_topic",
    "believes": "belief_opinion",
    "values": "belief_value",
    "recently_changed_stance_on": "belief_opinion",
    "has_aesthetic": "belief_opinion",
    "is_navigating": "concept_topic",
    "is_constrained_by": "concept_topic",
    "is_frustrated_by": "concept_topic",
    "has_been_wronged": "concept_topic",
    "is_transitioning": "concept_topic",
    "is_experiencing": "concept_topic",
    "is_processing": "concept_topic",
    "is_rediscovering": "concept_topic",
    "has_unsolved_problem": "concept_topic",
    "has_collaborator": "collaborator",
    "is_responsible_for": "project_assignment",
    "is_advocating_for": "concept_topic",
    "is_in_conflict_with": "adversary",
    "is_inspired_by": "influence",
    "is_located_in": "place_physical",
    "is_affiliated_with": "place_institutional",
    "has_language_context": "concept_topic",
    "is_motivated_by": "concept_topic",
}

PRIVATE_DECLARED_CONFIDENCE = 0.97


async def declare_private(pool: asyncpg.Pool, user_id: str, predicate: str, value: str) -> None:
    """User explicitly adds a PRIVATE memory fact (never matched/public)."""
    if predicate not in PRIVATE_DECLARE_ENTITY_TYPE:
        raise ValueError(f"{predicate!r} is not declarable as private memory")
    value = (value or "").strip()
    if not value:
        raise ValueError("value is required")

    entity_type = PRIVATE_DECLARE_ENTITY_TYPE[predicate]
    async with pool.acquire() as conn:
        async with conn.transaction():
            entity_id = await resolve_entity(conn, user_id, value, entity_type)
            existing = await conn.fetchrow(
                """SELECT id FROM assertions WHERE user_id = $1 AND predicate = $2
                     AND object_entity_id = $3 AND valid_until IS NULL LIMIT 1""",
                user_id, predicate, entity_id)
            if existing:
                await conn.execute(
                    """UPDATE assertions SET source = 'declared',
                          confidence = $2, version = version + 1 WHERE id = $1""",
                    existing["id"], PRIVATE_DECLARED_CONFIDENCE)
            else:
                await conn.execute(
                    """INSERT INTO assertions
                         (user_id, predicate, object_entity_id, confidence, source_system,
                          source, is_public, decay_fn)
                       VALUES ($1, $2, $3, $4, 'user_confirmed', 'declared', false, $5)""",
                    user_id, predicate, entity_id, PRIVATE_DECLARED_CONFIDENCE,
                    decay_fn_for(predicate))
    # Private memory is not matched, so no recompute_user_embeddings is needed.
```

Note: `decay_fn_for` is already imported in this module; `resolve_entity` too.

### 3b. `app/main.py` — add the route

```python
@app.post("/me/memory/declare")
async def declare_memory_fact(req: DeclareRequest, user_id: str = Depends(current_user)) -> dict:
    """User explicitly adds a PRIVATE memory fact (stays private, never matched)."""
    from app.services.findability import declare_private
    try:
        await declare_private(get_pool(), user_id, req.predicate, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "declared", "predicate": req.predicate, "value": req.value}
```

`DeclareRequest` already exists in `app/models.py` and is imported in `main.py`.

### 3c. Delete `app/services/persona_brief.py` (duplicate brief code) — after confirming
nothing imports it (`grep -rn persona_brief app/`). It is a slim port of the
Google-Docs brief and is now dead.

### 3d. (Optional, Phase 5) `app/services/persona_ingest.py` — no change needed; it
already ingests the persona profile into memory. If you also want the brief prose as
facts, add a `brief_seeded` ingest in Phase 5, not here.

### Phase 3 verification (memory-layer repo)

```bash
cd /home/ubuntu/memory-layer
uv run pytest -q tests/test_findability.py tests/test_pipeline.py
# Manual: POST /me/memory/declare {"predicate":"is_working_on","value":"Acme launch"}
#         then GET /me/graph shows the new private fact with source=declared, is_public=false
```

---

## Phase 4 — `agent-persona` memory client: `declare_fact`

Add to `backend/agent/memory_client.py`:

```python
async def declare_fact(user_id: str, predicate: str, value: str) -> bool:
    """Write a user-authored PRIVATE memory fact directly (structured predicate/value).

    Distinct from ingest_turns (which runs async extraction) — this is an
    explicit, high-confidence declaration for the editable memory surface.
    """
    if not is_enabled():
        return False
    token = _make_jwt(user_id)
    try:
        async with _client() as client:
            resp = await client.post(
                "/me/memory/declare",
                json={"predicate": predicate, "value": value},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return True
    except Exception as exc:
        logger.debug("[memory] /me/memory/declare failed for %s: %s", user_id, exc)
        return False
```

Optionally expose an MCP tool `remember_this_structured(user_id, predicate, value)`
in `backend/mcp/tools/memory.py` for the LLM to write discrete private facts. Do NOT
change the existing free-text `remember_this` (ingest-based) — both are valid.

### Phase 4 verification

`python -m pytest tests/test_memory_fact_ref.py -q` (still green), plus a manual
`declare_fact` round-trip if the memory layer (Phase 3) is deployed.

---

## Phase 5 — Optional: seed brief prose into memory facts

In `backend/agent/persona_manager.py:save_brief_content`, after the DB write,
fire-and-forget an ingest so the brief's substance is recallable via `/context`:

```python
    # Best-effort: make the brief's substance semantically recallable in the
    # memory layer (narrative stays verbatim in the prompt).
    import asyncio
    from agent.memory_client import ingest_turns, is_enabled
    if is_enabled() and content and len(content.strip()) >= 40:
        async def _seed():
            await ingest_turns(
                user_id=user_id,
                turns=[{"role": "user", "content": content.strip()}],
                source_system="brief_seeded",
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_seed())
        else:
            asyncio.create_task(_seed())
```

(None of this blocks the save. `brief_seeded` mirrors the existing
`persona_seeded` tag in the memory layer.)

---

## Phase 6 — Tests

- `backend/tests/test_brief_tools.py` — update the monkeypatched `persona_manager`
  stubs to the new shapes: `get_brief` returns `{exists, content, fallback_description}`,
  `save_brief_content` returns `{success, content}`, `init_brief_doc` returns the shim dict.
  Remove `brief_doc_id` expectations. Keep `_ensure_brief_doc` no_persona / google_unavailable
  tests but drop the google path (now `no_persona` only).
- `backend/tests/test_action_summary.py` already patches `ingest_conversation` — unaffected.
- Add a test for the new `_format_user_brief` reading `brief_content` (assert description
  from `brief_content` wins over `persona.description`, and empty `brief_content` falls back).

### Phase 6 verification

```bash
cd /home/ubuntu/agent-persona/backend && python -m pytest -q
```

---

## Deploy order (prod + dev channels per AGENTS.md)

1. Run Phase 0 backfill in **prod** env first (before any code deploy that removes read_document).
2. Deploy code changes: commit + push `main` → dev copy `git pull`, `pip install -r requirements.txt` (only if changed), **`npm run build`** (always after webapp changes), `pm2 restart api-dev web-dev` → smoke test dev.
3. Deploy memory-layer (Phase 3) to its own service (`api.zynd.ai`) independently.
4. Prod copy: `git pull`, `npm run build`, `pm2 restart api web`.
5. After prod verified, run cleanup (optional): null `brief_doc_id/url/revision_id` on `persona_agents` and clear `user_metadata.brief_doc`, and drop the now-unused columns in a later migration.

## Rollback

- `persona_agents.brief_doc_id` / `brief_doc_url` columns are left in place through
  Phases 1–5, so reverting to the Google-Docs path is a code revert only. Only the
  final cleanup step removes them.
