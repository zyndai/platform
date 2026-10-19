import 'dotenv/config';
import { defineConfig } from 'drizzle-kit';
import { memoryTarget } from '../lib/memory-target';

export default defineConfig({
  dialect: 'postgresql',
  schema: './memory/schema/index.ts',
  out: './memory/migrations',
  schemaFilter: ['public'],
  migrations: { schema: 'drizzle', table: '__memory_migrations' },
  // Generation/checking do not connect; never substitute the shared DATABASE_URL.
  dbCredentials: { url: process.env.MEMORY_DATABASE_URL ? memoryTarget() : '' },
  strict: true,
  verbose: true,
});
