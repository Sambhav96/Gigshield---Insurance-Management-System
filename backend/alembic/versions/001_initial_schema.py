"""initial_schema — complete GigShield database schema

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-15 00:00:00.000000

Covers ALL tables from spec Section 2.1 plus audit-required additions:
  - riders, hubs, policies, policy_pauses
  - telemetry_pings, shift_states, trigger_events
  - claims, payouts, claim_evidence, zone_vov_certs
  - disputes, zone_risk_cache, liquidity_snapshots
  - metrics_timeseries, segment_economics, experiments, message_experiments
  - notifications, admin_audit_log
  - admin_users, hub_manager_users (auth tables)
  - fraud_clusters, blacklisted_devices (CRITICAL-03 fix)
  - oracle_api_snapshots, system_config (referenced in code, missing before)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── hubs (referenced by riders FK, so create first) ─────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS hubs (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name                TEXT NOT NULL,
        platform            TEXT NOT NULL,
        city                TEXT NOT NULL,
        latitude            NUMERIC(10,7) NOT NULL,
        longitude           NUMERIC(10,7) NOT NULL,
        h3_index_res9       TEXT NOT NULL,
        h3_index_res8       TEXT NOT NULL,
        radius_km           NUMERIC(4,2) DEFAULT 2.0,
        capacity            INTEGER DEFAULT 100,
        city_multiplier     NUMERIC(4,3) NOT NULL DEFAULT 1.0,
        drainage_index      NUMERIC(4,3) DEFAULT 0.5,
        rain_threshold_mm   NUMERIC(5,2) DEFAULT 35.0,
        api_key             TEXT,
        geom                TEXT,
        created_at          TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── admin_users ──────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS admin_users (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username        TEXT UNIQUE NOT NULL,
        password_hash   TEXT NOT NULL,
        email           TEXT,
        role            TEXT DEFAULT 'admin' CHECK (role IN ('admin','super_admin','analyst')),
        is_active       BOOLEAN DEFAULT true,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── hub_manager_users ────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS hub_manager_users (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        hub_id          UUID REFERENCES hubs(id) NOT NULL,
        username        TEXT UNIQUE NOT NULL,
        password_hash   TEXT NOT NULL,
        display_name    TEXT,
        is_active       BOOLEAN DEFAULT true,
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── riders ───────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS riders (
        id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name                        TEXT,
        phone                       TEXT UNIQUE,
        email                       TEXT UNIQUE,
        password_hash               TEXT,
        supabase_user_id            TEXT UNIQUE,
        aadhaar_hash                TEXT,
        pan_hash                    TEXT,
        platform                    TEXT NOT NULL DEFAULT 'zepto'
                                        CHECK (platform IN ('zepto','blinkit','instamart')),
        city                        TEXT NOT NULL DEFAULT 'Mumbai',
        hub_id                      UUID REFERENCES hubs(id),
        declared_income             NUMERIC(8,2) NOT NULL DEFAULT 500.0,
        effective_income            NUMERIC(8,2) NOT NULL DEFAULT 500.0,
        telemetry_inferred_income   NUMERIC(8,2),
        income_verified_at          TIMESTAMPTZ,
        razorpay_fund_account_id    TEXT,
        tier                        TEXT DEFAULT 'B' CHECK (tier IN ('A','B')),
        risk_score                  INTEGER DEFAULT 50 CHECK (risk_score BETWEEN 0 AND 100),
        risk_profile                TEXT DEFAULT 'medium'
                                        CHECK (risk_profile IN ('low','medium','high')),
        device_fingerprint          TEXT,
        bank_account_hash           TEXT,
        phone_verified              BOOLEAN DEFAULT false,
        enrollment_ip_prefix        TEXT,
        syndicate_suspect_group_id  TEXT,
        experiment_group_id         TEXT DEFAULT 'control',
        created_at                  TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── policies ─────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rider_id                    UUID REFERENCES riders(id) NOT NULL,
        hub_id                      UUID REFERENCES hubs(id) NOT NULL,
        plan                        TEXT NOT NULL CHECK (plan IN ('basic','standard','pro')),
        status                      TEXT DEFAULT 'active'
                                        CHECK (status IN ('active','paused','lapsed','cancelled')),
        coverage_pct                NUMERIC(4,3) NOT NULL,
        plan_cap_multiplier         INTEGER NOT NULL CHECK (plan_cap_multiplier IN (3,5,7)),
        weekly_premium              NUMERIC(8,2) NOT NULL,
        razorpay_fund_account_id    TEXT,
        discount_weeks              INTEGER DEFAULT 0 CHECK (discount_weeks BETWEEN 0 AND 4),
        pause_count_qtr             INTEGER DEFAULT 0 CHECK (pause_count_qtr <= 2),
        weekly_payout_used          NUMERIC(8,2) DEFAULT 0,
        week_start_date             DATE NOT NULL DEFAULT CURRENT_DATE,
        razorpay_mandate_id         TEXT,
        experiment_group_id         TEXT,
        activated_at                TIMESTAMPTZ DEFAULT NOW(),
        cancelled_at                TIMESTAMPTZ,
        created_at                  TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── policy_pauses ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS policy_pauses (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        policy_id   UUID REFERENCES policies(id) NOT NULL,
        start_date  DATE NOT NULL,
        end_date    DATE,
        reason      TEXT,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── telemetry_pings ──────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS telemetry_pings (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rider_id        UUID REFERENCES riders(id) NOT NULL,
        latitude        NUMERIC(10,7) NOT NULL,
        longitude       NUMERIC(10,7) NOT NULL,
        h3_index_res9   TEXT NOT NULL DEFAULT 'unknown',
        speed_kmh       NUMERIC(6,2),
        accuracy_m      NUMERIC(6,2),
        network_type    TEXT,
        is_bundle       BOOLEAN DEFAULT false,
        bundle_hash     TEXT,
        platform_status TEXT,
        session_active  BOOLEAN DEFAULT false,
        recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        synced_at       TIMESTAMPTZ DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_rider_recorded ON telemetry_pings(rider_id, recorded_at DESC)")

    # ── shift_states ─────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS shift_states (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rider_id    UUID REFERENCES riders(id) NOT NULL,
        status      TEXT NOT NULL CHECK (status IN ('active','idle','offline')),
        started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ended_at    TIMESTAMPTZ,
        inferred_by TEXT NOT NULL DEFAULT 'gps'
                        CHECK (inferred_by IN ('gps','platform_api','app_session'))
    )
    """)

    # ── trigger_events ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS trigger_events (
        id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        trigger_type            TEXT NOT NULL
                                    CHECK (trigger_type IN ('rain','flood','heat','aqi','bandh','platform_down')),
        h3_index                TEXT NOT NULL,
        hub_id                  UUID REFERENCES hubs(id),
        oracle_score            NUMERIC(4,3),
        satellite_score         NUMERIC(4,3),
        weather_score           NUMERIC(4,3),
        traffic_score           NUMERIC(4,3),
        peer_score              NUMERIC(4,3),
        consensus_score         NUMERIC(4,3),
        accel_score             NUMERIC(4,3),
        weight_config           JSONB,
        raw_api_data            JSONB,
        status                  TEXT DEFAULT 'detected'
                                    CHECK (status IN ('detected','active','resolving','resolved','cancelled')),
        cold_start_mode         BOOLEAN DEFAULT false,
        is_synthetic            BOOLEAN DEFAULT false,
        cooldown_active         BOOLEAN DEFAULT false,
        cooldown_payout_factor  NUMERIC(4,3) DEFAULT 1.0,
        correlation_factor      NUMERIC(4,3) DEFAULT 1.0,
        city_trigger_count      INTEGER DEFAULT 1,
        vov_zone_certified      BOOLEAN DEFAULT false,
        vov_cert_score          NUMERIC(4,3),
        triggered_at            TIMESTAMPTZ DEFAULT NOW(),
        resolved_at             TIMESTAMPTZ
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_triggers_h3_status ON trigger_events(h3_index, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_triggers_triggered_at ON trigger_events(triggered_at DESC)")

    # ── claims ───────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rider_id                    UUID REFERENCES riders(id) NOT NULL,
        policy_id                   UUID REFERENCES policies(id) NOT NULL,
        trigger_id                  UUID REFERENCES trigger_events(id) NOT NULL,
        idempotency_key             TEXT UNIQUE NOT NULL,
        status                      TEXT DEFAULT 'initiated'
                                        CHECK (status IN (
                                            'initiated','evaluating','auto_cleared','soft_flagged',
                                            'hard_flagged','manual_review','manual_approved',
                                            'manual_rejected','manual_adjusted','cap_exhausted',
                                            'disputed','paid','rejected'
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
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_rider_id ON claims(rider_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status)")

    # ── payouts ──────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS payouts (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        claim_id            UUID REFERENCES claims(id),
        rider_id            UUID REFERENCES riders(id) NOT NULL,
        policy_id           UUID REFERENCES policies(id) NOT NULL,
        amount              NUMERIC(8,2) NOT NULL,
        payout_type         TEXT NOT NULL CHECK (payout_type IN (
                                'initial','continuation','provisional','remainder',
                                'goodwill','vov_reward','premium_debit','refund'
                            )),
        razorpay_ref        TEXT UNIQUE,
        razorpay_status     TEXT DEFAULT 'initiated'
                                CHECK (razorpay_status IN (
                                    'initiated','processing','success','failed',
                                    'reversed','circuit_breaker_hold'
                                )),
        idempotency_key     TEXT UNIQUE NOT NULL,
        reconcile_status    TEXT,
        released_at         TIMESTAMPTZ DEFAULT NOW(),
        reconciled_at       TIMESTAMPTZ
    )
    """)

    # ── claim_evidence (VOV) ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS claim_evidence (
        id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        claim_id                    UUID REFERENCES claims(id) NOT NULL,
        rider_id                    UUID REFERENCES riders(id) NOT NULL,
        h3_index                    TEXT NOT NULL DEFAULT 'unknown',
        video_url                   TEXT,
        exif_gps_lat                NUMERIC(10,7),
        exif_gps_lng                NUMERIC(10,7),
        exif_timestamp              TIMESTAMPTZ,
        exif_valid                  BOOLEAN,
        integrity_valid             BOOLEAN,
        cv_confidence               NUMERIC(4,3),
        cv_classes                  TEXT[],
        gear_detected               BOOLEAN DEFAULT false,
        contributed_to_zone_cert    BOOLEAN DEFAULT false,
        vov_reward_issued           BOOLEAN DEFAULT false,
        vov_reward_amount           NUMERIC(6,2),
        ttl_delete_at               TIMESTAMPTZ,
        created_at                  TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── zone_vov_certs ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS zone_vov_certs (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        h3_index            TEXT NOT NULL,
        trigger_id          UUID REFERENCES trigger_events(id) NOT NULL,
        submitted_count     INTEGER NOT NULL DEFAULT 0,
        confirmed_count     INTEGER NOT NULL DEFAULT 0,
        avg_cv_confidence   NUMERIC(4,3),
        certified           BOOLEAN DEFAULT false,
        certified_at        TIMESTAMPTZ,
        expires_at          TIMESTAMPTZ,
        created_at          TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── disputes ─────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS disputes (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        claim_id        UUID REFERENCES claims(id) NOT NULL,
        rider_id        UUID REFERENCES riders(id) NOT NULL,
        reason_text     TEXT NOT NULL,
        status          TEXT DEFAULT 'open'
                            CHECK (status IN ('open','resolved_upheld','resolved_rejected','escalated')),
        resolution_note TEXT,
        goodwill_credit NUMERIC(8,2),
        sla_deadline    TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '72 hours'),
        escalated       BOOLEAN DEFAULT false,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        resolved_at     TIMESTAMPTZ
    )
    """)

    # ── zone_risk_cache ──────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS zone_risk_cache (
        h3_index              TEXT PRIMARY KEY,
        vulnerability_idx     NUMERIC(4,3) DEFAULT 0.5,
        active_policies       INTEGER DEFAULT 0,
        lambda_surge          NUMERIC(4,3) DEFAULT 1.0,
        confirmed_event_count INTEGER DEFAULT 0,
        cold_start_mode       BOOLEAN DEFAULT true,
        last_updated          TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── liquidity_snapshots ──────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS liquidity_snapshots (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        razorpay_balance  NUMERIC(12,2) DEFAULT 0,
        reserve_buffer    NUMERIC(12,2) DEFAULT 0,
        available_cash    NUMERIC(12,2) DEFAULT 0,
        expected_24h      NUMERIC(12,2) DEFAULT 0,
        liquidity_ratio   NUMERIC(6,4) DEFAULT 0,
        mode              TEXT DEFAULT 'normal',
        snapshot_at       TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── metrics_timeseries ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS metrics_timeseries (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        metric_name TEXT NOT NULL,
        value       NUMERIC,
        labels      JSONB,
        recorded_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_metrics_name_time ON metrics_timeseries(metric_name, recorded_at DESC)")

    # ── segment_economics ────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS segment_economics (
        id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        week_start            DATE NOT NULL,
        city                  TEXT NOT NULL,
        plan                  TEXT NOT NULL,
        tier                  TEXT NOT NULL,
        risk_profile          TEXT NOT NULL,
        active_policies       INTEGER,
        premiums_collected    NUMERIC(12,2),
        payouts_issued        NUMERIC(12,2),
        loss_ratio            NUMERIC(6,4),
        gross_margin          NUMERIC(12,2),
        fraud_flags           INTEGER,
        vov_participants      INTEGER
    )
    """)

    # ── experiments ──────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS experiments (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name              TEXT NOT NULL,
        parameter_name    TEXT NOT NULL,
        parameter_value   JSONB NOT NULL,
        group_id          TEXT NOT NULL,
        active            BOOLEAN DEFAULT true,
        set_by_admin_id   UUID,
        activated_at      TIMESTAMPTZ DEFAULT NOW(),
        deactivated_at    TIMESTAMPTZ
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS message_experiments (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        experiment_name   TEXT NOT NULL,
        group_id          TEXT NOT NULL,
        message_key       TEXT NOT NULL,
        message_template  TEXT NOT NULL,
        active            BOOLEAN DEFAULT true,
        created_at        TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── notifications ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rider_id      UUID REFERENCES riders(id) NOT NULL,
        type          TEXT NOT NULL,
        channel       TEXT NOT NULL CHECK (channel IN ('push','sms','whatsapp')),
        message       TEXT NOT NULL,
        status        TEXT DEFAULT 'pending'
                          CHECK (status IN ('pending','sent','delivered','failed')),
        attempt_count INTEGER DEFAULT 0,
        sent_at       TIMESTAMPTZ,
        delivered_at  TIMESTAMPTZ,
        failed_at     TIMESTAMPTZ,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── admin_audit_log ──────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS admin_audit_log (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        admin_id        UUID NOT NULL,
        action          TEXT NOT NULL,
        action_type     TEXT,
        entity_type     TEXT,
        entity_id       TEXT,
        payload         JSONB,
        diff            JSONB,
        performed_at    TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # ── fraud_clusters (CRITICAL-03 fix) ─────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS fraud_clusters (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cluster_id          TEXT UNIQUE NOT NULL,
        cluster_type        TEXT NOT NULL DEFAULT 'ip_prefix_cluster',
        rider_ids           UUID[] NOT NULL DEFAULT '{}',
        detection_reason    TEXT,
        enrollment_ip_prefix TEXT,
        status              TEXT DEFAULT 'suspected'
                                CHECK (status IN ('suspected','confirmed','cleared')),
        flagged_at          TIMESTAMPTZ DEFAULT NOW(),
        reviewed_at         TIMESTAMPTZ,
        reviewed_by         UUID
    )
    """)

    # ── blacklisted_devices (CRITICAL-03 fix) ────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS blacklisted_devices (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        device_fingerprint  TEXT UNIQUE NOT NULL,
        reason              TEXT,
        blacklisted_at      TIMESTAMPTZ DEFAULT NOW(),
        blacklisted_by      UUID
    )
    """)

    # ── oracle_api_snapshots ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS oracle_api_snapshots (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        h3_index        TEXT NOT NULL,
        trigger_type    TEXT NOT NULL,
        api_source      TEXT NOT NULL,
        raw_payload     JSONB,
        score           NUMERIC(4,3),
        fetched_at      TIMESTAMPTZ DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_oracle_snaps_h3_time ON oracle_api_snapshots(h3_index, fetched_at DESC)")

    # ── system_config ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS system_config (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        description TEXT,
        updated_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_by  UUID
    )
    """)

    # ── Seed default system_config ────────────────────────────────────────────
    op.execute("""
    INSERT INTO system_config (key, value, description) VALUES
        ('global_kill_switch', 'off', 'Global kill switch: off | triggers_only | payouts_only | full'),
        ('oracle_cycle_interval_min', '15', 'Oracle evaluation interval in minutes'),
        ('payout_cooldown_hours', '24', 'Cooldown between payouts for same trigger type'),
        ('fraud_score_hard_threshold', '0.80', 'Fraud score above which claims are hard-flagged'),
        ('vov_reward_amount_inr', '10.00', 'VOV video reward in INR'),
        ('ml_retrain_interval_days', '30', 'Days between ML model retrains')
    ON CONFLICT (key) DO NOTHING
    """)

    # ── Seed default admin user (password: Admin@GigShield2026) ──────────────
    # bcrypt hash of 'Admin@GigShield2026'
    op.execute("""
    INSERT INTO admin_users (username, password_hash, email, role)
    VALUES (
        'admin',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iUM2',
        'admin@gigshield.in',
        'super_admin'
    )
    ON CONFLICT (username) DO NOTHING
    """)

    # ── Seed demo hub ────────────────────────────────────────────────────────
    op.execute("""
    INSERT INTO hubs (id, name, platform, city, latitude, longitude, h3_index_res9, h3_index_res8, city_multiplier)
    VALUES (
        '00000000-0000-0000-0000-000000000001',
        'Mumbai Central Hub',
        'blinkit',
        'Mumbai',
        19.0760, 72.8777,
        '8929b1aa3ffffff',
        '8829b1aa3ffffff',
        1.1
    )
    ON CONFLICT (id) DO NOTHING
    """)

    # ── Seed demo hub manager user (password: Hub@GigShield2026) ─────────────
    op.execute("""
    INSERT INTO hub_manager_users (hub_id, username, password_hash, display_name)
    VALUES (
        '00000000-0000-0000-0000-000000000001',
        'hub_manager',
        '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iUM2',
        'Mumbai Hub Manager'
    )
    ON CONFLICT (username) DO NOTHING
    """)


