import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/**
 * The independent migration histories, in the order they apply to a fresh
 * database (cards references auth.users only, but identity comes first so
 * later histories can reference it). Each owns its schemas and records its
 * progress in drizzle.__<name>_migrations.
 */
export const HISTORIES = [
  { name: 'identity', owns: ['identity'] },
  { name: 'persona', owns: ['public'] },
  { name: 'cards', owns: ['cards'] },
] as const;

export type HistoryName = (typeof HISTORIES)[number]['name'];

export const migrationsFolder = (name: HistoryName) => join(root, name, 'migrations');
export const migrationsTable = (name: HistoryName) => `__${name}_migrations`;

export function readJournal(folder: string): { entries: { idx: number; tag: string; when: number }[] } {
  return JSON.parse(readFileSync(join(folder, 'meta/_journal.json'), 'utf8'));
}

/** Parse `--project a,b` (default: all, in order). */
export function selectedHistories(argv: string[]): (typeof HISTORIES)[number][] {
  const i = argv.indexOf('--project');
  if (i === -1) return [...HISTORIES];
  const wanted = argv[i + 1]?.split(',') ?? [];
  const unknown = wanted.filter((w) => !HISTORIES.some((h) => h.name === w));
  if (unknown.length) throw new Error(`unknown --project ${unknown.join(',')}; expected ${HISTORIES.map((h) => h.name).join(', ')}`);
  return HISTORIES.filter((h) => wanted.includes(h.name));
}
