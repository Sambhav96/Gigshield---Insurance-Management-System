"""api/internal/webhooks.py — Razorpay webhook receiver."""
from __future__ import annotations

import json
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.dependencies import get_db
from app.utils.crypto import verify_razorpay_webhook

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Receives Razorpay payout.processed / payout.failed / payout.reversed events.
    Full idempotency: check webhook_events before processing.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify HMAC
    if not verify_razorpay_webhook(body, signature, settings.razorpay_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(body)
    event_type = payload.get("event")
    event_id = payload.get("id") or payload.get("payload", {}).get("payout", {}).get("entity", {}).get("id", "")

    # Idempotency: skip if already processed
    existing = await conn.fetchrow(
        "SELECT id FROM webhook_events WHERE event_id = $1", event_id
    )
    if existing:
        return {"status": "already_processed"}

    # Mark as received
    await conn.execute(
        "INSERT INTO webhook_events (event_id, event_type, payload, processed) VALUES ($1,$2,$3::jsonb,false)",
        event_id, event_type, json.dumps(payload),
    )

    payout_entity = payload.get("payload", {}).get("payout", {}).get("entity", {})
    razorpay_ref = payout_entity.get("id")
    reference_id = payout_entity.get("reference_id")  # our idempotency_key (first 40 chars)

    if event_type == "payout.processed":
        await conn.execute(
            "UPDATE payouts SET razorpay_status='success', reconcile_status='matched', reconciled_at=NOW() "
            "WHERE razorpay_ref=$1 OR idempotency_key LIKE $2",
            razorpay_ref, (reference_id or "") + "%",
        )
        # BUG-04 FIX: Webhook is the authoritative source for marking claims 'paid'.
        # Workers set status='auto_cleared'; this webhook promotes to 'paid' + sets paid_at.
        await conn.execute(
            """
            UPDATE claims
            SET status = 'paid', paid_at = NOW()
            WHERE id IN (
                SELECT DISTINCT claim_id FROM payouts
                WHERE razorpay_ref = $1 AND claim_id IS NOT NULL
            ) AND status = 'auto_cleared'
            """,
            razorpay_ref,
        )

    elif event_type == "payout.failed":
        await conn.execute(
            "UPDATE payouts SET razorpay_status='failed' WHERE razorpay_ref=$1",
            razorpay_ref,
        )
        # Queue retry
        from app.workers.payout_worker import process_claim_payout_task
        payout_row = await conn.fetchrow(
            "SELECT claim_id, payout_type FROM payouts WHERE razorpay_ref=$1", razorpay_ref
        )
        if payout_row and payout_row["claim_id"]:
            process_claim_payout_task.apply_async(
                args=[str(payout_row["claim_id"]), payout_row["payout_type"]],
                countdown=300,
            )

    elif event_type == "payout.reversed":
        await conn.execute(
            "UPDATE payouts SET razorpay_status='reversed' WHERE razorpay_ref=$1",
            razorpay_ref,
        )
        import structlog
        structlog.get_logger().error(
            "payout_reversed", razorpay_ref=razorpay_ref,
            entity=payout_entity
        )

    await conn.execute(
        "UPDATE webhook_events SET processed=true WHERE event_id=$1", event_id
    )
    return {"status": "processed"}
