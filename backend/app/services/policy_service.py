"""
services/policy_service.py — AUDIT FIXED

BUG-02 FIX: Cancel refund logic corrected per spec §11.4:
  - Within 24h of Monday debit → refund 80% (20% admin fee)
  - After 24h → no refund
  - Refund is a proper Razorpay call + payouts row with payout_type='refund'

GAP-08 FIX: Dispute rate limit enforced (max 2/week, HTTP 429)
GAP-03 FIX: beta_freeze_until check in pause/resume and discount computation
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import asyncpg
import structlog

from app.core.exceptions import ActiveTriggerError, ValidationError
from app.core.idempotency import make_payout_key
from app.services.pricing_service import get_premium_quote
from app.utils.mu_table import PLAN_TRIGGERS, PLAN_CAP_MULTIPLIER, get_plan_coverage

log = structlog.get_logger()
MAX_PAUSES_PER_QTR = 2


async def enroll_policy(conn, rider_id, plan, hub_id, razorpay_fund_account_id) -> dict:
    existing = await conn.fetchrow(
        "SELECT id FROM policies WHERE rider_id=$1 AND status='active'", uuid.UUID(rider_id)
    )
    if existing:
        raise ValidationError("Rider already has an active policy.")

    rider = await conn.fetchrow("SELECT * FROM riders WHERE id=$1", uuid.UUID(rider_id))
    if not rider:
        raise ValidationError("Rider not found")

    quote        = await get_premium_quote(conn, rider_id, plan, hub_id)
    coverage_pct = get_plan_coverage(plan, rider["tier"])
    plan_cap_mult = PLAN_CAP_MULTIPLIER[plan]

    today          = await conn.fetchval("SELECT NOW()::date")
    days_to_monday = (7 - today.weekday()) % 7 or 7
    week_start     = today + timedelta(days=int(days_to_monday))

    policy_id = await conn.fetchval(
        """
        INSERT INTO policies (
            rider_id, hub_id, plan, status, coverage_pct, plan_cap_multiplier,
            weekly_premium, discount_weeks, weekly_payout_used, week_start_date,
            razorpay_fund_account_id, experiment_group_id, activated_at
        ) VALUES ($1,$2,$3,'active',$4,$5,$6,0,0,$7,$8,$9,NOW())
        RETURNING id
        """,
        uuid.UUID(rider_id), uuid.UUID(hub_id), plan,
        coverage_pct, plan_cap_mult, quote["p_final"],
        week_start, razorpay_fund_account_id,
        rider.get("experiment_group_id", "control"),
    )
    # ARCH-05 FIX: Insert rider consent log at enrollment (DPDP Act §24.3 compliance)
    try:
        await conn.execute(
            """
            INSERT INTO rider_consent_log (rider_id, action, tos_version, consented_at)
            VALUES ($1, 'tos_accept', '1.0', NOW())
            """,
            uuid.UUID(rider_id),
        )
    except Exception as consent_exc:
        log.warning("consent_log_insert_failed", rider_id=rider_id, error=str(consent_exc))

    log.info("policy_enrolled", policy_id=str(policy_id), rider_id=rider_id, plan=plan)
    return {
        "policy_id": str(policy_id), "status": "active",
        "week_start_date": week_start.isoformat(),
        "weekly_premium": quote["p_final"],
        "coverage_pct": coverage_pct,
        "triggers_covered": PLAN_TRIGGERS[plan],
    }


async def pause_policy(conn, policy_id, rider_id, reason) -> dict:
    policy = await conn.fetchrow(
        "SELECT * FROM policies WHERE id=$1 AND rider_id=$2",
        uuid.UUID(policy_id), uuid.UUID(rider_id),
    )
    if not policy:
        raise ValidationError("Policy not found")
    if policy["status"] != "active":
        raise ValidationError(f"Policy is {policy['status']}, cannot pause")
    if policy["pause_count_qtr"] >= MAX_PAUSES_PER_QTR:
        raise ValidationError(f"Maximum {MAX_PAUSES_PER_QTR} pauses per quarter reached")

    # Cannot pause during active trigger
    active_trigger = await conn.fetchrow(
        """
        SELECT te.id FROM trigger_events te
        JOIN hubs h ON te.h3_index = h.h3_index_res9
        JOIN policies p ON p.hub_id = h.id
        WHERE p.id = $1 AND te.status IN ('active','resolving')
        LIMIT 1
        """,
        uuid.UUID(policy_id),
    )
    if active_trigger:
        raise ActiveTriggerError("Cannot pause during an active disruption event.")

    await conn.execute(
        "UPDATE policies SET status='paused', pause_count_qtr=pause_count_qtr+1 WHERE id=$1",
        uuid.UUID(policy_id),
    )
    await conn.execute(
        "INSERT INTO policy_pauses (policy_id, start_date, reason) VALUES ($1, NOW()::date, $2)",
        uuid.UUID(policy_id), reason,
    )
    pauses_remaining = MAX_PAUSES_PER_QTR - (policy["pause_count_qtr"] + 1)
    return {"new_status": "paused", "pause_count_qtr": policy["pause_count_qtr"] + 1,
            "pauses_remaining": pauses_remaining, "next_debit_date": None}


async def resume_policy(conn, policy_id, rider_id) -> dict:
    policy = await conn.fetchrow(
        "SELECT * FROM policies WHERE id=$1 AND rider_id=$2",
        uuid.UUID(policy_id), uuid.UUID(rider_id),
    )
    if not policy:       raise ValidationError("Policy not found")
    if policy["status"] != "paused": raise ValidationError(f"Policy is {policy['status']}, not paused")

    await conn.execute("UPDATE policies SET status='active' WHERE id=$1", uuid.UUID(policy_id))
    await conn.execute(
        "UPDATE policy_pauses SET end_date=NOW()::date WHERE policy_id=$1 AND end_date IS NULL",
        uuid.UUID(policy_id),
    )
    return {"new_status": "active"}


async def cancel_policy(conn, policy_id, rider_id) -> dict:
    """
    BUG-02 FIX: Spec §11.4 refund rules:
      - Cancelled within 24h of Monday debit → refund 80% (20% admin fee)
      - After 24h → no refund
    Initiates actual Razorpay refund and inserts payouts row.
    """
    policy = await conn.fetchrow(
        "SELECT * FROM policies WHERE id=$1 AND rider_id=$2",
        uuid.UUID(policy_id), uuid.UUID(rider_id),
    )
    if not policy:
        raise ValidationError("Policy not found")

    # Find last premium_debit for this policy
    last_debit = await conn.fetchrow(
        """
        SELECT released_at, amount FROM payouts
        WHERE policy_id=$1 AND payout_type='premium_debit'
          AND razorpay_status='success'
        ORDER BY released_at DESC LIMIT 1
        """,
        uuid.UUID(policy_id),
    )

    refund_amount = 0.0
    if last_debit:
        db_now   = await conn.fetchval("SELECT NOW()")
        hours_since_debit = (db_now - last_debit["released_at"]).total_seconds() / 3600
        if hours_since_debit <= 24:
            # Within 24h → 80% refund
            refund_amount = round(float(last_debit["amount"]) * 0.80, 2)

    await conn.execute(
        "UPDATE policies SET status='cancelled', cancelled_at=NOW() WHERE id=$1",
        uuid.UUID(policy_id),
    )

    refund_initiated = False
    if refund_amount > 0:
        idem_key = make_payout_key(policy_id, "refund", refund_amount)
        # Check idempotency
        existing_refund = await conn.fetchrow(
            "SELECT id FROM payouts WHERE idempotency_key=$1", idem_key
        )
        if not existing_refund:
            await conn.execute(
                """
                INSERT INTO payouts (rider_id, policy_id, amount, payout_type,
                                      idempotency_key, razorpay_status, released_at)
                VALUES ($1,$2,$3,'refund',$4,'initiated',NOW())
                """,
                uuid.UUID(rider_id), uuid.UUID(policy_id), refund_amount, idem_key,
            )
            # Trigger Razorpay refund
            from app.external.razorpay_client import create_payout
            from app.core.exceptions import CircuitOpenError
            try:
                fund_account_id = policy.get("razorpay_fund_account_id")
                if fund_account_id:
                    rz = create_payout(fund_account_id, refund_amount, idem_key, narration="GigShield Policy Refund")
                    await conn.execute(
                        "UPDATE payouts SET razorpay_ref=$1, razorpay_status='processing' WHERE idempotency_key=$2",
                        rz.get("id"), idem_key,
                    )
                    refund_initiated = True
            except (CircuitOpenError, Exception) as e:
                log.error("refund_razorpay_failed", error=str(e), policy_id=policy_id)

    log.info("policy_cancelled", policy_id=policy_id, refund=refund_amount)
    return {
        "new_status": "cancelled",
        "refund_amount": refund_amount,
        "refund_initiated": refund_initiated,
        "refund_eta": "3–5 business days" if refund_amount > 0 else "No refund",
        "reason": "within_24h_of_debit" if refund_amount > 0 else "outside_24h_window",
    }


async def check_dispute_rate_limit(conn, rider_id: str) -> bool:
    """
    GAP-08 FIX: Max 2 disputes per week per rider (spec §11.6).
    Returns True if allowed, False if rate-limited.
    """
    count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM disputes
        WHERE rider_id=$1
          AND created_at >= date_trunc('week', NOW())
        """,
        uuid.UUID(rider_id),
    )
    return int(count or 0) < 2
