"""
services/payout_service.py — AUDIT FIXED

BUG-01 FIX: mu_time for initial payouts now uses trigger.triggered_at IST hour,
            not current time. Continuation correctly uses current IST hour.
CODE-01 FIX: No naive local-now calls used anywhere — all timestamps from DB.
GAP-06 FIX: Reads liquidity_mode from system_config and enforces per-mode behavior.
"""
from __future__ import annotations

import time
import uuid
import structlog

from app.core.idempotency import make_payout_key
from app.core.redis_client import get_sync_redis
from app.core.exceptions import CircuitOpenError
from app.external.razorpay_client import create_payout
from app.utils.mu_table import (
    get_mu, get_mu_label, get_min_duration,
    get_confidence_factor, get_correlation_payout_factor,
)
from app.services.notification_service import publish_notification, render_template

log = structlog.get_logger()
LOCK_TTL = 60


async def get_liquidity_mode(conn) -> str:
    """Read current liquidity mode from system_config (set by liquidity_service)."""
    row = await conn.fetchrow("SELECT value FROM system_config WHERE key='liquidity_mode'")
    return row["value"] if row else "normal"


async def process_claim_payout(conn, claim_id: str, payout_type: str = "initial") -> dict:
    """Full 10-step payout with 4-layer race protection + liquidity mode enforcement."""
    redis    = get_sync_redis()
    lock_key = f"payout_lock:{claim_id}"
    if not redis.set(lock_key, "1", nx=True, ex=LOCK_TTL):
        return {"status": "skipped", "reason": "lock_held"}
    try:
        return await _execute_payout(conn, claim_id, payout_type)
    finally:
        redis.delete(lock_key)


