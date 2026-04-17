"""workers/notification_worker.py — Multi-channel notification delivery worker.

WhatsApp channel REMOVED per product decision. Delivers push (FCM) only.

FIX: Pool created once per task invocation and passed to _deliver()
     instead of creating a new pool per message (which exhausted connections).
"""
from __future__ import annotations

import json
import asyncio
import asyncpg
import structlog

from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.workers.notification_worker.send_pending_notifications")
def send_pending_notifications():
    """Drain the notification queue and deliver via push/SMS (WhatsApp removed)."""
    from app.config import get_settings
    from app.core.redis_client import get_sync_redis
    from app.services.notification_service import render_template, send_fcm_push

    redis = get_sync_redis()
    settings = get_settings()

    async def _run_all(messages: list[dict]):
        """Create ONE pool for the entire batch, pass conn to each delivery."""
        pool = await asyncpg.create_pool(
            settings.database_url, min_size=1, max_size=5
        )
        try:
            tasks = [_deliver(pool, m, settings) for m in messages]
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await pool.close()

    async def _deliver(pool, message: dict, settings):
        rider_id   = message.get("rider_id")
        event_type = message.get("event_type")
        context    = message.get("context", {})
        channels   = message.get("channels", ["push"])

        # Defensive: strip whatsapp if any old message in queue still has it
        channels = [c for c in channels if c != "whatsapp"]
        if not channels:
            channels = ["push"]

        async with pool.acquire() as conn:
            rider = await conn.fetchrow(
                "SELECT phone, name FROM riders WHERE id = $1::uuid", rider_id
            )
            if not rider:
                return

            rendered = render_template(event_type, context)

            # Persist notification record
            try:
                await conn.execute(
                    """
                    INSERT INTO notifications (rider_id, type, channel, message, status)
                    VALUES ($1::uuid, $2, $3, $4, 'pending')
                    ON CONFLICT DO NOTHING
                    """,
                    rider_id, event_type, ",".join(channels), rendered,
                )
            except Exception:
                pass

        # FCM push delivery
        if "push" in channels:
            title_map = {
                "payout_success": "💰 Payout Sent!",
                "trigger_active": "🚨 Zone Alert",
                "claim_approved": "✅ Claim Approved",
                "policy_renewed": "🛡️ Policy Renewed",
            }
            title = title_map.get(event_type, "GigShield")
            body  = render_template(event_type, context)
            try:
                await send_fcm_push(rider_id, title, body, {"event_type": event_type})
            except Exception as exc:
                log.error("fcm_delivery_failed", error=str(exc))

    # Drain up to 100 messages per run
    messages = []
    for _ in range(100):
        raw = redis.rpop("notification_queue")
        if not raw:
            break
        try:
            messages.append(json.loads(raw))
        except Exception:
            pass

    if not messages:
        return

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run_all(messages))
        loop.close()
    except Exception as exc:
        log.error("notification_batch_failed", error=str(exc))
        return

    log.info("notifications_delivered", count=len(messages))
