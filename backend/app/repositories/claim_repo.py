"""repositories/claim_repo.py — All DB operations for claims."""
from __future__ import annotations

import uuid
from typing import Optional
import asyncpg

from app.core.idempotency import make_claim_key


async def get_claim_by_id(conn: asyncpg.Connection, claim_id: str) -> Optional[dict]:
    row = await conn.fetchrow("SELECT * FROM claims WHERE id = $1", uuid.UUID(claim_id))
    return dict(row) if row else None


async def create_claim(
    conn: asyncpg.Connection,
    rider_id: str,
    policy_id: str,
    trigger_id: str,
    oracle_confidence: float,
    duration_hrs: float,
    mu_time: float,
    event_payout: float,
    fraud_score: float,
    presence_confidence: float,
    intent_factors: dict,
    explanation_text: str,
    admin_trace: dict,
) -> Optional[str]:
    """
    Insert a new claim with idempotency check.
    Returns claim_id or None if already exists (idempotent).
    """
    idem_key = make_claim_key(rider_id, trigger_id, policy_id)

    row = await conn.fetchrow(
        """
        INSERT INTO claims (
            rider_id, policy_id, trigger_id, idempotency_key,
            status, oracle_confidence, presence_confidence,
            intent_factor1_gps, intent_factor2_session, intent_factor3_platform,
            fraud_score, event_payout, duration_hrs, mu_time,
            explanation_text, admin_trace
        )
        VALUES ($1,$2,$3,$4,'evaluating',$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        uuid.UUID(rider_id), uuid.UUID(policy_id), uuid.UUID(trigger_id),
        idem_key, oracle_confidence, presence_confidence,
        intent_factors.get("f1_gps", False),
        intent_factors.get("f2_session", False),
        intent_factors.get("f3_platform", False),
        fraud_score, event_payout, duration_hrs, mu_time,
        explanation_text,
        __import__("json").dumps(admin_trace),
    )
    return str(row["id"]) if row else None


async def list_claims_for_rider(
    conn: asyncpg.Connection,
    rider_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if status:
        rows = await conn.fetch(
            """
            SELECT * FROM claims WHERE rider_id = $1 AND status = $2
            ORDER BY initiated_at DESC LIMIT $3 OFFSET $4
            """,
            uuid.UUID(rider_id), status, limit, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE rider_id = $1 AND status = $2",
            uuid.UUID(rider_id), status,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM claims WHERE rider_id = $1 ORDER BY initiated_at DESC LIMIT $2 OFFSET $3",
            uuid.UUID(rider_id), limit, offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM claims WHERE rider_id = $1", uuid.UUID(rider_id)
        )
    return [dict(r) for r in rows], int(total or 0)


async def update_claim_status(
    conn: asyncpg.Connection,
    claim_id: str,
    status: str,
    admin_id: Optional[str] = None,
    admin_note: Optional[str] = None,
    custom_amount: Optional[float] = None,
) -> None:
    await conn.execute(
        """
        UPDATE claims
        SET status = $1,
            admin_id = $2,
            admin_note = $3,
            admin_custom_amount = $4,
            admin_action = $1,
            admin_action_at = NOW()
        WHERE id = $5
        """,
        status,
        uuid.UUID(admin_id) if admin_id else None,
        admin_note,
        custom_amount,
        uuid.UUID(claim_id),
    )


async def get_hard_flagged_claims(
    conn: asyncpg.Connection, limit: int = 50
) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT c.*, r.phone as rider_phone, r.name as rider_name,
               te.trigger_type, te.triggered_at
        FROM claims c
        JOIN riders r ON c.rider_id = r.id
        JOIN trigger_events te ON c.trigger_id = te.id
        WHERE c.status IN ('hard_flagged','manual_review')
        ORDER BY c.fraud_score DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]
