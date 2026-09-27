import { pgSchema } from 'drizzle-orm/pg-core';

// owner: shared (reviews: platform owner). The `identity` schema holds what
// persona AND cards both reference, and nothing else. Today the shared
// identity is Supabase's own auth.users (both products' user ids point at
// it), so this schema starts empty. It is where the Zynd Account layer goes
// (Stage 2: profiles / zynd_uid). Changes here are rare and reviewed by both
// products.
export const identity = pgSchema('identity');
