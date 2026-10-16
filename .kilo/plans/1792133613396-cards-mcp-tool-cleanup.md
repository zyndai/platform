# Cards MCP Tool Cleanup

## Goal and Decisions

Reduce the shared memory MCP to current Cards functionality. User approved keeping all six optional discovery/hosting tools, deleting unused external-integration code, preserving Persona implementations while deregistering their tools, and deleting both nonfunctional tools. This plan changes the MCP catalog, not Cards' HTTP APIs or Persona's own local registry.

Source inventory: 77 authenticated tools with S09 enabled, plus 4 tools on the separately flagged public Cards MCP. Target: **17 authenticated tools and 3 public tools**. Preserve existing feature-flag behavior; when S09 is off the five retained owner tools remain absent.

### Keep Authenticated (17)

- Memory/account: `get_my_context`, `report_user_info`, `confirm_fact_tool`, `forget_fact_tool`, `export_my_context`, `disconnect`.
- Cards owner: `list_pending_facts`, `approve_fact`, `dismiss_fact`, `set_looking_for`, `list_intros`.
- Optional, explicitly retained: `find_people`, `find_similar_users`, `search_linkedin_profiles`, `find_linkedin_people_for_me`, `publish_page`, `list_my_pages`.

### Deregister Persona, Preserve Code (24)

- Social: `set_social_links`, `connect_with`, `send_persona_message`, `my_connections`, `book_meeting`.
- Scheduling: `propose_meeting`, `respond_to_meeting`, `list_pending_meetings`.
- Network: `search_zynd_network`, `search_zynd_personas`, `get_persona_profile`, `list_my_connections`, `request_connection`, `check_connection_status`, `message_zynd_agent`, `call_zynd_agent`, `read_agent_channel`.
- Services: `search_zynd_services`, `get_zynd_service_card`, `call_zynd_service`.
- Brief/tasks: `append_to_my_brief`, `replace_my_brief`, `clear_my_brief`, `add_todo`.

Preserve these wrapper functions as unregistered code, their implementations and direct tests. Remove only MCP registration; do not delete Persona features or introduce a new enabling flag. Restore registration explicitly when Persona becomes part of the shared MCP offering.

### Remove External Integrations (35)

- Calendar: `create_calendar_event`, `list_calendar_events`, `delete_calendar_event`.
- Docs: `create_google_doc`, `append_to_google_doc`, `read_google_doc`, `list_google_docs`, `search_google_docs`.
- Drive: `create_google_drive_folder`, `list_google_drive_files`, `move_google_drive_file`, `list_google_drive_folder_contents`.
- Gmail: `search_gmail_emails`, `get_gmail_email_details`, `send_gmail_email`, `list_recent_gmail_threads`.
- Sheets: `create_google_sheet`, `append_to_google_sheet`, `read_google_sheet_values`, `search_google_spreadsheets`.
- X: `post_tweet`, `read_timeline`, `send_twitter_dm`, `read_twitter_dms`.
- LinkedIn account: `post_to_linkedin`, `send_linkedin_dm`, `read_linkedin_dms`.
- Notion: `search_notion`, `get_notion_database`, `query_notion_database`, `create_notion_page`, `update_notion_page`, `get_notion_page_content`, `create_notion_database`, `append_notion_blocks`.

Delete authenticated `update_headline`, which only returns `edit_on_card`. Delete public `request_intro`, which always returns disabled. Keep public `search_people`, `get_card`, `ask_card`, public resources, and current rollout flags.

## Implementation

