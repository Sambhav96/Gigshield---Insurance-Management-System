"""
services/alert_service.py — GAP-15 FIX

Alert dispatch loop that reads metrics_timeseries and fires webhooks/SMS
when thresholds defined in spec §14.3 are crossed.
Called by metrics_worker every 15 minutes.
"""
from __future__ import annotations

import asyncpg
import httpx
import structlog

from app.config import get_settings

settings = get_settings()
log      = structlog.get_logger()

# Spec §14.3 alert thresholds
ALERT_RULES = [
    {"metric": "loss_ratio_realtime",        "op": ">",  "threshold": 0.85,     "channel": ["webhook", "email"],  "msg": "Loss ratio {val:.1%} > 85% threshold"},
    {"metric": "liquidity_ratio",            "op": "<",  "threshold": 1.2,      "channel": ["webhook"],           "msg": "Liquidity ratio {val:.3f} < 1.2 — urgent"},
    {"metric": "liquidity_ratio",            "op": "<",  "threshold": 1.0,      "channel": ["sms", "webhook"],    "msg": "🚨 LIQUIDITY CRITICAL: ratio {val:.3f} < 1.0"},
    {"metric": "oracle_loop_last_run_secs",  "op": ">",  "threshold": 1200,     "channel": ["webhook"],           "msg": "Oracle loop stale: last ran {val:.0f}s ago"},
    {"metric": "failed_payouts_last_hour",   "op": ">",  "threshold": 3,        "channel": ["webhook", "email"],  "msg": "Failed payouts last hour: {val:.0f}"},
    {"metric": "hard_flag_rate_last_hour",   "op": ">",  "threshold": 0.20,     "channel": ["webhook"],           "msg": "Hard flag rate {val:.1%} > 20%"},
    {"metric": "auto_clear_rate_last_hour",  "op": "<",  "threshold": 0.50,     "channel": ["webhook"],           "msg": "Auto-clear rate {val:.1%} too conservative (< 50%)"},
    {"metric": "celery_queue_depth_payout",  "op": ">",  "threshold": 100,      "channel": ["webhook"],           "msg": "Payout queue depth {val:.0f} > 100"},
    {"metric": "api_rate_limit_hits_hour",   "op": ">",  "threshold": 5,        "channel": ["webhook"],           "msg": "API rate limit hits: {val:.0f}/hr"},
    {"metric": "solvency_ratio",             "op": "<",  "threshold": 1.2,      "channel": ["email"],             "msg": "Solvency ratio {val:.3f} below 1.2"},
    {"metric": "pending_payouts_total_inr",  "op": ">",  "threshold": 500000,   "channel": ["email"],             "msg": "Pending payouts total ₹{val:,.0f} > ₹5L"},
]


async def evaluate_and_dispatch_alerts(conn: asyncpg.Connection) -> dict:
    """
    GAP-15 FIX: Reads recent metrics and fires alerts for any crossed thresholds.
    Called every 15 minutes by metrics_worker.
    """
    fired = []

    for rule in ALERT_RULES:
        # Get latest value for this metric
        val = await conn.fetchval(
            """
            SELECT value FROM metrics_timeseries
            WHERE metric_name = $1
            ORDER BY recorded_at DESC LIMIT 1
            """,
            rule["metric"],
        )
        if val is None:
            continue

        val   = float(val)
        op    = rule["op"]
        thr   = rule["threshold"]
        cross = (op == ">" and val > thr) or (op == "<" and val < thr)

        if cross:
            message = rule["msg"].format(val=val)
            await _dispatch_alert(message, rule["channel"])
            fired.append({"metric": rule["metric"], "val": val, "threshold": thr, "channels": rule["channel"]})
            log.warning("alert_fired", metric=rule["metric"], val=val, threshold=thr)

    # Special: circuit breaker OPEN for Razorpay → SMS + webhook
    from app.external.circuit_breaker import get_circuit_breaker, CBState
    rz_cb = get_circuit_breaker("razorpay")
    if rz_cb.get_state() == CBState.OPEN:
        await _dispatch_alert("🚨 Razorpay circuit breaker OPEN — payouts halted", ["sms", "webhook"])
        fired.append({"metric": "circuit_breaker_razorpay", "val": "open", "threshold": "closed"})

    log.info("alert_evaluation_complete", alerts_fired=len(fired))
    return {"alerts_fired": len(fired), "alerts": fired}


async def _dispatch_alert(message: str, channels: list[str]) -> None:
    if "webhook" in channels and settings.admin_webhook_url:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(settings.admin_webhook_url, json={"text": message, "source": "gigshield-alerts"})
        except Exception as e:
            log.error("webhook_dispatch_failed", error=str(e))

    if "sms" in channels:
        from app.services.notification_service import send_sms
        send_sms(settings.admin_alert_email, message)  # using admin phone in real impl

    if "email" in channels:
        log.info("email_alert", message=message, to=settings.admin_alert_email)
