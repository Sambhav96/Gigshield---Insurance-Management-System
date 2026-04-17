-- Migration 005: cron_locks + rider_risk_scores + consent_logs + RLS policies
-- Run in Supabase SQL Editor after 001-004. Safe to re-run.

-- PART A: cron_locks
-- monday_worker.py inserts: INSERT INTO cron_locks(job_name, week_start) ... ON CONFLICT(job_name, week_start)
-- The UNIQUE constraint on (job_name, week_start) is required for ON CONFLICT to work.
CREATE TABLE IF NOT EXISTS cron_locks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name    TEXT NOT NULL,
  week_start  DATE NOT NULL,
  locked_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(job_name, week_start)
);

-- PART B: rider_risk_scores
CREATE TABLE IF NOT EXISTS rider_risk_scores (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id    UUID REFERENCES riders(id) NOT NULL,
  old_score   INTEGER,
  new_score   INTEGER NOT NULL,
  reason      TEXT,
  scored_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rider_risk_scores_rider
  ON rider_risk_scores(rider_id);

-- PART C: consent_logs
CREATE TABLE IF NOT EXISTS consent_logs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id     UUID REFERENCES riders(id) NOT NULL,
  consent_type TEXT NOT NULL,
  version      TEXT NOT NULL DEFAULT '1.0',
  ip_address   TEXT,
  accepted_at  TIMESTAMPTZ DEFAULT NOW()
);

-- PART D: Row Level Security
-- Supabase service_role key bypasses all RLS automatically — backend is not affected.
-- These policies only restrict access via Supabase anon/user JWT tokens (frontend Supabase JS client).
ALTER TABLE riders   ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims   ENABLE ROW LEVEL SECURITY;
ALTER TABLE payouts  ENABLE ROW LEVEL SECURITY;

-- riders table: each rider sees only their own row
-- supabase_user_id is a TEXT column in riders storing auth.users.id
DROP POLICY IF EXISTS "riders_self_only" ON riders;
CREATE POLICY "riders_self_only"
  ON riders FOR ALL
  USING (supabase_user_id = auth.uid()::text);

-- policies: rider sees only their own policies
DROP POLICY IF EXISTS "policies_owner_only" ON policies;
CREATE POLICY "policies_owner_only"
  ON policies FOR ALL
  USING (
    rider_id IN (
      SELECT id FROM riders WHERE supabase_user_id = auth.uid()::text
    )
  );

-- claims: rider sees only their own claims
DROP POLICY IF EXISTS "claims_owner_only" ON claims;
CREATE POLICY "claims_owner_only"
  ON claims FOR ALL
  USING (
    rider_id IN (
      SELECT id FROM riders WHERE supabase_user_id = auth.uid()::text
    )
  );

-- payouts: rider sees only payouts for their own claims
DROP POLICY IF EXISTS "payouts_owner_only" ON payouts;
CREATE POLICY "payouts_owner_only"
  ON payouts FOR ALL
  USING (
    claim_id IN (
      SELECT id FROM claims WHERE rider_id IN (
        SELECT id FROM riders WHERE supabase_user_id = auth.uid()::text
      )
    )
  );
