"""
services/discount_service.py — AUDIT FIXED

GAP-03 FIX: beta_freeze_until enforced.
  - Hard-flag confirmed → β=1.0, discount_weeks=0, cannot improve for 14 days.
  - Monday worker checks beta_freeze_until before incrementing discount_weeks.

CODE-04: Filter explicitly names allowed payout types that reset discount,
         making the intent clear and future-proof.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import asyncpg
import structlog

log = structlog.get_logger()

MAX_DISCOUNT_WEEKS  = 4
DISCOUNT_PER_WEEK   = 0.05   # 5% per clean week
FRAUD_FREEZE_DAYS   = 14     # days discount cannot improve after hard-flag confirmed

# CODE-04 FIX: Explicit allowlist of payout types that reset discount_weeks.
# Makes intent crystal clear — premium_debit excluded, everything else resets.
PAYOUT_TYPES_THAT_RESET = frozenset([
    "initial", "continuation", "provisional", "remainder",
    "goodwill", "vov_reward", "refund",
])


async def compute_discount_weeks(
    conn: asyncpg.Connection,
    policy_id: str,
    rider_id: str,
    week_start,
) -> int:
    """
    Called during Monday cycle.
    GAP-03 FIX: Checks beta_freeze_until — if frozen, returns 0 regardless of week.
    """
    policy = await conn.fetchrow(
        "SELECT discount_weeks, beta_freeze_until FROM policies WHERE id=$1",
        uuid.UUID(policy_id),
    )
    if not policy:
        return 0

    # GAP-03: Check freeze window
    db_now = await conn.fetchval("SELECT NOW()")
    freeze_until = policy.get("beta_freeze_until")
    if freeze_until and db_now < freeze_until:
        log.info("discount_frozen", policy_id=policy_id, freeze_until=str(freeze_until))
        return 0

    current_weeks   = policy["discount_weeks"]
    prev_week_start = week_start - timedelta(days=7)

    # Check if ANY resetting payout occurred in the previous week
    week_total = await conn.fetchval(
        """
        SELECT COALESCE(SUM(amount), 0) FROM payouts
        WHERE rider_id = $1
          AND released_at >= $2
          AND released_at < $3
          AND payout_type = ANY($4::text[])
        """,
        uuid.UUID(rider_id),
        prev_week_start,
        week_start,
        list(PAYOUT_TYPES_THAT_RESET),
    )

    new_weeks = min(current_weeks + 1, MAX_DISCOUNT_WEEKS) if float(week_total) == 0 else 0

    log.info("discount_computed", policy_id=policy_id, week_total=float(week_total),
             old=current_weeks, new=new_weeks)
    return new_weeks


async def apply_fraud_freeze(
    conn: asyncpg.Connection,
    policy_id: str,
    rider_id: str,
) -> None:
    """
    GAP-03 FIX: Called when hard-flag is confirmed.
    Resets discount_weeks=0, sets beta_freeze_until=NOW()+14 days.
    """
    db_now       = await conn.fetchval("SELECT NOW()")
    freeze_until = db_now + timedelta(days=FRAUD_FREEZE_DAYS)

    await conn.execute(
        "UPDATE policies SET discount_weeks=0, beta_freeze_until=$1 WHERE id=$2",
        freeze_until, uuid.UUID(policy_id),
    )
    log.warning("beta_freeze_applied", policy_id=policy_id, freeze_until=str(freeze_until))


def compute_beta_from_discount(discount_weeks: int, frozen: bool = False) -> float:
    """β = 1.0 − (0.05 × discount_weeks). Floor at 0.80. Frozen → β=1.0."""
    if frozen:
        return 1.0
    return max(0.80, 1.0 - (DISCOUNT_PER_WEEK * min(discount_weeks, MAX_DISCOUNT_WEEKS)))
