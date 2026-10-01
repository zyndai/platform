# Who owns what in the shared aafo database

Ownership follows the Postgres schema, and each schema has its own migration
history (see README.md): `public` = persona, `cards` = cards,
`identity` = shared. A change needs a review from the owner, **and** from
every service listed as a reader.

## Tables

| Table | Owner | Also read by |
|---|---|---|
| `persona_agents` | persona | **memory** (`services/memory/app/tools/zynd_network.py`: `agent_id, name, description, active, updated_at`), persona-web (via RLS subqueries) |
| `dm_threads`, `dm_messages`, `a2a_tasks`, `agent_tasks`, `pending_approvals` | persona | persona-web (signed-in reads + realtime) |
| `outbound_callbacks`, `callback_results` | persona | persona-web (realtime) |
| `persona_groups`, `persona_group_members`, `persona_group_messages`, `persona_group_invitations`, `persona_group_constraints`, `persona_group_audit_events` | persona | persona-web (realtime on messages/invitations) |
| `api_tokens`, `oauth_pending_state`, `telegram_links`, `telegram_chat_history` | persona | — |
| `linkedin_profiles`, `twitter_profiles`, `github_profiles` | persona | — |
| `enriched_contacts`, `enriched_companies`, `suggested_contacts`, `suggested_contact_runs` | persona | — |
| `chat_messages`, `brief_todos`, `published_pages` | persona | — |
| `cards.agent_profile_cards`, `cards.x_accounts`, `cards.x_mentions`, `cards.x_conversations`, `cards.keyword_posts` | cards | — (service role only; cards-web goes through cards-api) |
| `identity.*` (empty today; Zynd Account tables in Stage 2) | shared | persona, cards |

## Functions, triggers, publication

| Object | Owner | Last defined in | Called by |
|---|---|---|---|
| `is_persona_group_member(uuid)`, `is_persona_group_manager(uuid)` | persona | persona 0000 | RLS policies on group tables |
| `persona_agents_search_vector_update()` + trigger `persona_agents_search_vector_trigger` | persona | persona 0000 | keeps `persona_agents.search_vector` current |
| `search_personas_fts(text, int)` | persona | persona 0000 | persona-api, **memory** |
| `cards.skill_names(jsonb)` | cards | cards 0000 | generated column `agent_profile_cards.search_tsv` |
| `cards.match_cards(vector, int)`, `cards.search_cards_fts(text, int)` | cards | cards 0002 | cards-api (`services/search.py`) |
| publication `supabase_realtime` (9 persona tables) | persona | persona 0000 | persona-web realtime |
| extension `vector` (schema `extensions`) | cards | cards 0000 | — |
| schemas `cards`, `identity` + their grants | cards / shared | cards 0000, identity 0000 | — |
