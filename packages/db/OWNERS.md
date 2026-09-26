# Who owns what in the shared aafo database

A change to a table needs a review from its owner, **and** from every
service listed as a reader.

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
| `agent_profile_cards`, `x_accounts`, `x_mentions`, `x_conversations` | cards | — (service role only; cards-web goes through cards-api) |

## Functions, triggers, publication

| Object | Owner | Last defined in | Called by |
|---|---|---|---|
| `is_persona_group_member(uuid)`, `is_persona_group_manager(uuid)` | persona | 0000 | RLS policies on group tables |
| `persona_agents_search_vector_update()` + trigger `persona_agents_search_vector_trigger` | persona | 0000 | keeps `persona_agents.search_vector` current |
| `search_personas_fts(text, int)` | persona | 0000 | persona-api, **memory** |
| `skill_names(jsonb)` | cards | 0002 | generated column `agent_profile_cards.search_tsv` |
| `match_cards(vector, int)`, `search_cards_fts(text, int)` | cards | 0004 | cards-api (`services/search.py`) |
| publication `supabase_realtime` (9 persona tables) | persona | 0000 | persona-web realtime |
| extension `vector` (schema `extensions`) | cards | 0002 | — |
