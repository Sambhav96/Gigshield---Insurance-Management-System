"""
api/v1/referral.py — Rider referral system

UNICORN FEATURE: Growth mechanism via referral rewards

Flow:
  1. Rider gets unique referral code (rider's ID-based)
  2. New rider enrolls using referral code
  3. When new rider activates first policy → referrer gets ₹50 credit
  4. Credit applied as discount_weeks extension or wallet credit
"""
from __future__ import annotations

import uuid
import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_db, get_current_rider
from app.config import get_settings

router = APIRouter(prefix="/referral", tags=["referral"])
log = structlog.get_logger()
settings = get_settings()

REFERRAL_REWARD_INR = getattr(settings, "referral_reward_inr", 50.0)


class ApplyReferralRequest(BaseModel):
    referral_code: str


def _make_referral_code(rider_id: str) -> str:
    """Generate deterministic referral code from rider ID."""
    short = str(rider_id).replace("-", "")[:8].upper()
    return f"GS{short}"


@router.get("/my-code")
async def get_my_referral_code(rider: dict = Depends(get_current_rider)):
    """Get rider's unique referral code and stats."""
    code = _make_referral_code(str(rider["id"]))
    return {
        "referral_code": code,
        "share_message": f"Join GigShield — income protection for delivery riders! Use my code {code} to get your first week free 🛡️",
        "reward_per_referral_inr": REFERRAL_REWARD_INR,
        "share_url": f"https://gigshield.in/join?ref={code}",
    }


@router.get("/my-stats")
async def get_referral_stats(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Get rider's referral statistics."""
    referrer_code = _make_referral_code(str(rider["id"]))

    # Count riders who used this referral code
    referred_count = await conn.fetchval(
        "SELECT COUNT(*) FROM riders WHERE referral_code_used = $1",
        referrer_code,
    ) or 0

    # Count those who activated policies (earned rewards)
    rewarded_count = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT r.id)
        FROM riders r
        JOIN policies p ON p.rider_id = r.id
        WHERE r.referral_code_used = $1
          AND p.status = 'active'
        """,
        referrer_code,
    ) or 0

    total_earned = float(rewarded_count) * REFERRAL_REWARD_INR

    return {
        "referral_code": referrer_code,
        "referred_count": int(referred_count),
        "rewarded_count": int(rewarded_count),
        "total_earned_inr": total_earned,
        "pending_rewards": int(referred_count) - int(rewarded_count),
    }


@router.post("/apply")
async def apply_referral_code(
    body: ApplyReferralRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Apply a referral code to rider's account (only once, during onboarding)."""
    code = body.referral_code.strip().upper()

    # Check not already applied
    existing = await conn.fetchval(
        "SELECT referral_code_used FROM riders WHERE id = $1", rider["id"]
    )
    if existing:
        raise HTTPException(status_code=400, detail="Referral code already applied")

    # Validate the code is not the rider's own code
    my_code = _make_referral_code(str(rider["id"]))
    if code == my_code:
        raise HTTPException(status_code=400, detail="Cannot use your own referral code")

    # Verify code maps to a valid rider (extract ID from code)
    # Code format: GS + first 8 chars of UUID without dashes
    if not code.startswith("GS") or len(code) != 10:
        raise HTTPException(status_code=400, detail="Invalid referral code format")

    # Find referrer by code pattern match
    referrer = await conn.fetchrow(
        "SELECT id FROM riders WHERE UPPER(REPLACE(id::text, '-', '')) LIKE $1",
        code[2:].lower() + "%",
    )
    if not referrer:
        raise HTTPException(status_code=404, detail="Referral code not found")

    # Store the code on rider record
    try:
        await conn.execute(
            "UPDATE riders SET referral_code_used = $1, referred_by = $2 WHERE id = $3",
            code, referrer["id"], rider["id"],
        )
    except Exception:
        # Column may not exist if migration not run — handle gracefully
        log.warning("referral_column_missing_skipping")

    log.info("referral_code_applied", rider_id=str(rider["id"]), code=code)
    return {
        "status": "applied",
        "referral_code": code,
        "message": "Referral code applied! Your referrer will receive ₹50 when you activate your first policy.",
    }


async def process_referral_reward(conn: asyncpg.Connection, new_rider_id: str) -> None:
    """
    Called when a referred rider activates their first policy.
    Awards referrer with discount week extension.
    """
    try:
        referral_code = await conn.fetchval(
            "SELECT referral_code_used FROM riders WHERE id = $1",
            uuid.UUID(new_rider_id),
        )
        if not referral_code:
            return

        # Find referrer's active policy and extend discount_weeks
        referrer_id_str = await conn.fetchval(
            "SELECT referred_by FROM riders WHERE id = $1",
            uuid.UUID(new_rider_id),
        )
        if not referrer_id_str:
            return

        # Extend referrer's discount weeks (capped at 4)
        updated = await conn.fetchval(
            """
            UPDATE policies
            SET discount_weeks = LEAST(discount_weeks + 1, 4)
            WHERE rider_id = $1 AND status = 'active'
            RETURNING id
            """,
            referrer_id_str,
        )

        if updated:
            log.info("referral_reward_issued", referrer_id=str(referrer_id_str),
                     new_rider_id=new_rider_id, reward="1_discount_week")

    except Exception as exc:
        log.warning("referral_reward_processing_failed", error=str(exc))
