import { sql } from 'drizzle-orm';
import { check, index, jsonb, pgTable, text, unique, uuid } from 'drizzle-orm/pg-core';
import { authUsers, fk, publicPolicy, serviceRolePolicy, tstz } from '../../lib/shared';
import { dmThreads, agentTasks } from './dm';

// owner: persona. Authoritative intro/approval state; Cards holds a minimal projection.
export const personaIntros = pgTable('persona_intro_requests', {
  id: uuid('id').primaryKey().defaultRandom(),
  cardId: text('card_id').notNull(),
  handle: text('handle').notNull(),
  requesterUid: uuid('requester_uid').notNull(),
  ownerUid: uuid('owner_uid').notNull(),
  requesterAgentId: text('requester_agent_id').notNull(),
  ownerAgentId: text('owner_agent_id').notNull(),
  requesterName: text('requester_name').notNull(),
  ownerName: text('owner_name').notNull(),
  why: text('why').notNull(),
  asks: jsonb('asks').notNull(),
  permissions: jsonb('permissions').notNull().default(sql`'{}'::jsonb`),
  status: text('status').notNull().default('pending'),
  idempotencyKey: uuid('idempotency_key').notNull(),
  threadId: uuid('thread_id').notNull(),
  meetingTaskId: uuid('meeting_task_id'),
  createdAt: tstz('created_at').notNull().defaultNow(),
  decidedAt: tstz('decided_at'),
}, t => [
  fk('persona_intro_requester_fkey', t.requesterUid, authUsers.id, 'cascade'),
  fk('persona_intro_owner_fkey', t.ownerUid, authUsers.id, 'cascade'),
  fk('persona_intro_thread_fkey', t.threadId, dmThreads.id, 'cascade'),
  fk('persona_intro_meeting_fkey', t.meetingTaskId, agentTasks.id, 'set null'),
  unique('persona_intro_requester_key').on(t.requesterUid, t.idempotencyKey),
  unique('persona_intro_thread_key').on(t.threadId),
  check('persona_intro_status_check', sql`status IN ('pending', 'accepted', 'declined', 'blocked', 'revoked')`),
  check('persona_intro_not_self', sql`requester_uid <> owner_uid`),
  index('persona_intro_owner_created_idx').on(t.ownerUid, t.createdAt),
  index('persona_intro_requester_created_idx').on(t.requesterUid, t.createdAt),
  serviceRolePolicy('persona_intro_requests'),
  publicPolicy('Intro participants read requests', {for: 'select', using: sql`auth.uid() IN (requester_uid, owner_uid)`}),
]);

export const introRules = pgTable('persona_intro_rules', {
  ownerUid: uuid('owner_uid').notNull(),
  requesterUid: uuid('requester_uid').notNull(),
  rule: text('rule').notNull(),
}, t => [
  unique('persona_intro_rules_owner_requester').on(t.ownerUid, t.requesterUid),
  check('persona_intro_rule_check', sql`rule IN ('allow', 'deny')`),
  fk('persona_intro_rule_owner_fkey', t.ownerUid, authUsers.id, 'cascade'),
  fk('persona_intro_rule_requester_fkey', t.requesterUid, authUsers.id, 'cascade'),
  serviceRolePolicy('persona_intro_rules'),
]);

export const introAudit = pgTable('persona_intro_audit', {
  id: uuid('id').primaryKey().defaultRandom(),
  introId: uuid('intro_id'),
  actorUid: uuid('actor_uid').notNull(),
  ownerUid: uuid('owner_uid').notNull(),
  action: text('action').notNull(),
  details: jsonb('details').notNull().default(sql`'{}'::jsonb`),
  createdAt: tstz('created_at').notNull().defaultNow(),
}, t => [
  fk('persona_intro_audit_request_fkey', t.introId, personaIntros.id, 'cascade'),
  index('persona_intro_audit_request_idx').on(t.introId),
  serviceRolePolicy('persona_intro_audit'),
]);
