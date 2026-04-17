"""
services/backtest_service.py — Historical backtesting engine

UNICORN FEATURE: Investor-grade backtesting dashboard

Replays historical weather/traffic data against the pricing model to show:
  - Simulated loss ratios per zone/period
  - Trigger frequency vs actual weather events
  - Premium adequacy validation
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

log = structlog.get_logger()


async def run_historical_backtest(
    conn,
    city: str,
    start_date: str,
    end_date: str,
    plan: str = "standard",
    n_synthetic_riders: int = 100,
) -> dict:
    """
    Simulate GigShield operations over a historical period.
    Uses actual trigger events from trigger_events table as ground truth.
    
    Returns loss ratio, payout frequency, premium adequacy stats.
    """
    try:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    except ValueError as e:
        return {"error": f"Invalid date format: {e}"}

    days = (end - start).days
    if days < 1 or days > 365:
        return {"error": "Date range must be 1-365 days"}

    # Get actual trigger events in period for city hubs
    try:
        trigger_rows = await conn.fetch(
            """
            SELECT te.trigger_type, te.oracle_score, te.triggered_at,
                   te.resolved_at, h.city, h.city_multiplier
            FROM trigger_events te
            LEFT JOIN hubs h ON h.id = te.hub_id
            WHERE (h.city = $1 OR $1 = 'all')
              AND te.triggered_at BETWEEN $2 AND $3
              AND te.status = 'resolved'
            ORDER BY te.triggered_at
            """,
            city, start, end,
        )
    except Exception:
        trigger_rows = []

    # Get actual policy/payout stats for period
    try:
        actual_stats = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT pol.id) AS policies,
                COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type = 'premium_debit'), 0) AS premiums,
                COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type != 'premium_debit'), 0) AS payouts
            FROM payouts p
            JOIN policies pol ON p.policy_id = pol.id
            JOIN riders r ON r.id = pol.rider_id
            WHERE (r.city = $1 OR $1 = 'all')
              AND p.released_at BETWEEN $2 AND $3
            """,
            city, start, end,
        )
    except Exception:
        actual_stats = None

    # Build weekly simulation
    weekly_results = []
    current = start
    week_num = 0
    total_sim_premiums = 0.0
    total_sim_payouts  = 0.0
    simulated_income = 600.0  # median income assumption

    coverage_pcts = {"basic": 0.50, "standard": 0.70, "pro": 0.90}
    cap_mults     = {"basic": 3, "standard": 5, "pro": 7}
    base_premium  = {"basic": 35.0, "standard": 55.0, "pro": 85.0}

    coverage = coverage_pcts.get(plan, 0.70)
    cap_mult = cap_mults.get(plan, 5)
    weekly_premium = base_premium.get(plan, 55.0)

    while current < end and week_num < 52:
        week_end = current + timedelta(days=7)
        week_triggers = [
            t for t in trigger_rows
            if current <= t["triggered_at"] < week_end
        ]

        # Sim: n_synthetic_riders enrolled
        sim_premiums = n_synthetic_riders * weekly_premium
        total_sim_premiums += sim_premiums

        sim_payouts = 0.0
        trigger_details = []
        for t in week_triggers:
            score = float(t["oracle_score"] or 0)
            # Estimate duration: 4 hours default
            duration_hrs = 4.0
            payout_per_rider = simulated_income * coverage * (duration_hrs / 8) * score
            # Assume 40% of riders affected per trigger
            affected = int(n_synthetic_riders * 0.4)
            event_payouts = affected * min(payout_per_rider, simulated_income * cap_mult * 0.50)
            sim_payouts += event_payouts
            trigger_details.append({
                "type": t["trigger_type"],
                "score": round(score, 3),
                "affected_riders": affected,
                "payout": round(event_payouts, 2),
            })

        total_sim_payouts += sim_payouts
        loss_ratio = sim_payouts / sim_premiums if sim_premiums > 0 else 0

        weekly_results.append({
            "week": week_num + 1,
            "start": current.date().isoformat(),
            "triggers": len(week_triggers),
            "sim_premiums": round(sim_premiums, 2),
            "sim_payouts": round(sim_payouts, 2),
            "loss_ratio": round(loss_ratio, 4),
            "trigger_details": trigger_details,
        })

        current = week_end
        week_num += 1

    overall_lr = total_sim_payouts / total_sim_premiums if total_sim_premiums > 0 else 0

    return {
        "status": "complete",
        "params": {
            "city": city, "plan": plan,
            "start_date": start_date, "end_date": end_date,
            "n_synthetic_riders": n_synthetic_riders,
            "days_simulated": days,
        },
        "summary": {
            "total_weeks": len(weekly_results),
            "total_triggers": sum(w["triggers"] for w in weekly_results),
            "total_sim_premiums": round(total_sim_premiums, 2),
            "total_sim_payouts": round(total_sim_payouts, 2),
            "overall_loss_ratio": round(overall_lr, 4),
            "premium_adequacy": "adequate" if overall_lr < 0.70 else ("borderline" if overall_lr < 0.85 else "inadequate"),
        },
        "actual_stats": {
            "policies": int(actual_stats["policies"] or 0) if actual_stats else 0,
            "premiums_inr": float(actual_stats["premiums"] or 0) if actual_stats else 0,
            "payouts_inr": float(actual_stats["payouts"] or 0) if actual_stats else 0,
        } if actual_stats else None,
        "weekly_results": weekly_results,
    }
