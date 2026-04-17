-- ============================================================
-- GigShield Complete Database Schema v3.0
-- Run via: psql $DATABASE_URL -f 001_initial_schema.sql
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_cron;

-- ============================================================
-- ADMIN USERS
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  email         TEXT UNIQUE NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- HUBS (DARK STORES)
-- ============================================================
CREATE TABLE IF NOT EXISTS hubs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name              TEXT NOT NULL,
  platform          TEXT NOT NULL CHECK (platform IN ('zepto','blinkit','instamart')),
  city              TEXT NOT NULL,
  latitude          NUMERIC(10,7) NOT NULL,
  longitude         NUMERIC(10,7) NOT NULL,
  h3_index_res9     TEXT NOT NULL,
  h3_index_res8     TEXT NOT NULL,
  radius_km         NUMERIC(4,2) DEFAULT 2.0,
  capacity          INTEGER DEFAULT 100,
  city_multiplier   NUMERIC(4,3) NOT NULL,
  drainage_index    NUMERIC(4,3) DEFAULT 0.5,
  rain_threshold_mm NUMERIC(5,2) DEFAULT 35.0,
  api_key           TEXT,
  geom              GEOGRAPHY(POINT, 4326),
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RIDERS
-- ============================================================
CREATE TABLE IF NOT EXISTS riders (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                      TEXT NOT NULL,
  phone                     TEXT UNIQUE NOT NULL,
  aadhaar_hash              TEXT,
  pan_hash                  TEXT,
  platform                  TEXT NOT NULL CHECK (platform IN ('zepto','blinkit','instamart')),
  city                      TEXT NOT NULL,
  hub_id                    UUID REFERENCES hubs(id),
  declared_income           NUMERIC(8,2) NOT NULL,
  effective_income          NUMERIC(8,2) NOT NULL,
  telemetry_inferred_income NUMERIC(8,2),
  income_verified_at        TIMESTAMPTZ,
  tier                      TEXT DEFAULT 'B' CHECK (tier IN ('A','B')),
  risk_score                INTEGER DEFAULT 50 CHECK (risk_score BETWEEN 0 AND 100),
  risk_profile              TEXT DEFAULT 'medium' CHECK (risk_profile IN ('low','medium','high')),
  device_fingerprint        TEXT,
  bank_account_hash         TEXT,
  phone_verified            BOOLEAN DEFAULT false,
  enrollment_ip_prefix      TEXT,
  syndicate_suspect_group_id UUID,
  experiment_group_id       TEXT DEFAULT 'control',
  annual_payout_total       NUMERIC(10,2) DEFAULT 0,
  created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RIDER RISK SCORE HISTORY (audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS rider_risk_scores (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id    UUID REFERENCES riders(id) NOT NULL,
  risk_score  INTEGER NOT NULL,
  risk_profile TEXT NOT NULL,
  computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- BLACKLISTED DEVICES
-- ============================================================
CREATE TABLE IF NOT EXISTS blacklisted_devices (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  device_fingerprint TEXT UNIQUE NOT NULL,
  reason             TEXT,
  blacklisted_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- POLICIES
-- ============================================================
CREATE TABLE IF NOT EXISTS policies (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id                  UUID REFERENCES riders(id) NOT NULL,
  hub_id                    UUID REFERENCES hubs(id) NOT NULL,
  plan                      TEXT NOT NULL CHECK (plan IN ('basic','standard','pro')),
  status                    TEXT DEFAULT 'active' CHECK (status IN ('active','paused','lapsed','cancelled')),
  coverage_pct              NUMERIC(4,3) NOT NULL,
  plan_cap_multiplier       INTEGER NOT NULL CHECK (plan_cap_multiplier IN (3,5,7)),
  weekly_premium            NUMERIC(8,2) NOT NULL,
  discount_weeks            INTEGER DEFAULT 0 CHECK (discount_weeks BETWEEN 0 AND 4),
  pause_count_qtr           INTEGER DEFAULT 0 CHECK (pause_count_qtr <= 2),
  weekly_payout_used        NUMERIC(8,2) DEFAULT 0,
  week_start_date           DATE NOT NULL,
  razorpay_mandate_id       TEXT,
  razorpay_fund_account_id  TEXT,
  experiment_group_id       TEXT,
  activated_at              TIMESTAMPTZ DEFAULT NOW(),
  cancelled_at              TIMESTAMPTZ,
  created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- POLICY PAUSES
-- ============================================================
CREATE TABLE IF NOT EXISTS policy_pauses (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_id   UUID REFERENCES policies(id) NOT NULL,
  start_date  DATE NOT NULL,
  end_date    DATE,
  reason      TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PLAN CONFIG (static lookup)
-- ============================================================
CREATE TABLE IF NOT EXISTS plan_config (
  plan             TEXT PRIMARY KEY,
  covered_triggers TEXT[] NOT NULL,
  base_premium     NUMERIC(8,2) NOT NULL,
  cap_multiplier   INTEGER NOT NULL
);

INSERT INTO plan_config (plan, covered_triggers, base_premium, cap_multiplier) VALUES
  ('basic',    ARRAY['rain','bandh','platform_down'],                         29.0, 3),
  ('standard', ARRAY['rain','bandh','platform_down','flood','aqi'],           49.0, 5),
  ('pro',      ARRAY['rain','bandh','platform_down','flood','aqi','heat'],    79.0, 7)
ON CONFLICT DO NOTHING;

-- ============================================================
-- TELEMETRY PINGS
-- ============================================================
CREATE TABLE IF NOT EXISTS telemetry_pings (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id        UUID REFERENCES riders(id) NOT NULL,
  latitude        NUMERIC(10,7) NOT NULL,
  longitude       NUMERIC(10,7) NOT NULL,
  h3_index_res9   TEXT NOT NULL,
  speed_kmh       NUMERIC(6,2),
  accuracy_m      NUMERIC(6,2),
  network_type    TEXT,
  is_bundle       BOOLEAN DEFAULT false,
  bundle_hash     TEXT,
  platform_status TEXT,
  session_active  BOOLEAN DEFAULT false,
  recorded_at     TIMESTAMPTZ NOT NULL,
  synced_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SHIFT STATES
-- ============================================================
CREATE TABLE IF NOT EXISTS shift_states (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id    UUID REFERENCES riders(id) NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('active','idle','offline')),
  started_at  TIMESTAMPTZ NOT NULL,
  ended_at    TIMESTAMPTZ,
  inferred_by TEXT NOT NULL CHECK (inferred_by IN ('gps','platform_api','app_session'))
);

-- ============================================================
-- TRIGGER EVENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS trigger_events (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trigger_type           TEXT NOT NULL CHECK (trigger_type IN ('rain','flood','heat','aqi','bandh','platform_down')),
  h3_index               TEXT NOT NULL,
  hub_id                 UUID REFERENCES hubs(id),
  oracle_score           NUMERIC(4,3),
  satellite_score        NUMERIC(4,3),
  weather_score          NUMERIC(4,3),
  traffic_score          NUMERIC(4,3),
  peer_score             NUMERIC(4,3),
  consensus_score        NUMERIC(4,3),
  accel_score            NUMERIC(4,3),
  weight_config          JSONB,
  raw_api_data           JSONB,
  status                 TEXT DEFAULT 'active' CHECK (status IN ('detected','active','resolving','resolved','cancelled')),
  cold_start_mode        BOOLEAN DEFAULT false,
  is_synthetic           BOOLEAN DEFAULT false,
  cooldown_active        BOOLEAN DEFAULT false,
  cooldown_payout_factor NUMERIC(4,3) DEFAULT 1.0,
  correlation_factor     NUMERIC(4,3) DEFAULT 1.0,
  city_trigger_count     INTEGER DEFAULT 1,
  vov_zone_certified     BOOLEAN DEFAULT false,
  vov_cert_score         NUMERIC(4,3),
  triggered_at           TIMESTAMPTZ DEFAULT NOW(),
  resolved_at            TIMESTAMPTZ
);

-- State machine enforcement for trigger_events
CREATE OR REPLACE FUNCTION validate_trigger_state_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.status = 'detected'  AND NEW.status != 'active'                     THEN RAISE EXCEPTION 'Invalid trigger transition: detected -> %', NEW.status; END IF;
  IF OLD.status = 'active'    AND NEW.status NOT IN ('resolving','cancelled') THEN RAISE EXCEPTION 'Invalid trigger transition: active -> %', NEW.status; END IF;
  IF OLD.status = 'resolving' AND NEW.status NOT IN ('resolved','active')     THEN RAISE EXCEPTION 'Invalid trigger transition: resolving -> %', NEW.status; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_trigger_state_machine ON trigger_events;
CREATE TRIGGER enforce_trigger_state_machine
  BEFORE UPDATE ON trigger_events
  FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
  EXECUTE FUNCTION validate_trigger_state_transition();

-- ============================================================
-- CLAIMS
-- ============================================================
CREATE TABLE IF NOT EXISTS claims (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id                    UUID REFERENCES riders(id) NOT NULL,
  policy_id                   UUID REFERENCES policies(id) NOT NULL,
  trigger_id                  UUID REFERENCES trigger_events(id) NOT NULL,
  idempotency_key             TEXT UNIQUE NOT NULL,
  status                      TEXT DEFAULT 'initiated' CHECK (status IN (
    'initiated','evaluating','auto_cleared','soft_flagged','hard_flagged',
    'manual_review','manual_approved','manual_rejected','manual_adjusted',
    'cap_exhausted','disputed','paid','rejected'
  )),
  fraud_score                 NUMERIC(4,3),
  oracle_confidence           NUMERIC(4,3),
  presence_confidence         NUMERIC(4,3),
  intent_factor1_gps          BOOLEAN,
  intent_factor2_session      BOOLEAN,
  intent_factor3_platform     BOOLEAN,
  intent_platform_unavailable BOOLEAN DEFAULT false,
  event_payout                NUMERIC(8,2),
  actual_payout               NUMERIC(8,2),
  confidence_adjusted_payout  NUMERIC(8,2),
  duration_hrs                NUMERIC(5,2),
  mu_time                     NUMERIC(3,2),
  explanation_text            TEXT,
  admin_trace                 JSONB,
  competing_triggers          JSONB,
  is_manual_override          BOOLEAN DEFAULT false,
  admin_action                TEXT,
  admin_id                    UUID,
  admin_action_at             TIMESTAMPTZ,
  admin_custom_amount         NUMERIC(8,2),
  admin_note                  TEXT,
  initiated_at                TIMESTAMPTZ DEFAULT NOW(),
  cleared_at                  TIMESTAMPTZ,
  paid_at                     TIMESTAMPTZ
);

-- ============================================================
-- PAYOUTS
-- ============================================================
CREATE TABLE IF NOT EXISTS payouts (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id         UUID REFERENCES claims(id),
  rider_id         UUID REFERENCES riders(id) NOT NULL,
  policy_id        UUID REFERENCES policies(id) NOT NULL,
  amount           NUMERIC(8,2) NOT NULL,
  payout_type      TEXT NOT NULL CHECK (payout_type IN (
    'initial','continuation','provisional','remainder','goodwill','vov_reward','premium_debit','refund'
  )),
  razorpay_ref     TEXT UNIQUE,
  razorpay_status  TEXT DEFAULT 'initiated' CHECK (razorpay_status IN (
    'initiated','processing','success','failed','reversed','circuit_breaker_hold'
  )),
  idempotency_key  TEXT UNIQUE NOT NULL,
  reconcile_status TEXT,
  released_at      TIMESTAMPTZ DEFAULT NOW(),
  reconciled_at    TIMESTAMPTZ
);

-- ============================================================
-- CLAIM EVIDENCE (VOV)
-- ============================================================
CREATE TABLE IF NOT EXISTS claim_evidence (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id                  UUID REFERENCES claims(id),
  rider_id                  UUID REFERENCES riders(id) NOT NULL,
  h3_index                  TEXT NOT NULL,
  video_url                 TEXT,
  exif_valid                BOOLEAN,
  cv_confidence             NUMERIC(4,3),
  gear_detected             BOOLEAN DEFAULT false,
  contributed_to_zone_cert  BOOLEAN DEFAULT false,
  ttl_delete_at             TIMESTAMPTZ,
  created_at                TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ZONE VOV CERTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS zone_vov_certs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  h3_index          TEXT NOT NULL,
  trigger_id        UUID REFERENCES trigger_events(id),
  submitted_count   INTEGER DEFAULT 0,
  confirmed_count   INTEGER DEFAULT 0,
  avg_cv_confidence NUMERIC(4,3),
  certified         BOOLEAN DEFAULT false,
  certified_at      TIMESTAMPTZ,
  expires_at        TIMESTAMPTZ,
  UNIQUE(h3_index, trigger_id)
);

-- ============================================================
-- DISPUTES
-- ============================================================
CREATE TABLE IF NOT EXISTS disputes (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id     UUID REFERENCES riders(id) NOT NULL,
  claim_id     UUID REFERENCES claims(id),
  reason_text  TEXT NOT NULL,
  status       TEXT DEFAULT 'open' CHECK (status IN ('open','under_review','resolved','rejected')),
  resolution   TEXT,
  sla_deadline TIMESTAMPTZ,
  resolved_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SYSTEM CONFIG (key-value store)
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO system_config (key, value) VALUES
  ('global_kill_switch',      'off'),
  ('oracle_threshold',        '0.65'),
  ('auto_clear_fs_threshold', '0.40'),
  ('hard_flag_fs_threshold',  '0.70'),
  ('lambda_floor',            '1.0'),
  ('capital_reserves',        '500000'),
  ('reserve_buffer_inr',      '500000'),
  ('p_base_margin_pct',       '0.25'),
  ('liquidity_mode',          'normal')
ON CONFLICT DO NOTHING;

-- ============================================================
-- EXPERIMENTS (A/B testing)
-- ============================================================
CREATE TABLE IF NOT EXISTS experiments (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parameter_name   TEXT NOT NULL,
  parameter_value  TEXT NOT NULL,
  group_id         TEXT NOT NULL DEFAULT 'all',
  active           BOOLEAN DEFAULT true,
  created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- LIQUIDITY SNAPSHOTS
-- ============================================================
CREATE TABLE IF NOT EXISTS liquidity_snapshots (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  razorpay_balance     NUMERIC(12,2),
  reserve_buffer       NUMERIC(12,2),
  available_cash       NUMERIC(12,2),
  expected_payouts_24h NUMERIC(12,2),
  liquidity_ratio      NUMERIC(8,4),
  mode                 TEXT,
  active_trigger_count INTEGER,
  pending_payouts_inr  NUMERIC(12,2),
  balance_stale        BOOLEAN DEFAULT false,
  created_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- METRICS TIMESERIES
-- ============================================================
CREATE TABLE IF NOT EXISTS metrics_timeseries (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  metric_name TEXT NOT NULL,
  value       NUMERIC NOT NULL,
  labels      JSONB,
  recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SEGMENT ECONOMICS (weekly snapshot)
-- ============================================================
CREATE TABLE IF NOT EXISTS segment_economics (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  city                TEXT NOT NULL,
  plan                TEXT NOT NULL,
  tier                TEXT NOT NULL,
  risk_profile        TEXT NOT NULL,
  week_start          DATE NOT NULL,
  active_policies     INTEGER,
  premiums_collected  NUMERIC(12,2),
  payouts_issued      NUMERIC(12,2),
  loss_ratio          NUMERIC(8,4),
  gross_margin        NUMERIC(12,2),
  UNIQUE(city, plan, tier, risk_profile, week_start)
);

-- ============================================================
-- RECONCILIATION REPORTS
-- ============================================================
CREATE TABLE IF NOT EXISTS reconciliation_reports (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  period        TEXT NOT NULL,
  total_payouts INTEGER,
  issues_found  BOOLEAN DEFAULT false,
  report_data   JSONB,
  run_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ADMIN AUDIT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_audit_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id     UUID,
  action       TEXT NOT NULL,
  entity_type  TEXT NOT NULL,
  entity_id    TEXT,
  diff         JSONB,
  performed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- WEBHOOK EVENTS (idempotency for Razorpay)
-- ============================================================
CREATE TABLE IF NOT EXISTS webhook_events (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id   TEXT UNIQUE NOT NULL,
  event_type TEXT NOT NULL,
  payload    JSONB,
  processed  BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- CRON LOCKS (prevent double-run for Monday cycle)
-- ============================================================
CREATE TABLE IF NOT EXISTS cron_locks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name    TEXT NOT NULL,
  week_start  DATE NOT NULL,
  locked_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(job_name, week_start)
);

-- ============================================================
-- CIRCUIT BREAKER EVENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS circuit_breaker_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  service       TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  failure_count INTEGER,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ORACLE API SNAPSHOTS (for backtesting)
-- ============================================================
CREATE TABLE IF NOT EXISTS oracle_api_snapshots (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  h3_index     TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  api_source   TEXT NOT NULL,
  raw_value    NUMERIC,
  signal_score NUMERIC(4,3),
  snapshot_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ENTITY STATE LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_state_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type     TEXT NOT NULL,
  entity_id       UUID NOT NULL,
  from_state      TEXT,
  to_state        TEXT NOT NULL,
  reason          TEXT,
  service_name    TEXT,
  transitioned_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SUPPORT MESSAGES
-- ============================================================
CREATE TABLE IF NOT EXISTS support_messages (
  id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id  UUID REFERENCES riders(id) NOT NULL,
  claim_id  UUID REFERENCES claims(id),
  direction TEXT NOT NULL CHECK (direction IN ('admin_to_rider','rider_to_admin')),
  message   TEXT NOT NULL,
  sent_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- BACKTEST RESULTS
-- ============================================================
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

-- ============================================================
-- STRESS TEST SCENARIOS
-- ============================================================
CREATE TABLE IF NOT EXISTS stress_test_scenarios (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  scenario_type TEXT NOT NULL,
  params        JSONB NOT NULL,
  last_result   JSONB,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- FRAUD CLUSTERS
-- ============================================================
CREATE TABLE IF NOT EXISTS fraud_clusters (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cluster_id         TEXT NOT NULL,
  rider_ids          UUID[] NOT NULL,
  detection_reason   TEXT,
  enrollment_ip      TEXT,
  device_fingerprint TEXT,
  detected_at        TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RIDER CONSENT LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS rider_consent_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rider_id    UUID REFERENCES riders(id) NOT NULL,
  action      TEXT NOT NULL,
  tos_version TEXT,
  ip_address  TEXT,
  consented_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ZONE RISK CACHE
-- ============================================================
CREATE TABLE IF NOT EXISTS zone_risk_cache (
  h3_index              TEXT PRIMARY KEY,
  vulnerability_idx     NUMERIC(4,3),
  confirmed_event_count INTEGER DEFAULT 0,
  cold_start_mode       BOOLEAN DEFAULT true,
  last_updated          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_telemetry_rider_time    ON telemetry_pings (rider_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_h3_time       ON telemetry_pings (h3_index_res9, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_claims_policy           ON claims (policy_id, initiated_at DESC);
CREATE INDEX IF NOT EXISTS idx_claims_trigger          ON claims (trigger_id);
CREATE INDEX IF NOT EXISTS idx_claims_status           ON claims (status) WHERE status NOT IN ('paid','rejected');
CREATE INDEX IF NOT EXISTS idx_claims_rider_status     ON claims (rider_id, status);
CREATE INDEX IF NOT EXISTS idx_policies_hub_status     ON policies (hub_id, status);
CREATE INDEX IF NOT EXISTS idx_policies_rider          ON policies (rider_id, status);
CREATE INDEX IF NOT EXISTS idx_trigger_h3_active       ON trigger_events (h3_index, status, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_trigger_hub_status      ON trigger_events (hub_id, status);
CREATE INDEX IF NOT EXISTS idx_payouts_rider_week      ON payouts (rider_id, released_at DESC);
CREATE INDEX IF NOT EXISTS idx_payouts_idempotency     ON payouts (idempotency_key);
CREATE INDEX IF NOT EXISTS idx_payouts_claim           ON payouts (claim_id);
CREATE INDEX IF NOT EXISTS idx_payouts_razorpay_ref    ON payouts (razorpay_ref);
CREATE INDEX IF NOT EXISTS idx_evidence_h3_trigger     ON claim_evidence (h3_index, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shift_rider_status      ON shift_states (rider_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_hubs_geom               ON hubs USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_hubs_h3                 ON hubs (h3_index_res9);
CREATE INDEX IF NOT EXISTS idx_metrics_name_time       ON metrics_timeseries (metric_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_snapshots_h3_time ON oracle_api_snapshots (h3_index, trigger_type, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_scores_rider       ON rider_risk_scores (rider_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_events_id       ON webhook_events (event_id);

-- ============================================================
-- ROW LEVEL SECURITY (enable on rider-facing tables)
-- ============================================================
ALTER TABLE riders         ENABLE ROW LEVEL SECURITY;
ALTER TABLE policies       ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims         ENABLE ROW LEVEL SECURITY;
ALTER TABLE payouts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_pings ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE disputes       ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS
CREATE POLICY "service_role_all" ON riders         USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON policies       USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON claims         USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON payouts        USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON telemetry_pings USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON claim_evidence USING (auth.role() = 'service_role');
CREATE POLICY "service_role_all" ON disputes       USING (auth.role() = 'service_role');
