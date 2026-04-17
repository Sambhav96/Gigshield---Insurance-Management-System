"""workers/continuation_worker.py — Continuation payouts every 30 min for active triggers."""
from __future__ import annotations

import structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _sync_conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    conn = psycopg2.connect(get_settings().database_url)
    conn.autocommit = True
    return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.continuation_worker.run_continuation_loop")
def run_continuation_loop():
    """
    Every 30 minutes:
    1. Re-fetch all active trigger_events
    2. Re-compute oracle_score for each
    3. If still >= 0.50: issue continuation payout (0.5h) for all active riders
    4. If < 0.50: set status = 'resolving'; second consecutive → 'resolved'

    Shift-state rule: skip only explicit offline riders (shift_status == "offline").
    """
    conn, cur = _sync_conn()

    try:
        cur.execute(
            "SELECT * FROM trigger_events WHERE status IN ('active', 'resolving')"
        )
        active_triggers = cur.fetchall()
        log.info("continuation_loop_started", trigger_count=len(active_triggers))

        for trigger in active_triggers:
            _process_trigger_continuation(cur, dict(trigger))

    finally:
        cur.close()
        conn.close()


def _process_trigger_continuation(cur, trigger: dict):
    from app.services.oracle_service import compute_oracle_score
    from app.utils.mu_table import get_mu, get_correlation_payout_factor

    trigger_id = str(trigger["id"])
    h3_index = trigger["h3_index"]

    # Fetch hub for coordinates
    cur.execute("SELECT * FROM hubs WHERE id = %s", (str(trigger["hub_id"]),))
    hub = cur.fetchone()
    if not hub:
        return

    lat, lng = float(hub["latitude"]), float(hub["longitude"])
    hub_threshold = float(hub.get("rain_threshold_mm", 35.0))

    # Re-fetch oracle score
    try:
        result = compute_oracle_score(
            trigger_type=trigger["trigger_type"],
            lat=lat, lng=lng, h3_index=h3_index,
            hub_threshold_mm=hub_threshold,
        )
        oracle_score = result["oracle_score"]
    except Exception as exc:
        log.error("continuation_oracle_failed", trigger_id=trigger_id, error=str(exc))
        return

    if oracle_score >= 0.50:
        # Still active — issue continuation payouts
        if trigger["status"] == "resolving":
            # Back above threshold — mark active again
            cur.execute(
                "UPDATE trigger_events SET status = 'active' WHERE id = %s", (trigger_id,)
            )

        # Update oracle_score
        cur.execute(
            "UPDATE trigger_events SET oracle_score = %s WHERE id = %s",
            (oracle_score, trigger_id),
        )

        # IST hour for mu
        cur.execute(
            "SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int as h"
        )
        ist_hour = cur.fetchone()["h"]
        mu_time = get_mu(ist_hour)

        # Get all active policies in this hex that had a paid/auto_cleared claim for this trigger
        cur.execute(
            """
            SELECT DISTINCT c.rider_id, c.policy_id, c.id as claim_id,
                   r.effective_income, p.coverage_pct, p.plan_cap_multiplier,
                   p.weekly_payout_used, p.razorpay_fund_account_id,
                   ss.status as shift_status
            FROM claims c
            JOIN policies p ON c.policy_id = p.id
            JOIN riders r ON c.rider_id = r.id
            LEFT JOIN shift_states ss ON ss.rider_id = c.rider_id
                AND ss.ended_at IS NULL
            WHERE c.trigger_id = %s
              AND c.status IN ('auto_cleared','paid','soft_flagged')
            """,
            (trigger_id,),
        )
        eligible = cur.fetchall()

        for rider_policy in eligible:
            # Skip only if rider is explicitly marked offline.
            # NULL shift_status means no shift record found (LEFT JOIN) — treat as active.
            # ARCH-05 FIX: NULL -> active (not offline)
            shift_status = rider_policy.get("shift_status")
            if shift_status == "offline":
                continue
            # shift_status is None (no shift record) or 'active'/'on_delivery' -> proceed

            from app.workers.payout_worker import process_claim_payout_task
            process_claim_payout_task.delay(str(rider_policy["claim_id"]), "continuation")

    else:
        # Oracle below 0.50
        if trigger["status"] == "active":
            cur.execute(
                "UPDATE trigger_events SET status = 'resolving' WHERE id = %s", (trigger_id,)
            )
            log.info("trigger_resolving", trigger_id=trigger_id, oracle_score=oracle_score)
        elif trigger["status"] == "resolving":
            # Second consecutive check below threshold → resolved
            cur.execute(
                "UPDATE trigger_events SET status = 'resolved', resolved_at = NOW() WHERE id = %s",
                (trigger_id,),
            )
            log.info("trigger_resolved", trigger_id=trigger_id)
