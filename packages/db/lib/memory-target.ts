const SHARED_REFS = ['aafoguuvmaxymrtnfafn', 'xmfjvixclgqcmjmtecwv'];

/** Compare database endpoints, ignoring credentials and connection options. */
export function sameDatabase(left: string, right: string): boolean {
  const a = new URL(left);
  const b = new URL(right);
  return a.hostname.toLowerCase() === b.hostname.toLowerCase() &&
    (a.port || '5432') === (b.port || '5432') &&
    decodeURIComponent(a.pathname) === decodeURIComponent(b.pathname);
}

export function memoryTarget(env: NodeJS.ProcessEnv = process.env): string {
  const url = env.MEMORY_DATABASE_URL;
  if (!url) throw new Error('MEMORY_DATABASE_URL is not set; memory never falls back to DATABASE_URL.');
  const target = new URL(url);
  if (!['postgres:', 'postgresql:'].includes(target.protocol)) {
    throw new Error('MEMORY_DATABASE_URL must be a Postgres URL.');
  }
  // libpq connection parameters must not override the endpoint validated here.
  for (const key of target.searchParams.keys()) {
    if (['host', 'hostaddr', 'port', 'dbname', 'user', 'service'].includes(key.toLowerCase())) {
      throw new Error(`MEMORY_DATABASE_URL cannot override ${key} through query parameters.`);
    }
  }
  const identity = `${target.hostname} ${decodeURIComponent(target.username)}`.toLowerCase();
  if (SHARED_REFS.some((ref) => identity.includes(ref))) {
    throw new Error('Refusing memory migrations against the aafo or dashboard Supabase project.');
  }
  if (env.DATABASE_URL && sameDatabase(url, env.DATABASE_URL)) {
    throw new Error('MEMORY_DATABASE_URL must target a different database from DATABASE_URL.');
  }
  return url;
}
