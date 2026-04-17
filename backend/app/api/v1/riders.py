"""api/v1/riders.py — Rider profile, registration, income update."""
from __future__ import annotations
from typing import Optional

from datetime import datetime
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_db, get_current_rider
from app.models.rider import RiderCreate, RiderProfile, IncomeUpdateRequest
from app.repositories.rider_repo import (
    create_rider, get_rider_by_id, update_effective_income
)
from app.services.income_service import compute_effective_income, check_income_deviation

router = APIRouter(prefix="/riders", tags=["riders"])


class PayoutDestinationRequest(BaseModel):
    razorpay_fund_account_id: str


@router.post("", status_code=201)
async def register_rider(
    body: RiderCreate,
    conn: asyncpg.Connection = Depends(get_db),
):
    """Register a new rider after OTP verification."""
    from app.repositories.rider_repo import get_rider_by_phone
    existing = await get_rider_by_phone(conn, body.phone)
    if existing:
        raise HTTPException(status_code=409, detail="Phone already registered")

    rider_id = await create_rider(
        conn,
        name=body.name,
        phone=body.phone,
        platform=body.platform.value,
        city=body.city,
        declared_income=body.declared_income,
        hub_id=str(body.hub_id),
    )
    return {"rider_id": rider_id, "status": "created"}