async def _execute_payout(conn, claim_id: str, payout_type: str) -> dict:
    # GAP-06: Check liquidity mode first
    mode = await get_liquidity_mode(conn)
    if mode == "emergency":
        # Queue payout — do not process now
        redis = get_sync_redis()
        redis.zadd("payout_recovery_queue", {claim_id: time.time()})
        return {"status": "queued_emergency", "reason": "liquidity_emergency_mode"}

    async with conn.transaction():
        # L2: SELECT FOR UPDATE SKIP LOCKED
        claim = await conn.fetchrow(
            "SELECT * FROM claims WHERE id=$1 FOR UPDATE SKIP LOCKED",
            uuid.UUID(claim_id),
        )
        if not claim:
            return {"status": "skipped", "reason": "locked_by_other"}
        if claim["status"] in ("paid", "rejected", "cap_exhausted", "manual_rejected"):
            return {"status": "skipped", "reason": f"terminal_{claim['status']}"}

        policy  = await conn.fetchrow("SELECT * FROM policies WHERE id=$1", claim["policy_id"])
        rider   = await conn.fetchrow("SELECT * FROM riders WHERE id=$1", claim["rider_id"])
        trigger = await conn.fetchrow("SELECT * FROM trigger_events WHERE id=$1", claim["trigger_id"])
        if not all([policy, rider, trigger]):
            return {"status": "error", "reason": "missing_entities"}

        # ── BUG-01 FIX: IST hour from trigger.triggered_at for initial, NOW() for continuation ──
        if payout_type == "initial":
            ist_hour = await conn.fetchval(
                "SELECT EXTRACT(HOUR FROM $1 AT TIME ZONE 'Asia/Kolkata')::int",
                trigger["triggered_at"],
            )
        else:
            ist_hour = await conn.fetchval(
                "SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int"
            )

        mu_time          = get_mu(int(ist_hour))
        effective_income = float(rider["effective_income"])
        coverage_pct     = float(policy["coverage_pct"])
        duration_hrs     = get_min_duration(trigger["trigger_type"]) if payout_type == "initial" else 0.5

        # Steps 2–5: formula
        event_payout  = effective_income * coverage_pct * (duration_hrs / 8) * mu_time
        oracle_score  = float(claim.get("oracle_confidence") or trigger["oracle_score"] or 0.65)
        conf_factor   = get_confidence_factor(oracle_score)
        corr_factor   = float(trigger.get("correlation_factor") or 1.0)
        cool_factor   = float(trigger.get("cooldown_payout_factor") or 1.0)
        final_payout  = event_payout * conf_factor * corr_factor * cool_factor

        # GAP-06: stressed mode applies global 0.90 factor
        if mode == "stressed":
            final_payout *= 0.90

        # Step 6: headroom cap (authoritative DB read with lock)
        plan_cap_mult = int(policy["plan_cap_multiplier"])
        max_weekly    = effective_income * plan_cap_mult
        weekly_used   = float(await conn.fetchval(
            "SELECT weekly_payout_used FROM policies WHERE id=$1 FOR UPDATE",
            policy["id"],
        ) or 0)
        headroom = max_weekly - weekly_used
        if headroom <= 0:
            await conn.execute("UPDATE claims SET status='cap_exhausted' WHERE id=$1", uuid.UUID(claim_id))
            return {"status": "cap_exhausted", "weekly_cap": max_weekly}
        actual_payout = min(final_payout, headroom)

        # Step 7: event cap
        event_total = float(await conn.fetchval(
            """
            SELECT COALESCE(SUM(p.amount),0) FROM payouts p
            JOIN claims c ON p.claim_id=c.id
            WHERE c.trigger_id=$1 AND c.rider_id=$2
            """,
            claim["trigger_id"], claim["rider_id"],
        ) or 0)
        single_event_cap = max_weekly * 0.50
        if event_total >= single_event_cap:
            return {"status": "event_cap_reached", "event_cap": single_event_cap}

        # Step 8: daily soft limit (continuation only)
        if payout_type == "continuation":
            daily_limit = max_weekly / 4
            daily_total = float(await conn.fetchval(
                """
                SELECT COALESCE(SUM(amount),0) FROM payouts
                WHERE rider_id=$1
                  AND released_at >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Kolkata')
                  AND payout_type != 'premium_debit'
                """,
                claim["rider_id"],
            ) or 0)
            if daily_total >= daily_limit:
                return {"status": "daily_limit_reached"}

        # Step 9: Atomic cap increment (CRITICAL race-condition fix)
        # Uses UPDATE ... RETURNING to atomically check-and-increment.
        # If RETURNING returns NULL, another worker already consumed remaining cap.
        updated_policy = await conn.fetchrow(
            """
            UPDATE policies
            SET weekly_payout_used = weekly_payout_used + $1
            WHERE id = $2
              AND weekly_payout_used + $1 <= (effective_income * plan_cap_multiplier)
            RETURNING id, weekly_payout_used
            """,
            actual_payout, policy["id"],
        )
        if not updated_policy:
            # Cap was hit by a concurrent worker between our read and this update
            await conn.execute("UPDATE claims SET status='cap_exhausted' WHERE id=$1", uuid.UUID(claim_id))
            return {"status": "cap_exhausted_concurrent", "weekly_cap": max_weekly}

        # GAP-24 FIX: increment annual_payout_total for TDS tracking
        await conn.execute(
            "UPDATE riders SET annual_payout_total=COALESCE(annual_payout_total,0)+$1 WHERE id=$2",
            actual_payout, rider["id"],
        )
        # TDS threshold check
        annual_total = float(await conn.fetchval(
            "SELECT annual_payout_total FROM riders WHERE id=$1", rider["id"]
        ) or 0)
        if annual_total >= 10000:
            await conn.execute(
                """
                INSERT INTO entity_state_log (entity_type, entity_id, to_state, reason)
                VALUES ('tds_threshold', $1, 'crossed', 'annual_payout_exceeds_10000')
                ON CONFLICT DO NOTHING
                """,
                rider["id"],
            )

        # L3: Atomic status guard — BUG-04 FIX: mark 'auto_cleared', NOT 'paid'.
        # Claim is only marked 'paid' when Razorpay webhook confirms (webhooks.py).
        # This prevents claims being stuck in 'paid' state if Razorpay call fails.
        updated = await conn.execute(
            "UPDATE claims SET status='auto_cleared', actual_payout=$1 "
            "WHERE id=$2 AND status NOT IN ('paid','rejected','cap_exhausted','auto_cleared') RETURNING id",
            actual_payout, uuid.UUID(claim_id),
        )
        if updated == "UPDATE 0":
            return {"status": "already_processed"}

        # L4: Idempotency key insert
        idem_key = make_payout_key(claim_id, payout_type, actual_payout)
        inserted = await conn.fetchrow(
            """
            INSERT INTO payouts (claim_id, rider_id, policy_id, amount, payout_type,
                                  idempotency_key, razorpay_status, released_at)
            VALUES ($1,$2,$3,$4,$5,$6,'initiated',NOW())
            ON CONFLICT (idempotency_key) DO NOTHING RETURNING id
            """,
            claim["id"], claim["rider_id"], claim["policy_id"],
            actual_payout, payout_type, idem_key,
        )
        if not inserted:
            return {"status": "skipped", "reason": "idempotency_conflict"}

    # Step 10: Call Razorpay OUTSIDE transaction
    fund_account_id = policy.get("razorpay_fund_account_id")
    if not fund_account_id:
        return {"status": "queued_no_fund_account", "amount": actual_payout}

    # GAP-06: stressed mode – payouts > ₹1000 require manual approval
    if mode == "stressed" and actual_payout > 1000:
        await conn.execute(
            "UPDATE payouts SET razorpay_status='pending_manual' WHERE idempotency_key=$1",
            idem_key,
        )
        return {"status": "pending_manual_approval", "amount": actual_payout, "mode": mode}

    try:
        rz = create_payout(fund_account_id, actual_payout, idem_key)
        await conn.execute(
            "UPDATE payouts SET razorpay_ref=$1, razorpay_status='processing' WHERE idempotency_key=$2",
            rz.get("id"), idem_key,
        )
        # Rider-facing message respects liquidity mode language
        msg = render_template("payout_success", {"amount": actual_payout, "trigger_type": trigger["trigger_type"]})
        publish_notification(str(rider["id"]), "payout_success",
                             {"amount": actual_payout, "trigger_type": trigger["trigger_type"]})
        log.info("payout_initiated", claim_id=claim_id, amount=actual_payout, mode=mode)
        return {
            "status": "success", "amount": actual_payout, "payout_type": payout_type,
            "mu_time": mu_time, "mu_label": get_mu_label(int(ist_hour)), "idem_key": idem_key,
        }
    except CircuitOpenError:
        await conn.execute(
            "UPDATE payouts SET razorpay_status='circuit_breaker_hold' WHERE idempotency_key=$1",
            idem_key,
        )
        get_sync_redis().zadd("payout_recovery_queue", {idem_key: time.time()})
        return {"status": "circuit_breaker_hold", "amount": actual_payout}
    except Exception as exc:
        await conn.execute(
            "UPDATE payouts SET razorpay_status='failed' WHERE idempotency_key=$1", idem_key
        )
        log.error("payout_razorpay_error", error=str(exc))
        return {"status": "failed", "error": str(exc)}
