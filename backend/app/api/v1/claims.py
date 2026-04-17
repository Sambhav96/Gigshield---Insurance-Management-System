"""api/v1/claims.py — AUDIT FIXED: dispute rate limit enforced (GAP-08)."""
from __future__ import annotations

import uuid as _uuid
from datetime import timedelta

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_db, get_current_rider
from app.repositories.claim_repo import list_claims_for_rider, get_claim_by_id
from app.services.policy_service import check_dispute_rate_limit

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("")
async def list_claims(
    status: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    claims, total = await list_claims_for_rider(
        conn, str(rider["id"]), status=status, limit=limit, offset=offset
    )
    return {"claims": claims, "total": total}


@router.get("/{claim_id}/proof")
async def get_claim_proof(
    claim_id: _uuid.UUID,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    claim = await get_claim_by_id(conn, str(claim_id))
    if not claim or str(claim["rider_id"]) != str(rider["id"]):
        raise HTTPException(status_code=404, detail="Claim not found")

    trigger = await conn.fetchrow("SELECT * FROM trigger_events WHERE id=$1", claim["trigger_id"])
    payout  = await conn.fetchrow("SELECT * FROM payouts WHERE claim_id=$1 LIMIT 1", claim["id"])

    admin_trace = claim.get("admin_trace") or {}
    descriptions = {
        "rain": "Heavy rainfall exceeded threshold in your delivery zone",
        "flood": "Flooding detected via satellite and government advisory",
        "heat": "Extreme heat (wet bulb temperature) exceeded safe working threshold",
        "aqi": "Air quality index exceeded hazardous level",
        "bandh": "Civic strike detected — road speed < 15% of normal baseline",
        "platform_down": "Platform app outage detected for 30+ consecutive minutes",
    }

    return {
        "claim_id": str(claim_id),
        "trigger_type": trigger["trigger_type"] if trigger else "unknown",
        "trigger_description": descriptions.get(trigger["trigger_type"] if trigger else "", "Disruption event"),
        "oracle_score": float(trigger["oracle_score"]) if trigger else 0,
        "oracle_weight_config": trigger["weight_config"] if trigger else {},
        "signal_breakdown": {
            "satellite_score": float(trigger["satellite_score"] or 0) if trigger else 0,
            "weather_score":   float(trigger["weather_score"] or 0) if trigger else 0,
            "traffic_score":   float(trigger["traffic_score"] or 0) if trigger else 0,
        },
        "fraud_score":       float(claim["fraud_score"] or 0),
        "presence_confidence": float(claim["presence_confidence"] or 0),
        "oracle_confidence": float(claim["oracle_confidence"] or 0),
        "payout_amount":     float(payout["amount"]) if payout else 0,
        "payout_breakdown": {
            "effective_income": float(rider["effective_income"]),
            "coverage_pct":     admin_trace.get("coverage_pct"),
            "duration_hrs":     float(claim["duration_hrs"] or 0),
            "mu_time":          float(claim["mu_time"] or 0),
            "event_payout":     float(claim["event_payout"] or 0),
            "actual_payout":    float(claim["actual_payout"] or 0),
        },
        "api_sources_used": admin_trace.get("api_sources", []),
        "dispute_deadline": (claim["initiated_at"] + timedelta(days=7)).isoformat() if claim["initiated_at"] else None,
        "explanation": claim.get("explanation_text") or "Your zone crossed the disruption threshold based on verified data sources.",
    }


@router.post("/disputes")
async def file_dispute(
    body: dict,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """GAP-08 FIX: Rate limit enforced — max 2 disputes per week per rider."""
    claim_id    = body.get("claim_id")
    reason_text = body.get("reason_text", "")

    if len(reason_text) < 10:
        raise HTTPException(status_code=400, detail="Reason must be at least 10 characters")

    # GAP-08: Rate limit check
    allowed = await check_dispute_rate_limit(conn, str(rider["id"]))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Dispute rate limit reached: maximum 2 disputes per week. Try again next Monday.",
        )

    claim = await get_claim_by_id(conn, str(claim_id))
    if not claim or str(claim["rider_id"]) != str(rider["id"]):
        raise HTTPException(status_code=404, detail="Claim not found")

    db_now       = await conn.fetchval("SELECT NOW()")
    sla_deadline = db_now + timedelta(days=3)

    dispute_id = await conn.fetchval(
        """
        INSERT INTO disputes (rider_id, claim_id, reason_text, status, sla_deadline)
        VALUES ($1,$2,$3,'open',$4)
        RETURNING id
        """,
        rider["id"], _uuid.UUID(str(claim_id)), reason_text, sla_deadline,
    )
    await conn.execute(
        "UPDATE claims SET status='disputed' WHERE id=$1", _uuid.UUID(str(claim_id))
    )

    return {"dispute_id": str(dispute_id), "sla_deadline": sla_deadline.isoformat(), "status": "open"}


@router.get("/{claim_id}/timeline")
async def get_claim_timeline(
    claim_id: _uuid.UUID,
    rider: dict = Depends(get_current_rider),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    GET /api/v1/claims/{id}/timeline
    Returns chronological timeline of all events for a claim.
    Used by rider activity page to show claim status history.
    """
    # Verify claim belongs to rider
    claim = await conn.fetchrow(
        "SELECT * FROM claims WHERE id = $1 AND rider_id = $2",
        claim_id, rider["id"],
    )
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    timeline = []

    # 1. Claim initiated
    timeline.append({
        "event": "claim_initiated",
        "label": "Claim Created",
        "description": "Your claim was automatically initiated when the trigger was detected.",
        "timestamp": claim["initiated_at"].isoformat() if claim.get("initiated_at") else None,
        "status": "completed",
        "icon": "shield",
    })

    # 2. Fraud evaluation
    if claim.get("fraud_score") is not None:
        fs = float(claim["fraud_score"])
        timeline.append({
            "event": "fraud_evaluated",
            "label": "Fraud Check",
            "description": f"Fraud score: {fs:.2f}. {'Auto-cleared.' if fs < 0.40 else 'Manual review required.' if fs >= 0.80 else 'Standard verification.'}",
            "timestamp": claim["initiated_at"].isoformat() if claim.get("initiated_at") else None,
            "status": "completed",
            "icon": "security",
            "score": fs,
        })

    # 3. Status events
    status_map = {
        "auto_cleared":    ("Auto Approved", "Claim auto-cleared. Payout processing.", "check_circle"),
        "soft_flagged":    ("Under Verification", "70% provisional payout sent. Verification in progress.", "pending"),
        "hard_flagged":    ("Manual Review", "Claim flagged for manual review. Decision in 4 hours.", "flag"),
        "manual_approved": ("Admin Approved", "Claim approved by admin team.", "verified"),
        "manual_rejected": ("Rejected", f"Claim rejected. Reason: {claim.get('admin_note') or 'Policy violation.'}", "cancel"),
        "paid":            ("Payout Sent", f"₹{float(claim.get('actual_payout') or 0):,.2f} sent to your UPI account.", "payments"),
        "cap_exhausted":   ("Cap Reached", "Weekly coverage cap reached.", "block"),
        "disputed":        ("Dispute Filed", "Dispute filed. Resolution in 72 hours.", "gavel"),
    }
    current_status = claim.get("status", "")
    if current_status in status_map:
        label, desc, icon = status_map[current_status]
        timeline.append({
            "event": f"status_{current_status}",
            "label": label,
            "description": desc,
            "timestamp": (claim.get("cleared_at") or claim.get("paid_at") or claim.get("admin_action_at") or claim["initiated_at"]).isoformat()
                         if any([claim.get("cleared_at"), claim.get("paid_at"), claim.get("admin_action_at")]) else None,
            "status": "completed" if current_status in ("auto_cleared", "manual_approved", "paid") else
                      "error" if current_status in ("manual_rejected", "cap_exhausted") else "pending",
            "icon": icon,
        })

    # 4. Payout records
    payouts = await conn.fetch(
        """
        SELECT amount, payout_type, razorpay_status, released_at
        FROM payouts WHERE claim_id = $1
        ORDER BY released_at ASC
        """,
        claim_id,
    )
    for p in payouts:
        type_labels = {
            "initial": "Initial Payout", "provisional": "Provisional Payout (70%)",
            "remainder": "Remaining Payout (30%)", "continuation": "Continuation Payout",
        }
        timeline.append({
            "event": "payout",
            "label": type_labels.get(p["payout_type"], "Payout"),
            "description": f"₹{float(p['amount']):,.2f} — {p['razorpay_status']}",
            "timestamp": p["released_at"].isoformat() if p.get("released_at") else None,
            "status": "completed" if p["razorpay_status"] == "success" else
                      "error" if p["razorpay_status"] == "failed" else "pending",
            "icon": "payments",
            "amount": float(p["amount"]),
        })

    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"] or "")

    return {
        "claim_id": str(claim_id),
        "current_status": current_status,
        "fraud_score": float(claim.get("fraud_score") or 0),
        "event_payout": float(claim.get("event_payout") or 0),
        "actual_payout": float(claim.get("actual_payout") or 0),
        "explanation": claim.get("explanation_text"),
        "timeline": timeline,
    }
