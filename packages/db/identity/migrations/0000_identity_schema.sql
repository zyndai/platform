-- owner: shared
-- The identity schema: the only thing persona and cards genuinely share.
-- Empty for now (the shared user id is Supabase's auth.users). Stage 2 adds
-- the Zynd Account tables here. Only the backends (service role) may use it.
CREATE SCHEMA "identity";
--> statement-breakpoint
GRANT USAGE ON SCHEMA identity TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity GRANT EXECUTE ON FUNCTIONS TO service_role;
