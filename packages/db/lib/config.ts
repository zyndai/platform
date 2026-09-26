import 'dotenv/config';
import { defineConfig } from 'drizzle-kit';

/**
 * drizzle-kit config for one migration history. Each history owns exactly the
 * Postgres schemas it lists and records its own progress in its own table
 * (drizzle.__<name>_migrations), so persona, cards and identity migrate
 * independently. Run drizzle-kit from packages/db with
 * `--config <name>/drizzle.config.ts` (the npm scripts do this).
 */
export const historyConfig = (name: 'identity' | 'persona' | 'cards', ownedSchemas: string[]) =>
  defineConfig({
    dialect: 'postgresql',
    schema: `./${name}/schema/index.ts`,
    out: `./${name}/migrations`,
    schemaFilter: ownedSchemas,
    // anon / authenticated / service_role exist on Supabase already; never create them.
    entities: { roles: { provider: 'supabase' } },
    migrations: { schema: 'drizzle', table: `__${name}_migrations` },
    dbCredentials: { url: process.env.DATABASE_URL ?? '' },
    strict: true,
    verbose: true,
  });
