-- ============================================================
-- Migration 004 — Auth columns + remaining audit fixes
-- Run AFTER 001, 002, 003
-- ============================================================

-- ── Riders: email/password/supabase for new auth model ──────────────────────
ALTER TABLE riders ADD COLUMN IF NOT EXISTS email              TEXT UNIQUE;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS password_hash      TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS supabase_user_id   TEXT UNIQUE;

-- phone and platform/city/hub_id were NOT NULL in migration 001.
-- For Google-OAuth or email-only riders these may be null, so relax constraints.
ALTER TABLE riders ALTER COLUMN phone          DROP NOT NULL;
ALTER TABLE riders ALTER COLUMN platform       DROP NOT NULL;
ALTER TABLE riders ALTER COLUMN city           DROP NOT NULL;
ALTER TABLE riders ALTER COLUMN hub_id         DROP NOT NULL;
ALTER TABLE riders ALTER COLUMN declared_income DROP NOT NULL;

-- ── admin_users: ensure table exists (already in 001 but guard anyway) ───────
CREATE TABLE IF NOT EXISTS admin_users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT UNIQUE NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Backward compat: if table existed before email support
ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS email TEXT;
UPDATE admin_users
SET email = username || '@gigshield.local'
WHERE email IS NULL;
ALTER TABLE admin_users ALTER COLUMN email SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_users_email ON admin_users (email);

-- Seed a default admin (CHANGE PASSWORD IN PRODUCTION)
-- password: GigShield@Admin123  (bcrypt hash)
INSERT INTO admin_users (username, email, password_hash)
VALUES (
  'admin',
  'admin@gigshield.local',
  '$2b$12$jX3bhE.TjvG0Zzct0eBEru5aJJ58YalJiD/IennsaQR2iLcttqQhO'
)
ON CONFLICT (username) DO NOTHING;

-- ── reconciliation_reports: ensure all spec columns present ─────────────────
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS period                    TEXT DEFAULT 'daily';
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS report_date               DATE;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_db_records          INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_razorpay_records    INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS matched_count             INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS late_success_count        INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS mismatch_count            INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS missing_from_db_count     INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS missing_from_razorpay_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_discrepancy_inr     NUMERIC(10,2) DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS issues_found              BOOLEAN DEFAULT false;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS report_data               JSONB;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS run_at                    TIMESTAMPTZ DEFAULT NOW();

-- ── fraud_clusters: ensure spec columns (cluster_type, status) present ──────
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS cluster_type TEXT DEFAULT 'ip_prefix_cluster';
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS status       TEXT DEFAULT 'suspected'
  CHECK (status IN ('suspected','confirmed','dismissed'));
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS admin_note   TEXT;

-- ── rider_consent_log: ensure table exists ───────────────────────────────────
CREATE TABLE IF NOT EXISTS rider_consent_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id     UUID REFERENCES riders(id) NOT NULL,
  action       TEXT NOT NULL,
  tos_version  TEXT,
  ip_address   TEXT,
  user_agent   TEXT,
  consented_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── system_config: ensure liquidity_mode and guardrail keys exist ────────────
INSERT INTO system_config (key, value) VALUES
  ('liquidity_mode',     'normal'),
  ('lambda_floor',       '1.0'),
  ('p_base_margin_pct',  '0.25')
ON CONFLICT (key) DO NOTHING;

-- ── plan_config: seed so legacy queries don't break if table referenced ──────
CREATE TABLE IF NOT EXISTS plan_config (
  plan              TEXT PRIMARY KEY,
  covered_triggers  TEXT[] NOT NULL,
  cap_multiplier    INTEGER NOT NULL,
  base_premium      NUMERIC(6,2) NOT NULL
);

INSERT INTO plan_config (plan, covered_triggers, cap_multiplier, base_premium) VALUES
  ('basic',    ARRAY['rain','bandh','platform_down'],                     3, 29.0),
  ('standard', ARRAY['rain','bandh','platform_down','flood','aqi'],       5, 49.0),
  ('pro',      ARRAY['rain','bandh','platform_down','flood','aqi','heat'],7, 79.0)
ON CONFLICT (plan) DO NOTHING;

-- ── entity_state_log: ensure it exists (needed for TDS tracking) ─────────────
CREATE TABLE IF NOT EXISTS entity_state_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type     TEXT NOT NULL,
  entity_id       UUID,
  from_state      TEXT,
  to_state        TEXT NOT NULL,
  reason          TEXT,
  service_name    TEXT,
  metadata        JSONB,
  transitioned_at TIMESTAMPTZ DEFAULT NOW()
);

-- Make entity_id nullable (TDS log uses text-cast IDs, not always real UUIDs)
ALTER TABLE entity_state_log ALTER COLUMN entity_id DROP NOT NULL;

-- ── zone_risk_cache: ensure vulnerability_idx column present ─────────────────
ALTER TABLE zone_risk_cache ADD COLUMN IF NOT EXISTS vulnerability_idx NUMERIC(4,3) DEFAULT 0.5;
ALTER TABLE zone_risk_cache ADD COLUMN IF NOT EXISTS active_policies   INTEGER DEFAULT 0;
ALTER TABLE zone_risk_cache ADD COLUMN IF NOT EXISTS lambda_surge      NUMERIC(4,3) DEFAULT 1.0;

-- ── metrics_timeseries: ensure labels column present ────────────────────────
ALTER TABLE metrics_timeseries ADD COLUMN IF NOT EXISTS labels JSONB;

-- ── payouts: ensure razorpay_status constraint covers all values ─────────────
ALTER TABLE payouts DROP CONSTRAINT IF EXISTS payouts_razorpay_status_check;
ALTER TABLE payouts ADD CONSTRAINT payouts_razorpay_status_check
  CHECK (razorpay_status IN (
    'initiated','processing','success','failed','reversed',
    'circuit_breaker_hold','pending_manual'
  ));
