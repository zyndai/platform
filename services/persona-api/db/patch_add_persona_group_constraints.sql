-- Patch: persona_group_constraints — shared "group memory"
--
-- Phase 4 — each group can carry a small set of guardrails that every
-- member's persona must respect when speaking inside the group. Three
-- kinds:
--
--   fact   — positive context ("Our launch is May 20")
--   rule   — negative instruction ("Don't quote pricing outside")
--   voice  — style guidance ("Warm tone, no exclamation marks")
--
-- The constraint list is injected into the dispatch prompt alongside the
-- shared brief; the brief is descriptive (what the team is doing), the
-- constraints are prescriptive (what to say / not say). Limited to a
-- handful per group — these are guardrails, not docs. The UI caps
-- creation at MAX_CONSTRAINTS_PER_GROUP in code.
--
-- Lives in a dedicated table (rather than a JSONB column) so the
-- created_by / created_at metadata is queryable and a soft archive flow
-- can preserve removed rules for audit without polluting the live list.

CREATE TABLE IF NOT EXISTS persona_group_constraints (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id            UUID NOT NULL REFERENCES persona_groups(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL CHECK (kind IN ('fact', 'rule', 'voice')),
    text                TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 400),
    created_by_user_id  UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS persona_group_constraints_group_idx
    ON persona_group_constraints (group_id, archived_at NULLS FIRST, created_at DESC);

ALTER TABLE persona_group_constraints ENABLE ROW LEVEL SECURITY;

CREATE POLICY "members read group constraints" ON persona_group_constraints
    FOR SELECT USING (public.is_persona_group_member(persona_group_constraints.group_id));

CREATE POLICY "service role full access on persona_group_constraints"
    ON persona_group_constraints
    FOR ALL USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
