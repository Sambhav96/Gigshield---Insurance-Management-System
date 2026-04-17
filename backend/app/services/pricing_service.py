"""
services/pricing_service.py — AUDIT FIXED

BUG-03 FIX: vulnerability_idx now reads from zone_risk_cache.vulnerability_idx
            (zone-level ML prediction), not risk_score/100

BUG-04 FIX: recent_trigger_factor now filters AND oracle_score >= 0.70
            and includes the 3-of-4-weeks personal rider multiplier (GAP-07)

CODE-02 FIX: compute_vulnerability_index renamed / replaced with get_zone_vulnerability

P_final = P_base × city_multiplier × λ × β × risk_multiplier × recent_trigger_factor
P_base  = (vulnerability_idx × effective_income × coverage_pct × 0.50) × margin
λ       = MIN(MAX(λ_floor, 1.0 + active/capacity), 2.0)
β       = 1.0 - (0.05 × discount_weeks)  [freeze-aware]
"""
from __future__ import annotations

import asyncpg

from app.utils.mu_table import (
    PLAN_TRIGGERS, PLAN_CAP_MULTIPLIER, PLAN_BASE_PREMIUM,
    get_plan_coverage, get_mu, get_mu_label,
)

RISK_MULTIPLIERS    = {"low": 0.95, "medium": 1.00, "high": 1.15}
P_BASE_MARGIN_DEFAULT = 1.25   # read from system_config at runtime
LAMBDA_FLOOR_DEFAULT  = 1.0


async def get_zone_vulnerability(conn: asyncpg.Connection, h3_index: str) -> float:
    """
    BUG-03 FIX: Read from zone_risk_cache.vulnerability_idx (ML model output).
    Falls back to 0.50 (neutral) if zone not yet in cache.
    """
    val = await conn.fetchval(
        "SELECT vulnerability_idx FROM zone_risk_cache WHERE h3_index = $1",
        h3_index,
    )
    if val is not None:
        return float(val)
    # Zone not in cache — insert default and return 0.50
    await conn.execute(
        """
        INSERT INTO zone_risk_cache (h3_index, vulnerability_idx, cold_start_mode)
        VALUES ($1, 0.50, true)
        ON CONFLICT (h3_index) DO NOTHING
        """,
        h3_index,
    )
    return 0.50


def compute_vulnerability_index(risk_score: float) -> float:
    """Legacy helper: convert rider risk score (0-100) to vulnerability index (0-1)."""
    return round(max(0.0, min(float(risk_score), 100.0)) / 100.0, 4)


def compute_p_base(
    effective_income: float,
    coverage_pct: float,
    vulnerability_idx: float,
    margin: float = P_BASE_MARGIN_DEFAULT,
) -> float:
    """P_base = (vulnerability_idx × effective_income × coverage_pct × 0.50) × margin"""
    return (vulnerability_idx * effective_income * coverage_pct * 0.50) * margin


def compute_lambda(
    active_policies_in_hub: int,
    hub_capacity: int,
    lambda_floor: float = LAMBDA_FLOOR_DEFAULT,
) -> float:
    """λ = MIN(MAX(λ_floor, 1.0 + active/capacity), 2.0)"""
    raw = 1.0 + (active_policies_in_hub / max(hub_capacity, 1))
    return round(min(max(lambda_floor, raw), 2.0), 4)


def compute_beta(discount_weeks: int) -> float:
    """β = 1.0 − (0.05 × discount_weeks). Floor at 0.80."""
    return max(0.80, 1.0 - (0.05 * min(discount_weeks, 4)))


def compute_recent_trigger_factor(recent_events_count: int) -> float:
    """Legacy helper: +5% per recent event, capped at 1.40."""
    return round(min(1.0 + int(recent_events_count) * 0.05, 1.40), 4)


