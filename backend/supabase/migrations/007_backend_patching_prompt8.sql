-- Migration 007 — Backend patching support for Prompt 8
-- Safe to re-run.

-- 1) Hub manager auth table
CREATE TABLE IF NOT EXISTS hub_manager_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hub_id UUID REFERENCES hubs(id) UNIQUE,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Demo seed: one hub manager per existing hub.
-- Password hash corresponds to: Hub@123
INSERT INTO hub_manager_users (hub_id, username, password_hash)
SELECT h.id, CONCAT('hub_', LOWER(REPLACE(h.city, ' ', '_')), '_', ROW_NUMBER() OVER (ORDER BY h.created_at, h.id)),
       '$2b$12$Qv3QhLr/9n0Q8H9lQNoYh.47fK17m6nF2f2mA8FJx2g77QJVK3rAu'
FROM hubs h
ON CONFLICT (hub_id) DO NOTHING;

-- 2) Rider payout destination storage
ALTER TABLE riders ADD COLUMN IF NOT EXISTS razorpay_fund_account_id TEXT;

-- 3) Experiment configs table for admin config endpoint
CREATE TABLE IF NOT EXISTS experiment_configs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed from system config if empty
INSERT INTO experiment_configs (key, value)
SELECT key, value
FROM system_config
WHERE key IN (
  'oracle_threshold',
  'auto_clear_fs_threshold',
  'hard_flag_fs_threshold',
  'single_event_cap_pct',
  'lambda_floor',
  'risk_profile_high_mult',
  'vov_reward_individual',
  'discount_per_clean_week',
  'max_discount_weeks',
  'confidence_band_1_factor',
  'confidence_band_2_factor',
  'daily_soft_limit_divisor',
  'vov_reward_zone_cert',
  'p_base_margin_pct'
)
ON CONFLICT (key) DO NOTHING;