def downgrade() -> None:
    tables = [
        "blacklisted_devices", "fraud_clusters", "admin_audit_log",
        "notifications", "message_experiments", "experiments",
        "segment_economics", "metrics_timeseries", "liquidity_snapshots",
        "zone_risk_cache", "disputes", "zone_vov_certs", "claim_evidence",
        "payouts", "claims", "trigger_events", "shift_states",
        "telemetry_pings", "policy_pauses", "policies",
        "oracle_api_snapshots", "system_config",
        "hub_manager_users", "admin_users", "riders", "hubs",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")


def upgrade_v2() -> None:
    """Additional columns added in v2 (called from upgrade if not exists)."""
    # Referral columns on riders
    op.execute("""
    ALTER TABLE riders
        ADD COLUMN IF NOT EXISTS referral_code_used TEXT,
        ADD COLUMN IF NOT EXISTS referred_by UUID REFERENCES riders(id),
        ADD COLUMN IF NOT EXISTS latitude NUMERIC(10,7),
        ADD COLUMN IF NOT EXISTS longitude NUMERIC(10,7),
        ADD COLUMN IF NOT EXISTS fcm_token TEXT,
        ADD COLUMN IF NOT EXISTS annual_payout_total NUMERIC(12,2) DEFAULT 0;
    """)

    # Hub B2B API key column (already TEXT in migration, but add index)
    op.execute("CREATE INDEX IF NOT EXISTS idx_hubs_api_key ON hubs(api_key) WHERE api_key IS NOT NULL")

    # Experiment rollback column
    op.execute("""
    ALTER TABLE experiments
        ADD COLUMN IF NOT EXISTS rollback_value TEXT,
        ADD COLUMN IF NOT EXISTS created_by UUID;
    """)

    # Reconciliation reports table
    op.execute("""
    CREATE TABLE IF NOT EXISTS reconciliation_reports (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        run_at          TIMESTAMPTZ DEFAULT NOW(),
        mismatches      INTEGER DEFAULT 0,
        auto_fixed      INTEGER DEFAULT 0,
        manual_review   INTEGER DEFAULT 0,
        report_json     JSONB
    )
    """)

    # Experiment configs table (for bounds enforcement)
    op.execute("""
    CREATE TABLE IF NOT EXISTS experiment_configs (
        key     TEXT PRIMARY KEY,
        value   TEXT,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)
