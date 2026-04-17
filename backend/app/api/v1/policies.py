"""api/v1/policies.py — Policy enrollment, quote, lifecycle."""
from __future__ import annotations

from uuid import UUID
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_db, get_current_rider
from app.models.policy import PolicyCreate, PolicyStatusUpdate
from app.services.policy_service import (
    enroll_policy, pause_policy, resume_policy, cancel_policy
)
from app.services.pricing_service import get_premium_quote

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("/quote")
async def get_quote(
    plan: str = Query(..., pattern="^(basic|standard|pro)$"),
    hub_id: UUID = Query(...),
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Get a premium quote for a plan + hub combination."""
    return await get_premium_quote(conn, str(rider["id"]), plan, str(hub_id))


@router.post("", status_code=201)
async def create_policy(
    body: PolicyCreate,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    return await enroll_policy(
        conn,
        rider_id=str(rider["id"]),
        plan=body.plan.value,
        hub_id=str(body.hub_id),
        razorpay_fund_account_id=body.razorpay_fund_account_id,
    )


@router.get("/me")
async def get_my_policy(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    from app.repositories.policy_repo import get_active_policy_for_rider
    policy = await get_active_policy_for_rider(conn, str(rider["id"]))
    if not policy:
        raise HTTPException(status_code=404, detail="No active policy")

    plan = str(policy["plan"])
    effective_income = float(rider.get("effective_income") or 0)
    cap_multiplier = int(policy.get("plan_cap_multiplier") or 0)
    weekly_cap = float(effective_income * cap_multiplier)

    if plan == "basic":
        covered_triggers = ["Rain > 10mm/hr"]
    elif plan == "standard":
        covered_triggers = ["Rain > 5mm/hr", "AQI > 300"]
    else:
        covered_triggers = ["Rain", "AQI > 250", "Heat", "Flood", "Bandh", "Platform Down"]

    return {
        "id": str(policy["id"]),
        "rider_id": str(policy["rider_id"]),
        "hub_id": str(policy["hub_id"]),
        "plan": plan,
        "plan_name": f"{plan.title()} Shield",
        "status": str(policy["status"]),
        "coverage_pct": float(policy["coverage_pct"]),
        "coverage_percent": float(policy["coverage_pct"]) * 100,
        "weekly_premium": float(policy["weekly_premium"]),
        "premium_amount": float(policy["weekly_premium"]),
        "plan_cap_multiplier": cap_multiplier,
        "weekly_cap": weekly_cap,
        "discount_weeks": int(policy.get("discount_weeks") or 0),
        "weekly_payout_used": float(policy.get("weekly_payout_used") or 0),
        "razorpay_fund_account_id": policy.get("razorpay_fund_account_id"),
        "covered_triggers": covered_triggers,
    }


@router.patch("/{policy_id}/status")
async def update_policy_status(
    policy_id: UUID,
    body: PolicyStatusUpdate,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    if body.action == "pause":
        return await pause_policy(conn, str(policy_id), str(rider["id"]), body.reason)
    elif body.action == "resume":
        return await resume_policy(conn, str(policy_id), str(rider["id"]))
    elif body.action == "cancel":
        return await cancel_policy(conn, str(policy_id), str(rider["id"]))
    raise HTTPException(status_code=400, detail="Invalid action")