@router.get("/me")
async def get_my_profile(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    declared_income = rider.get("declared_income")
    effective_income = rider.get("effective_income")
    return {
        "id": str(rider["id"]),
        "name": rider["name"],
        "phone": rider["phone"],
        "platform": rider["platform"],
        "city": rider["city"],
        "declared_income": float(declared_income or 0),
        "effective_income": float(effective_income or 0),
        "tier": rider["tier"],
        "risk_score": rider["risk_score"],
        "risk_profile": rider["risk_profile"],
        "phone_verified": rider["phone_verified"],
        "experiment_group_id": rider["experiment_group_id"],
        "hub_id": str(rider["hub_id"]) if rider.get("hub_id") else None,
        "razorpay_fund_account_id": rider.get("razorpay_fund_account_id"),
    }


@router.post("/me/payout-destination")
async def save_payout_destination(
    body: PayoutDestinationRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    try:
        await conn.execute(
            "UPDATE riders SET razorpay_fund_account_id = $1 WHERE id = $2",
            body.razorpay_fund_account_id,
            rider["id"],
        )
    except asyncpg.UndefinedColumnError:
        # Backward-compatible fallback for schemas where fund account is stored on policies.
        await conn.execute(
            "UPDATE policies SET razorpay_fund_account_id = $1 WHERE rider_id = $2 AND status = 'active'",
            body.razorpay_fund_account_id,
            rider["id"],
        )
    return {"status": "saved", "razorpay_fund_account_id": body.razorpay_fund_account_id}


@router.get("/me/payouts")
async def get_my_payouts(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    rows = await conn.fetch(
        """
        SELECT p.*, c.trigger_id, c.status AS claim_status
        FROM payouts p
        LEFT JOIN claims c ON p.claim_id = c.id
        WHERE p.rider_id = $1
        ORDER BY p.released_at DESC
        LIMIT 50
        """,
        rider["id"],
    )

    payouts = []
    for row in rows:
        d = dict(row)
        payouts.append(
            {
                "id": str(d["id"]),
                "claim_id": str(d["claim_id"]) if d.get("claim_id") else None,
                "rider_id": str(d["rider_id"]),
                "policy_id": str(d["policy_id"]) if d.get("policy_id") else None,
                "amount": float(d.get("amount") or 0),
                "payout_type": d.get("payout_type"),
                "razorpay_ref": d.get("razorpay_ref"),
                "razorpay_status": d.get("razorpay_status"),
                "released_at": d.get("released_at").isoformat() if d.get("released_at") else None,
                "claim_status": d.get("claim_status"),
                "trigger_id": str(d["trigger_id"]) if d.get("trigger_id") else None,
            }
        )

    available_balance = await conn.fetchval(
        """
        SELECT COALESCE(SUM(CASE WHEN payout_type != 'premium_debit' THEN amount ELSE 0 END), 0)
             - COALESCE(SUM(CASE WHEN payout_type = 'premium_debit' THEN amount ELSE 0 END), 0)
        FROM payouts
        WHERE rider_id = $1
        """,
        rider["id"],
    )

    return {
        "payouts": payouts,
        "total": len(payouts),
        "available_balance": float(available_balance or 0),
    }


@router.get("/me/activity")
async def get_my_activity(
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    rider_id = rider["id"]
    hub_id = rider.get("hub_id")

    payout_rows = await conn.fetch(
        """
        SELECT id, payout_type, amount, released_at
        FROM payouts
        WHERE rider_id = $1
        ORDER BY released_at DESC
        LIMIT 20
        """,
        rider_id,
    )

    claim_rows = await conn.fetch(
        """
        SELECT c.id, c.status, c.initiated_at, te.trigger_type
        FROM claims c
        LEFT JOIN trigger_events te ON te.id = c.trigger_id
        WHERE c.rider_id = $1
        ORDER BY c.initiated_at DESC
        LIMIT 20
        """,
        rider_id,
    )

    alert_rows = await conn.fetch(
        """
        SELECT id, trigger_type, triggered_at, status
        FROM trigger_events
        WHERE hub_id = $1
        ORDER BY triggered_at DESC
        LIMIT 20
        """,
        hub_id,
    ) if hub_id else []

    events: list[dict] = []

    for row in payout_rows:
        d = dict(row)
        ts = d.get("released_at")
        events.append(
            {
                "type": "payment",
                "title": str(d.get("payout_type") or "payout").replace("_", " ").title(),
                "subtitle": "Payout released",
                "value": f"+₹{float(d.get('amount') or 0):.2f}",
                "timestamp": ts.isoformat() if ts else None,
                "icon": "payments",
                "sort_ts": ts,
            }
        )

    for row in claim_rows:
        d = dict(row)
        ts = d.get("initiated_at")
        events.append(
            {
                "type": "claim",
                "title": str(d.get("status") or "claim").replace("_", " ").title(),
                "subtitle": f"Trigger: {str(d.get('trigger_type') or 'unknown').upper()}",
                "value": "Logged",
                "timestamp": ts.isoformat() if ts else None,
                "icon": "description",
                "sort_ts": ts,
            }
        )

    for row in alert_rows:
        d = dict(row)
        ts = d.get("triggered_at")
        events.append(
            {
                "type": "alert",
                "title": f"{str(d.get('trigger_type') or 'alert').upper()} Alert",
                "subtitle": f"Status: {str(d.get('status') or 'active').title()}",
                "value": "Zone",
                "timestamp": ts.isoformat() if ts else None,
                "icon": "warning",
                "sort_ts": ts,
            }
        )

    events.sort(key=lambda e: e.get("sort_ts") or datetime.min, reverse=True)
    events = events[:30]
    for e in events:
        e.pop("sort_ts", None)

    return {"activities": events}


@router.patch("/me/income")
async def update_income(
    body: IncomeUpdateRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Update declared income with 30% change cap protection."""
    deviation = await check_income_deviation(
        conn, str(rider["id"]), body.new_declared_income
    )
    if deviation["flag"]:
        return {
            "status": "flagged_for_review",
            "message": f"Income change of {deviation['change_pct']:.0%} exceeds 30% threshold. Under review for {deviation['hold_weeks']} weeks.",
            "hold_weeks": deviation["hold_weeks"],
        }

    # Compute new effective income
    import asyncpg as _apg
    from app.utils.mu_table import get_city_median_income
    new_effective = min(body.new_declared_income, get_city_median_income(rider["city"]))

    await conn.execute(
        "UPDATE riders SET declared_income = $1 WHERE id = $2",
        body.new_declared_income, rider["id"],
    )
    await update_effective_income(conn, str(rider["id"]), new_effective)

    return {
        "status": "updated",
        "new_declared_income": body.new_declared_income,
        "new_effective_income": new_effective,
    }


class RiderProfileUpdateRequest(BaseModel):
    """Used by onboarding ProfileForm to set hub, platform, city, income post-registration."""
    name: Optional[str] = None
    phone: Optional[str] = None
    platform: Optional[str] = None
    city: Optional[str] = None
    declared_income: Optional[float] = None
    hub_id: Optional[str] = None


@router.patch("/me/profile")
async def update_my_profile(
    body: RiderProfileUpdateRequest,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Update rider profile fields after email registration.
    Called by onboarding ProfileForm when rider registered via email
    and needs to set hub_id, platform, city, income.
    """
    from app.utils.mu_table import get_city_median_income

    updates = []
    params: list = []
    idx = 1

    if body.name is not None:
        updates.append(f"name = ${idx}")
        params.append(body.name.strip())
        idx += 1

    if body.phone is not None:
        import re
        phone = body.phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+91"):
            phone = "+91" + phone.lstrip("0")
        updates.append(f"phone = ${idx}")
        params.append(phone)
        idx += 1

    if body.platform is not None:
        updates.append(f"platform = ${idx}")
        params.append(body.platform.lower())
        idx += 1

    if body.city is not None:
        updates.append(f"city = ${idx}")
        params.append(body.city)
        idx += 1

    if body.hub_id is not None:
        import uuid as _uuid
        updates.append(f"hub_id = ${idx}")
        params.append(_uuid.UUID(body.hub_id))
        idx += 1

    if body.declared_income is not None:
        city = body.city or rider.get("city") or "Mumbai"
        city_median = get_city_median_income(city)
        effective = round(min(body.declared_income, city_median), 2)
        tier = "A" if effective > 700 else "B"
        updates.append(f"declared_income = ${idx}")
        params.append(body.declared_income)
        idx += 1
        updates.append(f"effective_income = ${idx}")
        params.append(effective)
        idx += 1
        updates.append(f"tier = ${idx}")
        params.append(tier)
        idx += 1

    if not updates:
        return {"status": "no_changes"}

    params.append(rider["id"])
    await conn.execute(
        f"UPDATE riders SET {', '.join(updates)} WHERE id = ${idx}",
        *params,
    )

    # Return updated profile
    updated = await conn.fetchrow("SELECT * FROM riders WHERE id = $1", rider["id"])
    return {
        "status": "updated",
        "id": str(updated["id"]),
        "name": updated["name"],
        "hub_id": str(updated["hub_id"]) if updated.get("hub_id") else None,
        "platform": updated["platform"],
        "city": updated["city"],
        "effective_income": float(updated["effective_income"] or 0),
    }
