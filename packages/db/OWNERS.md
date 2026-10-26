# Who owns what in the shared aafo database

Ownership follows the Postgres schema, and each schema has its own migration
history (see README.md): `public` = persona, `cards` = cards,
`identity` = shared. A change needs a review from the owner, **and** from
every service listed as a reader.

## Tables

| Table | Owner | Also read by |
|---|---|---|
| `persona_agents` | persona | **memory** (`services/memory/app/tools/zynd_network.py`: `agent_id, name, description, active, updated_at`), persona-web (via RLS subqueries) |
| `dm_threads`, `dm_messages`, `dm_thread_reads`, `a2a_tasks`, `agent_tasks`, `pending_approvals` | persona | persona-web (signed-in reads + realtime); read cursors are persona-api only |
| `outbound_callbacks`, `callback_results` | persona | persona-web (realtime) |
| `persona_groups`, `persona_group_members`, `persona_group_messages`, `persona_group_reads`, `persona_group_invitations`, `persona_group_constraints`, `persona_group_audit_events` | persona | persona-web (realtime on messages/invitations); read cursors are persona-api only |
| `api_tokens`, `oauth_pending_state`, `telegram_links`, `telegram_chat_history` | persona | — |
| `linkedin_profiles`, `twitter_profiles`, `github_profiles` | persona | — |
| `enriched_contacts`, `enriched_companies`, `suggested_contacts`, `suggested_contact_runs` | persona | — |
| `chat_messages`, `brief_todos`, `published_pages` | persona | — |
| `cards.agent_profile_cards`, `cards.x_accounts`, `cards.x_mentions`, `cards.x_conversations`, `cards.keyword_posts`, `cards.takedown_requests` | cards | — (service role only; cards-web goes through cards-api) |
| `cards.visitor_preferences`, `cards.profile_visits` | cards | cards-api only; consent-bound owner reads |
| `cards.connections`, `cards.dm_threads`, `cards.dm_messages`, `cards.dm_read_state`, `cards.groups`, `cards.group_members`, `cards.group_read_state`, `cards.group_invitations`, `cards.group_messages` | cards | cards-api only; Cards web/MCP use Cards HTTP. Read cursors are service-role only |
| `cards.group_memory`, `cards.group_memory_state`, `cards.group_message_memory` | cards | cards-api only; rolling group summary/facts, never raw messages |
| `cards.group_agent_jobs`, `cards.group_agent_preferences` | cards | cards-api only; durable mention queue and per-user agent opt-out |
| `identity.*` (empty today; Zynd Account tables in Stage 2) | shared | persona, cards |
| `persona_intro_requests`, `persona_intro_rules`, `persona_intro_audit` | persona | cards-api via Persona HTTP; persona-web (requests only, participant RLS) |
| `cards.intro_requests` | cards | cards-api; minimal Persona status projection and activity events |

## Functions, triggers, publication

| Object | Owner | Last defined in | Called by |
|---|---|---|---|
| `is_persona_group_member(uuid)`, `is_persona_group_manager(uuid)` | persona | persona 0000 | RLS policies on group tables |
| `persona_agents_search_vector_update()` + trigger `persona_agents_search_vector_trigger` | persona | persona 0000 | keeps `persona_agents.search_vector` current |
| `search_personas_fts(text, int)` | persona | persona 0000 | persona-api, **memory** |
| `cards.skill_names(jsonb)` | cards | cards 0000 | generated column `agent_profile_cards.search_tsv` |
| `cards.match_cards(vector, int, bool)`, `cards.search_cards_fts(text, int, bool)` | cards | cards 0022 (live definitions recorded) | cards-api (`services/search.py`) |
| `cards.filter_cards(jsonb, text[], jsonb, vector, bool, int)` | cards | cards 0030 | cards-api (`services/search.py`); superset pre-filter for role/place/skill searches, cards-api applies the exact rules |
| `cards.s10_set_visitor_privacy`, `cards.s10_record_named_visit` | cards | cards 0016 | cards-api only |
| `cards.s10_named_visitors` | cards | cards 0018 | cards-api only; consent-bound public profile links |
| `cards.network_create_group`, `cards.network_respond_invitation` | cards | cards 0020 | cards-api only; transactional membership checks |
| `cards.network_inbox`, `cards.network_dm_messages`, `cards.network_send_dm`, `cards.network_group_messages`, `cards.network_send_group_message`, `cards.network_mark_read`, `cards.network_group_members`, `cards.network_card_payload` | cards | cards 0023 | cards-api only; one round-trip inbox/message operations |
| `cards.network_can_subscribe` | cards | cards 0023 | Supabase Realtime RLS only; boolean authorization for `cards:*` private topics |
| `cards.network_send_agent_group_message` | cards | cards 0028 (0026 before; reply limit 4000 -> 8000) | cards-api only; writes the Card assistant's reply, `client_id` = job id |
| `cards.network_enqueue_group_agent_replies`, `cards.network_claim_group_agent_job`, `cards.network_finish_group_agent_job` | cards | cards 0026 (claim/finish: 0027) | cards-api only; durable mention jobs |
| `cards.network_group_memory_search`, `cards.network_group_memory_list`, `cards.network_group_memory_remember`, `cards.network_group_memory_add_fact`, `cards.network_group_memory_set_summary`, `cards.network_groups_needing_summary` | cards | cards 0026 | cards-api only; group-scoped summary/facts and semantic search |
| group memory/agent job triggers in `cards` | cards | cards 0026 | memory saved, message remembered, agent typing broadcasts |
| `realtime.messages` policy `cards network can receive broadcasts` | cards | cards 0023 | Supabase Realtime private `cards:*` topics; review alongside any other `realtime.messages` policy |
| message/connection/invitation/member triggers in `cards` | cards | cards 0023 | sequence assignment, inbox summaries, read-state init, and Realtime Broadcast |
| `cards.v_funnel_daily`, `cards.v_funnel_daily_totals`, `cards.purge_card_events` | cards | cards 0022 | Cards analytics/retention; deployed daily-view contract preserved |
| publication `supabase_realtime` (9 persona tables) | persona | persona 0000 | persona-web realtime |
| extension `vector` (schema `extensions`) | cards | cards 0000 | — |
| schemas `cards`, `identity` + their grants | cards / shared | cards 0000, identity 0000 | — |
