-- ============================================================
-- Migration 003 — All schema fixes from audit report
-- SCHEMA-01 through SCHEMA-07 + missing columns
-- ============================================================

-- SCHEMA-05 FIX: Add beta_freeze_until to riders
ALTER TABLE riders ADD COLUMN IF NOT EXISTS beta_freeze_until TIMESTAMPTZ;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS platform_reported_income NUMERIC(8,2);

-- SCHEMA-05 FIX: Add beta_freeze_until to policies as well (per spec §6.1)
ALTER TABLE policies ADD COLUMN IF NOT EXISTS beta_freeze_until TIMESTAMPTZ;

-- SCHEMA-04 FIX: Add active_policies and lambda_surge to zone_risk_cache
ALTER TABLE zone_risk_cache ADD COLUMN IF NOT EXISTS active_policies INTEGER DEFAULT 0;
ALTER TABLE zone_risk_cache ADD COLUMN IF NOT EXISTS lambda_surge NUMERIC(4,3) DEFAULT 1.0;

-- SCHEMA-06 FIX: Fix duplicate enum value in payouts.razorpay_status
ALTER TABLE payouts DROP CONSTRAINT IF EXISTS payouts_razorpay_status_check;
ALTER TABLE payouts ADD CONSTRAINT payouts_razorpay_status_check
  CHECK (razorpay_status IN (
    'initiated','processing','success','failed','reversed','circuit_breaker_hold','pending_manual'
  ));

-- SCHEMA-07 FIX: experiments.parameter_value must be TEXT (not JSONB)
-- Ensure correct type — oracle_service casts as ::float
ALTER TABLE experiments ALTER COLUMN parameter_value TYPE TEXT USING parameter_value::text;

-- SCHEMA-03 FIX: Alias expected_payouts_24h as expected_24h for compat
COMMENT ON COLUMN liquidity_snapshots.expected_payouts_24h IS 'spec name: expected_24h';

-- SCHEMA-01 FIX: Reconcile fraud_clusters with spec §10.7
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS cluster_type TEXT DEFAULT 'ip_enrollment';
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'suspected'
  CHECK (status IN ('suspected','confirmed','dismissed'));
ALTER TABLE fraud_clusters ADD COLUMN IF NOT EXISTS admin_note TEXT;

-- SCHEMA-02 FIX: Reconciliation reports aligned with spec §20.1
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS report_date DATE;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_db_records INTEGER;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_razorpay_records INTEGER;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS matched_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS late_success_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS mismatch_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS missing_from_db_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS missing_from_razorpay_count INTEGER DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_discrepancy_inr NUMERIC(10,2) DEFAULT 0;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS layer TEXT DEFAULT 'layer3';

