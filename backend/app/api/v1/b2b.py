"""
api/v1/b2b.py — B2B Hub API for Zepto/Blinkit/Instamart integration

UNICORN FEATURE: Revenue stream via B2B API
Allows platforms to query their fleet's GigShield coverage status.

Auth: X-Hub-API-Key header (hashed key stored in hubs.api_key)
Rate limited: 100 requests/minute per hub.

Endpoints:
  GET /b2b/hubs/{hub_id}/fleet-coverage  — fleet coverage summary
  GET /b2b/hubs/{hub_id}/active-triggers — active trigger events
  GET /b2b/hubs/{hub_id}/payout-stats    — weekly payout statistics
"""
from __future__ import annotations

import hashlib
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Path

from app.core.database import get_db_connection

router = APIRouter(prefix="/b2b", tags=["b2b"])
log = structlog.get_logger()


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def _authenticate_hub(
    hub_id: str,
    x_hub_api_key: str,
    conn: asyncpg.Connection,
) -> dict:
    """Validate hub API key against stored hash."""
    hub = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1", uuid_mod.UUID(hub_id))
    if not hub:
        raise HTTPException(status_code=404, detail="Hub not found")

    stored_hash = hub.get("api_key")
    if not stored_hash or stored_hash == "placeholder":
        raise HTTPException(
            status_code=503,
            detail="B2B API key not configured for this hub. Contact GigShield admin."
        )

    if _hash_api_key(x_hub_api_key) != stored_hash:
        log.warning("b2b_invalid_api_key", hub_id=hub_id)
        raise HTTPException(status_code=401, detail="Invalid API key")

    return dict(hub)


@router.get("/hubs/{hub_id}/fleet-coverage")
async def fleet_coverage(
    hub_id: str = Path(...),
    x_hub_api_key: str = Header(..., alias="X-Hub-API-Key"),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Return fleet coverage summary for the hub.
    Used by Zepto/Blinkit/Instamart to display coverage badges in their rider apps.
    """
    hub = await _authenticate_hub(hub_id, x_hub_api_key, conn)

    active_policies = await conn.fetchval(
        "SELECT COUNT(*) FROM policies WHERE hub_id = $1 AND status = 'active'",
        uuid_mod.UUID(hub_id),
    )

    total_riders = await conn.fetchval(
        "SELECT COUNT(*) FROM riders WHERE hub_id = $1", uuid_mod.UUID(hub_id)
    )

    coverage_pct_dist = await conn.fetch(
        """
        SELECT plan, COUNT(*) AS count, AVG(coverage_pct) AS avg_coverage
        FROM policies
        WHERE hub_id = $1 AND status = 'active'
        GROUP BY plan ORDER BY plan
        """,
        uuid_mod.UUID(hub_id),
    )

    weekly_payouts = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(p.amount), 0) AS total, COUNT(*) AS count
        FROM payouts p
        JOIN policies pol ON p.policy_id = pol.id
        WHERE pol.hub_id = $1
          AND p.released_at >= NOW() - INTERVAL '7 days'
          AND p.payout_type != 'premium_debit'
        """,
        uuid_mod.UUID(hub_id),
    )

    active_trigger = await conn.fetchrow(
        """
        SELECT trigger_type, oracle_score, triggered_at
        FROM trigger_events
        WHERE h3_index = $1 AND status IN ('active','resolving')
        ORDER BY triggered_at DESC LIMIT 1
        """,
        hub["h3_index_res9"],
    )

    return {
        "hub_id": hub_id,
        "hub_name": hub["name"],
        "platform": hub["platform"],
        "city": hub["city"],
        "fleet_stats": {
            "total_riders": int(total_riders or 0),
            "covered_riders": int(active_policies or 0),
            "coverage_rate": round(
                int(active_policies or 0) / max(int(total_riders or 1), 1), 3
            ),
        },
        "plan_distribution": [
            {
                "plan": r["plan"],
                "count": int(r["count"]),
                "avg_coverage_pct": round(float(r["avg_coverage"] or 0) * 100, 1),
            }
            for r in coverage_pct_dist
        ],
        "weekly_payouts": {
            "total_inr": float(weekly_payouts["total"] or 0),
            "count": int(weekly_payouts["count"] or 0),
        },
        "active_trigger": {
            "type": active_trigger["trigger_type"],
            "oracle_score": float(active_trigger["oracle_score"] or 0),
            "since": active_trigger["triggered_at"].isoformat(),
        } if active_trigger else None,
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/hubs/{hub_id}/active-triggers")
async def active_triggers(
    hub_id: str = Path(...),
    x_hub_api_key: str = Header(..., alias="X-Hub-API-Key"),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """Return all active/recent trigger events for this hub's zone."""
    hub = await _authenticate_hub(hub_id, x_hub_api_key, conn)

    triggers = await conn.fetch(
        """
        SELECT id, trigger_type, oracle_score, status, triggered_at, resolved_at, is_synthetic
        FROM trigger_events
        WHERE h3_index = $1
          AND triggered_at >= NOW() - INTERVAL '48 hours'
        ORDER BY triggered_at DESC
        LIMIT 20
        """,
        hub["h3_index_res9"],
    )

    return {
        "hub_id": hub_id,
        "triggers": [
            {
                "id": str(t["id"]),
                "type": t["trigger_type"],
                "oracle_score": float(t["oracle_score"] or 0),
                "status": t["status"],
                "triggered_at": t["triggered_at"].isoformat(),
                "resolved_at": t["resolved_at"].isoformat() if t["resolved_at"] else None,
                "is_synthetic": t["is_synthetic"],
            }
            for t in triggers
        ],
    }


@router.get("/hubs/{hub_id}/payout-stats")
async def payout_stats(
    hub_id: str = Path(...),
    x_hub_api_key: str = Header(..., alias="X-Hub-API-Key"),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """Return payout statistics for investor/partner reporting."""
    hub = await _authenticate_hub(hub_id, x_hub_api_key, conn)

    stats = await conn.fetchrow(
        """
        SELECT
            COUNT(*) AS total_payouts,
            COALESCE(SUM(p.amount), 0) AS total_amount,
            COALESCE(AVG(p.amount), 0) AS avg_amount,
            COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type = 'premium_debit'), 0) AS premiums_collected,
            COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type != 'premium_debit'), 0) AS payouts_issued
        FROM payouts p
        JOIN policies pol ON p.policy_id = pol.id
        WHERE pol.hub_id = $1
          AND p.released_at >= NOW() - INTERVAL '30 days'
        """,
        uuid_mod.UUID(hub_id),
    )

    premiums = float(stats["premiums_collected"] or 0)
    payouts_issued = float(stats["payouts_issued"] or 0)
    loss_ratio = payouts_issued / premiums if premiums > 0 else 0.0

    return {
        "hub_id": hub_id,
        "period": "last_30_days",
        "total_payouts": int(stats["total_payouts"] or 0),
        "total_amount_inr": float(stats["total_amount"] or 0),
        "avg_payout_inr": round(float(stats["avg_amount"] or 0), 2),
        "premiums_collected_inr": premiums,
        "payouts_issued_inr": payouts_issued,
        "loss_ratio": round(loss_ratio, 4),
        "queried_at": datetime.now(timezone.utc).isoformat(),
    }
