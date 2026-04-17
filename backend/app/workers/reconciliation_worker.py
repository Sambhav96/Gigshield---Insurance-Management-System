"""workers/reconciliation_worker.py — BUG-06/07 FIXED: actual Razorpay polling."""
from __future__ import annotations
import asyncio, structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="app.workers.reconciliation_worker.poll_stuck_payouts")
def poll_stuck_payouts():
    """Every 30 min: Layer 2 — BUG-06 FIXED with actual Razorpay fetch."""
    import asyncpg
    from app.config import get_settings
    from app.services.reconciliation_service import reconcile_stuck_payouts

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            result = await reconcile_stuck_payouts(conn)
        await pool.close()
        return result

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_run())
        loop.close()
        log.info("layer2_reconcile_done", result=result)
    except Exception as exc:
        log.error("layer2_reconcile_failed", error=str(exc))


@celery_app.task(name="app.workers.reconciliation_worker.run_daily_reconciliation")
def run_daily_reconciliation():
    """Daily 03:00 UTC: Layer 3 — BUG-07 FIXED with spec schema."""
    import asyncpg
    from app.config import get_settings
    from app.services.reconciliation_service import run_daily_reconciliation as _layer3

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            result = await _layer3(conn)
        await pool.close()
        return result

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_run())
        loop.close()
        log.info("layer3_reconcile_done", result=result)
    except Exception as exc:
        log.error("layer3_reconcile_failed", error=str(exc))
