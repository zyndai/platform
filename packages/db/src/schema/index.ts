// Every table in the shared aafo database. drizzle-kit reads this file;
// runtime code (persona-api, cards-api, memory) still uses supabase-py.
export * from './persona/agents';
export * from './persona/callbacks';
export * from './persona/contacts';
export * from './persona/content';
export * from './persona/dm';
export * from './persona/groups';
export * from './persona/integrations';
export * from './cards/cards';
export * from './cards/x_bot';
