-- owner: memory
-- Persist explicit plugin consent and its private/public effects atomically.
-- Requires the existing memory users/assertions schema; this is not its baseline.
-- Rollback: after disabling plugin consent and exporting these records, drop
-- memory_plugin_outbox, memory_plugin_publications, memory_plugin_facts,
-- memory_plugin_consents in that order. Never drop existing memory tables.
CREATE TABLE public.memory_plugin_consents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL REFERENCES public.users(id),
  source_connection_id text,
  source_client_id text,
  action text NOT NULL CHECK (action IN ('save_memory', 'publish_card_fact')),
  content_hash text NOT NULL,
  nonce_hash text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
  status text NOT NULL CHECK (status IN ('saved_privately', 'published', 'rejected', 'sync_pending')),
  subject_id uuid,
  expires_at timestamptz NOT NULL,
  decided_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE public.memory_plugin_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id),
  consent_id uuid NOT NULL UNIQUE REFERENCES public.memory_plugin_consents(id),
  text text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE INDEX memory_plugin_facts_user_id_idx ON public.memory_plugin_facts(user_id);
--> statement-breakpoint
CREATE TABLE public.memory_plugin_publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.users(id),
  consent_id uuid NOT NULL UNIQUE REFERENCES public.memory_plugin_consents(id),
  assertion_id uuid NOT NULL REFERENCES public.assertions(id),
  predicate text NOT NULL,
  value text NOT NULL,
  public_text text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE public.memory_plugin_outbox (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_id uuid NOT NULL UNIQUE REFERENCES public.memory_plugin_publications(id),
  status text NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  last_error text
);