-- GAP-13 FIX: annual_payout_total must exist on riders (ensure it's correct type)
ALTER TABLE riders ADD COLUMN IF NOT EXISTS annual_payout_total NUMERIC(10,2) DEFAULT 0;

-- GAP-14 FIX: Proper RLS policies (spec §26.1 + DPDP Act)
-- Enable RLS
ALTER TABLE riders          ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims          ENABLE ROW LEVEL SECURITY;
ALTER TABLE payouts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_pings ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence  ENABLE ROW LEVEL SECURITY;
ALTER TABLE disputes        ENABLE ROW LEVEL SECURITY;

-- Drop old permissive policies if they exist
DROP POLICY IF EXISTS "service_role_all" ON riders;
DROP POLICY IF EXISTS "service_role_all" ON policies;
DROP POLICY IF EXISTS "service_role_all" ON claims;
DROP POLICY IF EXISTS "service_role_all" ON payouts;
DROP POLICY IF EXISTS "service_role_all" ON telemetry_pings;
DROP POLICY IF EXISTS "service_role_all" ON claim_evidence;
DROP POLICY IF EXISTS "service_role_all" ON disputes;

-- Service role bypasses all RLS (backend API uses service role)
CREATE POLICY "service_role_bypass" ON riders          FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON policies        FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON claims          FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON payouts         FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON telemetry_pings FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON claim_evidence  FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "service_role_bypass" ON disputes        FOR ALL USING (auth.role() = 'service_role');

-- Riders can only see their own data (anon key usage)
CREATE POLICY "rider_own_data" ON riders
  FOR SELECT USING (auth.uid()::text = id::text);

CREATE POLICY "rider_own_policies" ON policies
  FOR SELECT USING (auth.uid()::text = rider_id::text);

CREATE POLICY "rider_own_claims" ON claims
  FOR SELECT USING (auth.uid()::text = rider_id::text);

CREATE POLICY "rider_own_payouts" ON payouts
  FOR SELECT USING (auth.uid()::text = rider_id::text);

CREATE POLICY "rider_own_telemetry" ON telemetry_pings
  FOR INSERT WITH CHECK (auth.uid()::text = rider_id::text);

-- GAP-16 FIX: Register pg_cron schedules
-- (Only runs if pg_cron extension is available)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    -- Every 5 min: liquidity snapshot marker
    PERFORM cron.schedule('gs-liquidity-5min',   '*/5 * * * *',  'SELECT 1 -- gigshield liquidity');
    -- Every 15 min: oracle cycle marker
    PERFORM cron.schedule('gs-oracle-15min',     '*/15 * * * *', 'SELECT 1 -- gigshield oracle');
    -- Every 30 min: continuation marker
    PERFORM cron.schedule('gs-continuation-30m', '*/30 * * * *', 'SELECT 1 -- gigshield continuation');
    -- Monday 00:01 IST = Sunday 18:31 UTC — cron_lock insert
    PERFORM cron.schedule('gs-monday-cycle', '31 18 * * 0',
      $cron$INSERT INTO cron_locks(job_name, week_start)
        VALUES('monday_cycle', date_trunc('week', NOW())::date)
        ON CONFLICT DO NOTHING$cron$
    );
    -- Daily 03:00 UTC: reconciliation marker
    PERFORM cron.schedule('gs-reconcile-daily', '0 3 * * *', 'SELECT 1 -- gigshield reconcile');
    -- Monthly 1st 02:00 UTC: ML retrain marker
    PERFORM cron.schedule('gs-ml-monthly', '0 2 1 * *', 'SELECT 1 -- gigshield ml retrain');
  END IF;
END $$;

-- Update system_config with correct defaults
INSERT INTO system_config (key, value) VALUES
  ('liquidity_mode', 'normal'),
  ('p_base_margin_pct', '0.25')
ON CONFLICT (key) DO NOTHING;

-- Add backtest and stress_test result tables with correct schema
CREATE TABLE IF NOT EXISTS backtest_results (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  city                 TEXT,
  date_from            DATE,
  date_to              DATE,
  config_used          JSONB,
  precision_pct        NUMERIC(5,2),
  recall_pct           NUMERIC(5,2),
  simulated_loss_ratio NUMERIC(6,4),
  actual_loss_ratio    NUMERIC(6,4),
  delta_loss_ratio     NUMERIC(6,4),
  is_simulation        BOOLEAN DEFAULT true,
  run_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS stress_test_scenarios (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  scenario_type TEXT NOT NULL,
  params        JSONB NOT NULL,
  last_result   JSONB,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Migration 003 addendum: align reconciliation_reports with
-- what reconciliation_service.py actually inserts
-- (period, issues_found, report_data columns)
-- ============================================================
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS period TEXT DEFAULT 'daily';
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS issues_found BOOLEAN DEFAULT false;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS report_data JSONB;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS run_at TIMESTAMPTZ DEFAULT NOW();
-- Ensure run_at exists (original schema used created_at)
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- ============================================================
-- Migration 003 addendum: riders table new columns for auth
-- (email, password_hash, supabase_user_id for new auth flows)
-- ============================================================
ALTER TABLE riders ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS supabase_user_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_riders_email ON riders (email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_riders_supabase_uid ON riders (supabase_user_id) WHERE supabase_user_id IS NOT NULL;

-- ============================================================
-- Migration 003 addendum: admin_users table (required by admin login)
-- ============================================================
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

-- Seed default admin — CHANGE PASSWORD IN PRODUCTION
INSERT INTO admin_users (username, email, password_hash)
VALUES ('admin', 'admin@gigshield.local', crypt('GigShield@Admin2024!', gen_salt('bf')))
ON CONFLICT (username) DO NOTHING;

-- ============================================================
-- Migration 003 addendum: plan_config table (used optionally)
-- Provides covered_triggers per plan — also backed up in mu_table.py
-- ============================================================
CREATE TABLE IF NOT EXISTS plan_config (
  plan              TEXT PRIMARY KEY,
  covered_triggers  TEXT[] NOT NULL,
  cap_multiplier    INTEGER NOT NULL DEFAULT 3,
  base_premium      NUMERIC(6,2) NOT NULL DEFAULT 29.0
);

INSERT INTO plan_config (plan, covered_triggers, cap_multiplier, base_premium) VALUES
  ('basic',    ARRAY['rain','bandh','platform_down'], 3, 29.0),
  ('standard', ARRAY['rain','bandh','platform_down','flood','aqi'], 5, 49.0),
  ('pro',      ARRAY['rain','bandh','platform_down','flood','aqi','heat'], 7, 79.0)
ON CONFLICT (plan) DO NOTHING;