async def compute_recent_trigger_factor_db(
    conn: asyncpg.Connection,
    hub_id: str,
    rider_id: str,
) -> float:
    """
    BUG-04 + GAP-07 FIX:
    Zone factor: MIN(1.0 + count_30d × 0.05, 1.40) WHERE oracle_score >= 0.70
    Rider factor: ×1.10 if rider claimed in 3 of last 4 weeks (§5.1)
    """
    # Zone-level factor with oracle_score filter
    confirmed_events_30d = await conn.fetchval(
        """
        SELECT COUNT(*) FROM trigger_events
        WHERE hub_id = $1
          AND status = 'resolved'
          AND oracle_score >= 0.70
          AND triggered_at >= NOW() - INTERVAL '30 days'
        """,
        hub_id,
    ) or 0
    zone_factor = min(1.0 + int(confirmed_events_30d) * 0.05, 1.40)

    # Rider personal factor: 3 of last 4 weeks with a claim
    weeks_with_claims = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT date_trunc('week', initiated_at))
        FROM claims
        WHERE rider_id = $1
          AND initiated_at >= NOW() - INTERVAL '28 days'
          AND status NOT IN ('rejected', 'manual_rejected', 'cap_exhausted')
        """,
        rider_id,
    ) or 0
    rider_multiplier = 1.10 if int(weeks_with_claims) >= 3 else 1.00

    return round(zone_factor * rider_multiplier, 4)


def compute_p_final(
    effective_income: float,
    coverage_pct: float,
    vulnerability_idx: float,
    city_multiplier: float,
    lambda_val: float,
    beta: float,
    risk_profile: str,
    recent_trigger_factor: float,
    margin: float = P_BASE_MARGIN_DEFAULT,
) -> float:
    p_base    = compute_p_base(effective_income, coverage_pct, vulnerability_idx, margin)
    risk_mult = RISK_MULTIPLIERS.get(risk_profile, 1.00)
    return round(p_base * city_multiplier * lambda_val * beta * risk_mult * recent_trigger_factor, 2)


async def get_premium_quote(
    conn: asyncpg.Connection,
    rider_id: str,
    plan: str,
    hub_id: str,
) -> dict:
    """Full premium quote with all spec-correct formula components."""
    import uuid
    rider = await conn.fetchrow("SELECT * FROM riders WHERE id = $1", uuid.UUID(rider_id))
    hub   = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1",   uuid.UUID(hub_id))
    if not rider or not hub:
        raise ValueError("Rider or hub not found")

    tier             = rider["tier"]
    coverage_pct     = get_plan_coverage(plan, tier)
    risk_profile     = rider["risk_profile"]
    effective_income = float(rider["effective_income"])
    discount_weeks   = 0

    existing = await conn.fetchrow(
        "SELECT discount_weeks, beta_freeze_until FROM policies WHERE rider_id=$1 AND status='active' LIMIT 1",
        uuid.UUID(rider_id),
    )
    if existing:
        discount_weeks = existing["discount_weeks"]
        # Freeze check
        if existing.get("beta_freeze_until"):
            freeze_until = existing["beta_freeze_until"]
            db_now = await conn.fetchval("SELECT NOW()")
            if db_now < freeze_until:
                discount_weeks = 0  # frozen — no discount

    # BUG-03 FIX: zone vulnerability from ML cache
    h3_index      = hub["h3_index_res9"]
    vuln_idx      = await get_zone_vulnerability(conn, h3_index)
    city_mult     = float(hub["city_multiplier"])
    hub_capacity  = hub["capacity"] or 100

    active_count = await conn.fetchval(
        "SELECT COUNT(*) FROM policies WHERE hub_id=$1 AND status='active'",
        uuid.UUID(hub_id),
    ) or 0

    # λ_floor from system_config (written by loss ratio guardrail)
    lambda_floor_row = await conn.fetchrow(
        "SELECT value::float FROM system_config WHERE key='lambda_floor'"
    )
    lambda_floor = float(lambda_floor_row["value"]) if lambda_floor_row else LAMBDA_FLOOR_DEFAULT

    # p_base_margin from system_config (written by RED loss ratio guardrail)
    margin_row = await conn.fetchrow(
        "SELECT value::float FROM system_config WHERE key='p_base_margin_pct'"
    )
    margin = float(margin_row["value"]) if margin_row else P_BASE_MARGIN_DEFAULT

    lambda_val     = compute_lambda(int(active_count), hub_capacity, lambda_floor)
    beta           = compute_beta(discount_weeks)
    risk_mult      = RISK_MULTIPLIERS.get(risk_profile, 1.00)
    recent_factor  = await compute_recent_trigger_factor_db(conn, hub_id, rider_id)

    p_final    = compute_p_final(
        effective_income, coverage_pct, vuln_idx, city_mult,
        lambda_val, beta, risk_profile, recent_factor, margin,
    )
    p_final    = max(p_final, PLAN_BASE_PREMIUM[plan])
    weekly_cap = effective_income * PLAN_CAP_MULTIPLIER[plan]

    example_mu       = get_mu(19)
    example_payout   = effective_income * coverage_pct * (2.0 / 8) * example_mu

    return {
        "plan": plan, "daily_income": effective_income,
        "p_base": round(compute_p_base(effective_income, coverage_pct, vuln_idx, margin), 2),
        "vulnerability_idx": vuln_idx,
        "city_multiplier": city_mult, "lambda_val": lambda_val,
        "beta": beta, "risk_multiplier": risk_mult,
        "recent_trigger_factor": recent_factor, "p_final": p_final,
        "discount_weeks": discount_weeks, "weekly_cap": weekly_cap,
        "coverage_pct": coverage_pct, "triggers_covered": PLAN_TRIGGERS[plan],
        "expected_payout_example": {"duration_hrs": 2.0, "mu": example_mu, "amount": round(example_payout, 2)},
    }
