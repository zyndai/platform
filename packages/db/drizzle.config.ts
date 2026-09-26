import 'dotenv/config';
import { defineConfig } from 'drizzle-kit';

// One migration history for the shared aafo database (persona + cards).
// See README.md before running anything against a real database.
export default defineConfig({
  dialect: 'postgresql',
  schema: './src/schema/index.ts',
  out: './migrations',
  // Only diff `public`. auth/storage/realtime/extensions belong to Supabase.
  schemaFilter: ['public'],
  // anon / authenticated / service_role already exist on Supabase; never create them.
  entities: { roles: { provider: 'supabase' } },
  migrations: { schema: 'drizzle', table: '__drizzle_migrations' },
  dbCredentials: { url: process.env.DATABASE_URL ?? '' },
  strict: true,
  verbose: true,
});