1. Read root instructions and instructions in each affected directory; inspect working-tree changes. Run the memory baseline: `uv run pytest -q -m "not integration"` in `services/memory`. Record actual failures; do not assume the documented baseline applies unchanged.
2. Update `services/memory/app/mcp_http.py`: remove the 35 external wrappers; remove registration decorators from the 24 Persona wrappers, retaining their code and imports required by those functions. Preserve the 12 retained non-owner registrations. Delete genuinely unused imports/helpers only after checking remaining callers. Do not accidentally remove `_suid` while preserved Persona wrappers still reference it.
3. Remove `update_headline` registration/function from `app/mcp_owner.py`; remove its scope entry, selector expectation and instructional references in `app/services/mcp_scopes.py` and `app/services/mcp_gate.py`. Preserve existing grants and all checks for retained tools, including explicit fact-publication confirmation. Do not broaden access to retained legacy-only tools or redesign OAuth. `people:message` continues to grant `find_people`; deregistered tools remain unavailable regardless of scope.
4. Delete unused integration implementation modules after checking Python, scripts, tests and dynamic/string references. Initial candidates: `app/tools/google/drive.py`, `gmail.py`, `sheets.py`, `app/tools/twitter.py`, `linkedin.py`, `notion.py`. Update/retire only tests for deleted implementations in `tests/test_oauth_integrations.py`, retaining coverage of shared code. Preserve `google/calendar.py` and `google/common.py` used by `app/services/meetings.py`; preserve `google/docs.py` used by `scripts/migrate_brief_gdoc_to_supabase.py`. Preserve `app/services/linkedin_search.py` for retained LinkedIn discovery. Do not remove OAuth routes, token storage, provider credentials, schema or dependencies merely because their MCP wrappers disappear.
5. Preserve `app/tools/brief.py`: `app/services/self_context.py` uses its reader for `get_my_context`. Preserve card-status/introduction helpers, Persona scheduling/social/network/services implementations and their dependencies. Check preserved functions still import and execute through existing non-MCP entry points.
6. Remove only the disabled public intro wrapper/stub in `app/cards_public_mcp.py`. Update its discovery prompt so it no longer instructs a call to `request_intro`; retain the implemented public search/read/chat paths, event behavior, caching and rate limits. Do not delete private introduction listing or Cards' HTTP introduction functionality.
7. Update active server instructions, memory skills (`skills/zynd-context/SKILL.md`, `skills/zynd-memory/SKILL.md`), packaged plugin card skill (`plugins/zynd/skills/zynd-card/SKILL.md`), tool inventories and `mcp-test-prompts.txt`. Document the new catalog and the disabled tools' removal in relevant existing docs, including the public MCP statement in `docs/S12_INTROS.md`. Preserve editor guidance for headlines without advertising a callable headline tool. Do not rewrite historical plans wholesale.
8. Update `tests/test_mcp_tools.py`, `test_s09.py`, `test_cards_public_mcp.py` and affected instruction/plugin tests. Assert exact tool-name sets, not counts alone. Test list and direct-call behavior with legacy `user` tokens and scoped tokens; a cached client calling a removed name must receive the standard unknown-tool response. Test S09 on/off and public endpoint on/off separately. Keep retained tools' existing scopes, confirmation, context composition, discovery/hosting and private/public data boundaries covered.

## Data Flow and Compatibility

Authenticated clients still enter `/mcp` through existing authentication and scope middleware. Registration becomes the upper bound for both discovery and execution, so legacy full-access tokens cannot reach removed tools. Cards editor fact review continues through its HTTP proxy to memory service endpoints. Persona's orchestrator continues using its own local registry and HTTP memory client.

This intentionally removes existing capabilities from full-access connected assistants. No token revocation, grant migration, database migration, credential deletion or replacement-tool aliases are required. Clients may need to reconnect/refresh their cached catalog. Update both MCP discovery/listing transports supported by the existing tests and their initialization instructions consistently.

## Validation and Rollout

- Run focused registration, scope/transport, public MCP and affected integration/plugin tests, then rerun the full memory non-integration suite against the baseline. Keep tests for preserved shared Calendar/Docs behavior.
- Run Cards API connector proxy tests (`tests/test_mcp_connector.py`) to verify HTTP fact-review contracts remain intact. Use the existing local environment; do not access production databases or require live third-party credentials.
- Check no active instructions/prompts request deleted or deregistered tools. Verify retained LinkedIn discovery does not import deleted LinkedIn account modules.
- Report new failures separately from baseline/environment failures. Report exact final names, deleted files, preserved dependencies and the breaking change for full-access clients.
- Obtain human approval before deployment. Any scope-check file edits must be called out explicitly for review as auth-adjacent; preserve current authorization behavior. No production writes, deployment, commit or push are part of this plan without explicit authorization.
- Rollback is a reviewed code revert restoring registrations and deleted integration files; no data rollback is needed. Do not enable the public endpoint as part of this work.

## Usage Reporting Limit

The inventory and recommendation are based on product relevance, not measured popularity. `app/services/mcp_gate.py` logs authenticated calls best-effort into `mcp_tool_calls`; no counts were available in the checkout. Actual rankings require a separately authorized read-only report from the deployed memory database (for example the last 30 days: calls, distinct users, latest call and exception rate, joined to the complete catalog to include zero-call tools). Logging can drop writes and can mark returned error payloads as successful. Public Cards events are a different, incomplete signal. Do not claim removed tools were unused or that retained tools were most used. Production analytics access and new telemetry are out of scope for this cleanup.
