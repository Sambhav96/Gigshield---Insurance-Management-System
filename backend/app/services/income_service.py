"""
services/income_service.py — AUDIT FIXED

GAP-02 FIX: platform_reported_avg now included in effective_income formula.
CODE-03 FIX: 1.20 buffer applies ONLY to telemetry_inferred, not platform_reported.

Spec §4.3 formula:
  effective_income = MIN(
    declared_income,
    platform_reported_avg,            ← no buffer
    telemetry_inferred_income × 1.20  ← 20% buffer for undercount
  )
  If no telemetry or platform data: MIN(declared, city_median)
"""
from __future__ import annotations

import uuid
import asyncpg
import structlog

from app.utils.mu_table import get_city_median_income, get_city_avg_order_value
from app.external.platform_adapter import get_rider_platform_status

log = structlog.get_logger()


async def compute_effective_income(conn: asyncpg.Connection, rider_id: str) -> float:
    """
    Spec §4.3 — effective_income = MIN(declared, platform_reported, telemetry×1.20).
    Falls back to MIN(declared, city_median) for new riders.
    """
    rider = await conn.fetchrow("SELECT * FROM riders WHERE id=$1", uuid.UUID(rider_id))
    if not rider:
        return 0.0

    declared     = float(rider["declared_income"])
    city         = rider["city"]
    city_median  = get_city_median_income(city)
    candidates   = [declared]

    # Platform-reported average (no 1.20 buffer — spec says use directly)
    platform_reported = rider.get("platform_reported_income")
    if platform_reported and float(platform_reported) > 0:
        candidates.append(float(platform_reported))

    # Telemetry-inferred × 1.20 buffer
    telemetry_inferred = rider.get("telemetry_inferred_income")
    if telemetry_inferred and float(telemetry_inferred) > 0:
        candidates.append(float(telemetry_inferred) * 1.20)
    else:
        # New rider — cap at city median
        candidates.append(city_median)

    effective = min(candidates)
    effective = max(effective, 300.0)  # floor ₹300/day
    return round(effective, 2)


async def infer_income_from_telemetry(
    conn: asyncpg.Connection, rider_id: str, lookback_days: int = 7
) -> float:
    """Estimate income from shift hours × delivery rate × city order value."""
    rider = await conn.fetchrow("SELECT city FROM riders WHERE id=$1", uuid.UUID(rider_id))
    if not rider:
        return 0.0

    city_order_value = get_city_avg_order_value(rider["city"])

    summary = await conn.fetchrow(
        f"""
        SELECT
            COUNT(*)::float AS total_pings,
            COUNT(DISTINCT recorded_at::date)::float AS active_days
        FROM telemetry_pings
        WHERE rider_id=$1
          AND recorded_at >= NOW() - INTERVAL '{lookback_days} days'
        """,
        uuid.UUID(rider_id),
    )
    if not summary or not summary["active_days"]:
        return 0.0

    pings_per_day       = (summary["total_pings"] or 0) / max(summary["active_days"], 1)
    avg_shift_hours     = min(pings_per_day / 12, 12.0)  # 12 pings/hr cap at 12h
    deliveries_per_hour = 12 * 0.40
    inferred            = avg_shift_hours * deliveries_per_hour * city_order_value

    log.info("income_inferred", rider_id=rider_id, inferred=inferred)
    return round(inferred, 2)


async def check_income_deviation(
    conn: asyncpg.Connection, rider_id: str, new_declared: float
) -> dict:
    """Anti-gaming: flag if income update > 30%."""
    try:
        rider_lookup = uuid.UUID(rider_id)
    except (ValueError, TypeError):
        rider_lookup = rider_id

    rider = await conn.fetchrow("SELECT effective_income FROM riders WHERE id=$1", rider_lookup)
    if not rider:
        return {"flag": False, "hold_weeks": 0, "change_pct": 0.0}

    current    = float(rider["effective_income"])
    if current == 0:
        return {"flag": False, "hold_weeks": 0, "change_pct": 0.0}

    change_pct = (new_declared - current) / current
    if change_pct > 0.30:
        log.warning("income_update_flagged", rider_id=rider_id, change_pct=change_pct)
        return {"flag": True, "hold_weeks": 2, "change_pct": round(change_pct, 3)}

    return {"flag": False, "hold_weeks": 0, "change_pct": round(change_pct, 3)}
