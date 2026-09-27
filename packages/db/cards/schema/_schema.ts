import { pgSchema } from 'drizzle-orm/pg-core';

// cards' tables live in their own `cards` schema, so they can never collide
// with persona's names, and this history never touches anything else.
export const cards = pgSchema('cards');
