-- ============================================================
-- GigShield Migration 002 — Missing Tables from Audit
-- Adds: zone_risk_cache, fraud_clusters, experiments (full),
--       rider_risk_scores, blacklisted_devices, cron_locks,
--       segment_economics, zone_vov_certs (full constraints),
--       DB-level idempotency enforcement, trigger state machine
-- Run AFTER 001_initial_schema.sql
-- ============================================================

-- ============================================================
-- ZONE RISK CACHE (cold-start + vulnerability per hex)
-- ============================================================
CREATE TABLE IF NOT EXISTS zone_risk_cache (
  h3_index              TEXT PRIMARY KEY,
  vulnerability_idx     NUMERIC(4,3) DEFAULT 0.5,
  confirmed_event_count INTEGER DEFAULT 0,
  cold_start_mode       BOOLEAN DEFAULT true,
  last_trigger_at       TIMESTAMPTZ,
  last_updated          TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-exit cold start when confirmed_event_count reaches 20
CREATE OR REPLACE FUNCTION update_cold_start_mode()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.confirmed_event_count >= 20 THEN
    NEW.cold_start_mode := false;
  END IF;
  NEW.last_updated := NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cold_start ON zone_risk_cache;
CREATE TRIGGER trg_cold_start
  BEFORE UPDATE ON zone_risk_cache
  FOR EACH ROW EXECUTE FUNCTION update_cold_start_mode();

-- Seed initial zone_risk_cache from hubs
INSERT INTO zone_risk_cache (h3_index, cold_start_mode)
SELECT DISTINCT h3_index_res9, true FROM hubs
ON CONFLICT DO NOTHING;

-- ============================================================
-- FRAUD CLUSTERS (geospatial syndicate detection)
-- ============================================================
CREATE TABLE IF NOT EXISTS fraud_clusters (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cluster_id           TEXT NOT NULL UNIQUE,
  rider_ids            UUID[] NOT NULL,
  detection_reason     TEXT NOT NULL,
  enrollment_ip_prefix TEXT,
  device_fingerprints  TEXT[],
  h3_hexes             TEXT[],
  risk_score_avg       NUMERIC(5,2),
  confirmed            BOOLEAN DEFAULT false,
  confirmed_by_admin   UUID,
  confirmed_at         TIMESTAMPTZ,
  detected_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_clusters_riders ON fraud_clusters USING GIN (rider_ids);

-- ============================================================
-- BLACKLISTED DEVICES
-- ============================================================
CREATE TABLE IF NOT EXISTS blacklisted_devices (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_fingerprint TEXT UNIQUE NOT NULL,
  rider_id           UUID REFERENCES riders(id),
  reason             TEXT,
  blacklisted_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RIDER RISK SCORE HISTORY (full audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS rider_risk_scores (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id     UUID REFERENCES riders(id) NOT NULL,
  risk_score   INTEGER NOT NULL,
  risk_profile TEXT NOT NULL,
  delta        INTEGER,              -- change from previous score
  trigger_reason TEXT,              -- 'weekly_decay' | 'hard_flag' | 'fraud_confirmed'
  computed_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_risk_scores_rider ON rider_risk_scores (rider_id, computed_at DESC);

-- ============================================================
-- CRON LOCKS (double-run protection for pg_cron / Celery beat)
-- ============================================================
CREATE TABLE IF NOT EXISTS cron_locks (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name   TEXT NOT NULL,
  week_start DATE NOT NULL,
  locked_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(job_name, week_start)
);

-- ============================================================
-- EXPERIMENTS (full A/B framework with group metadata)
-- ============================================================
CREATE TABLE IF NOT EXISTS experiments (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parameter_name   TEXT NOT NULL,
  parameter_value  TEXT NOT NULL,
  group_id         TEXT NOT NULL DEFAULT 'all'
                   CHECK (group_id != 'holdout'),   -- holdout can never be targeted
  active           BOOLEAN DEFAULT true,
  created_by       UUID REFERENCES admin_users(id),
  rollback_value   TEXT,    -- previous value, for 24hr rollback
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  expires_at       TIMESTAMPTZ   -- optional expiry
);

CREATE INDEX IF NOT EXISTS idx_experiments_active ON experiments (parameter_name, group_id)
  WHERE active = true;

-- ============================================================
-- METRICS TIMESERIES (extended — labels JSONB for dimensions)
-- ============================================================
-- Already created in 001; add labels column if missing
ALTER TABLE metrics_timeseries ADD COLUMN IF NOT EXISTS labels JSONB;
CREATE INDEX IF NOT EXISTS idx_metrics_labels ON metrics_timeseries USING GIN (labels)
  WHERE labels IS NOT NULL;

-- ============================================================
-- RECONCILIATION REPORTS (extended)
-- ============================================================
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS total_amount  NUMERIC(12,2);
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS matched_count INTEGER;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS failed_count  INTEGER;
ALTER TABLE reconciliation_reports ADD COLUMN IF NOT EXISTS layer        TEXT DEFAULT 'layer3';

-- ============================================================
-- CIRCUIT BREAKER EVENTS (full logging)
-- ============================================================
CREATE TABLE IF NOT EXISTS circuit_breaker_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service       TEXT NOT NULL,
  event_type    TEXT NOT NULL
                CHECK (event_type IN ('opened','closed','half_open','call_failed','call_succeeded','reset')),
  failure_count INTEGER,
  error_message TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cb_events_service ON circuit_breaker_events (service, created_at DESC);

-- ============================================================
-- ZONE VOV CERTS (add unique constraint if missing)
-- ============================================================
ALTER TABLE zone_vov_certs
  ADD COLUMN IF NOT EXISTS zone_oracle_score NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS riders_certified  INTEGER DEFAULT 0;

-- ============================================================
-- SEGMENT ECONOMICS (full weekly snapshot)
-- ============================================================
CREATE TABLE IF NOT EXISTS segment_economics (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  city                TEXT NOT NULL,
  plan                TEXT NOT NULL,
  tier                TEXT NOT NULL,
  risk_profile        TEXT NOT NULL,
  week_start          DATE NOT NULL,
  active_policies     INTEGER DEFAULT 0,
  premiums_collected  NUMERIC(12,2) DEFAULT 0,
  payouts_issued      NUMERIC(12,2) DEFAULT 0,
  loss_ratio          NUMERIC(8,4),
  gross_margin        NUMERIC(12,2),
  avg_fraud_score     NUMERIC(4,3),
  auto_clear_rate     NUMERIC(4,3),
  computed_at         TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(city, plan, tier, risk_profile, week_start)
);

-- ============================================================
-- RIDER CONSENT LOG (DPDP Act 2023 + ToS versioning)
-- ============================================================
CREATE TABLE IF NOT EXISTS rider_consent_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id     UUID REFERENCES riders(id) NOT NULL,
  action       TEXT NOT NULL,  -- 'tos_accept' | 'kyc_consent' | 'data_deletion_request'
  tos_version  TEXT,
  ip_address   TEXT,
  user_agent   TEXT,
  consented_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- DATA ACCESS LOG (DPDP Act — admin PII access audit)
-- ============================================================
CREATE TABLE IF NOT EXISTS data_access_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id    UUID REFERENCES admin_users(id),
  rider_id    UUID REFERENCES riders(id),
  action      TEXT NOT NULL,   -- 'view_profile' | 'view_claims' | 'export'
  fields_accessed TEXT[],
  accessed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ENTITY STATE LOG (debugging partial failures)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_state_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type     TEXT NOT NULL,
  entity_id       UUID NOT NULL,
  from_state      TEXT,
  to_state        TEXT NOT NULL,
  reason          TEXT,
  service_name    TEXT,
  metadata        JSONB,
  transitioned_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_state_log_entity ON entity_state_log (entity_type, entity_id, transitioned_at DESC);

-- ============================================================
-- ENFORCE IDEMPOTENCY AT DB LEVEL
-- Already have UNIQUE on payouts.idempotency_key and claims.idempotency_key
-- Add partial index for active claims to speed fraud queue queries
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_claims_fraud_queue ON claims (fraud_score DESC, initiated_at DESC)
  WHERE status IN ('hard_flagged', 'manual_review');

CREATE INDEX IF NOT EXISTS idx_payouts_stuck ON payouts (released_at)
  WHERE razorpay_status IN ('processing', 'initiated');

CREATE INDEX IF NOT EXISTS idx_payouts_circuit_hold ON payouts (released_at)
  WHERE razorpay_status = 'circuit_breaker_hold';

-- ============================================================
-- CLAIM STATE MACHINE ENFORCEMENT (DB trigger)
-- Prevents illegal status transitions at the DB level
-- ============================================================
CREATE OR REPLACE FUNCTION validate_claim_state_transition()
RETURNS TRIGGER AS $$
BEGIN
  -- Terminal states cannot transition
  IF OLD.status IN ('paid', 'rejected', 'manual_rejected') AND NEW.status != OLD.status THEN
    RAISE EXCEPTION 'Claim % is in terminal state %, cannot transition to %',
      OLD.id, OLD.status, NEW.status;
  END IF;

  -- cap_exhausted is also terminal
  IF OLD.status = 'cap_exhausted' AND NEW.status != OLD.status THEN
    RAISE EXCEPTION 'Claim % cap_exhausted is terminal', OLD.id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_claim_state_machine ON claims;
CREATE TRIGGER enforce_claim_state_machine
  BEFORE UPDATE ON claims
  FOR EACH ROW
  WHEN (OLD.status IS DISTINCT FROM NEW.status)
  EXECUTE FUNCTION validate_claim_state_transition();

-- ============================================================
-- POLICY STATE MACHINE ENFORCEMENT
-- ============================================================
CREATE OR REPLACE FUNCTION validate_policy_state_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.status = 'cancelled' AND NEW.status != 'cancelled' THEN
    RAISE EXCEPTION 'Policy % is cancelled and cannot be reactivated', OLD.id;
  END IF;
  IF OLD.status = 'active' AND NEW.status NOT IN ('paused','lapsed','cancelled') THEN
    RAISE EXCEPTION 'Invalid policy transition: active -> %', NEW.status;
  END IF;
  IF OLD.status = 'paused' AND NEW.status NOT IN ('active','lapsed','cancelled') THEN
    RAISE EXCEPTION 'Invalid policy transition: paused -> %', NEW.status;
  END IF;
  IF OLD.status = 'lapsed' AND NEW.status NOT IN ('active','cancelled') THEN
    RAISE EXCEPTION 'Invalid policy transition: lapsed -> %', NEW.status;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_policy_state_machine ON policies;
CREATE TRIGGER enforce_policy_state_machine
  BEFORE UPDATE ON policies
  FOR EACH ROW
  WHEN (OLD.status IS DISTINCT FROM NEW.status)
  EXECUTE FUNCTION validate_policy_state_transition();

-- ============================================================
-- pg_cron JOBS (DB-time-based — UTC)
-- Requires pg_cron extension (available in Supabase)
-- ============================================================
-- Every 5 min: platform health + liquidity
SELECT cron.schedule('platform-health',    '*/5 * * * *',  'SELECT 1'); -- replaced by Celery
SELECT cron.schedule('liquidity-snapshot', '*/5 * * * *',  'SELECT 1');
-- Every 15 min: oracle cycle
SELECT cron.schedule('oracle-cycle',       '*/15 * * * *', 'SELECT 1');
-- Every 30 min: continuation
SELECT cron.schedule('continuation',       '*/30 * * * *', 'SELECT 1');
-- Monday 00:01 IST = Sunday 18:31 UTC
SELECT cron.schedule('monday-cycle',       '31 18 * * 0',
  $$INSERT INTO cron_locks(job_name, week_start)
    VALUES('monday_cycle', date_trunc('week', NOW())::date)
    ON CONFLICT DO NOTHING$$);
-- Daily 03:00 UTC: reconciliation
SELECT cron.schedule('daily-reconcile',    '0 3 * * *',    'SELECT 1');
-- Monthly 1st 02:00 UTC: ML retrain
SELECT cron.schedule('monthly-ml',         '0 2 1 * *',    'SELECT 1');

-- ============================================================
-- ADMIN_AUDIT_LOG — ensure it exists with right columns
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_audit_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id     UUID REFERENCES admin_users(id),
  action       TEXT NOT NULL,
  entity_type  TEXT NOT NULL,
  entity_id    TEXT,
  diff         JSONB,
  ip_address   TEXT,
  performed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON admin_audit_log (performed_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_admin ON admin_audit_log (admin_id, performed_at DESC);

-- ============================================================
-- INDEXES for missing query patterns
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_telemetry_bundle ON telemetry_pings (bundle_hash)
  WHERE bundle_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_evidence_rider ON claim_evidence (rider_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes (status)
  WHERE status != 'resolved';
CREATE INDEX IF NOT EXISTS idx_shift_open ON shift_states (rider_id)
  WHERE ended_at IS NULL;
