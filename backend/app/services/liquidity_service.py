"""
services/liquidity_service.py — AUDIT FIXED

GAP-06 FIX: Liquidity mode now writes to system_config so payout_service reads it.
GAP-05 FIX: Loss ratio guardrails write lambda_floor and p_base_margin_pct to system_config.
"""
from __future__ import annotations

import json, time
import asyncpg
import structlog

from app.config import get_settings
from app.core.redis_client import get_sync_redis
from app.external.razorpay_client import get_balance

settings = get_settings()
log      = structlog.get_logger()

BALANCE_CACHE_KEY  = "liquidity:razorpay_balance"
BALANCE_CACHE_TTL  = 240
STALE_THRESHOLD    = 900


async def compute_liquidity_snapshot(conn: asyncpg.Connection) -> dict:
    redis = get_sync_redis()

    cached = redis.get(BALANCE_CACHE_KEY)
    balance_stale = False

    if cached:
        cached_data      = json.loads(cached)
        age              = time.time() - cached_data.get("ts", 0)
        razorpay_balance = cached_data["balance"]
        if age > STALE_THRESHOLD:
            balance_stale = True
    else:
        try:
            razorpay_balance = get_balance()
            redis.set(BALANCE_CACHE_KEY, json.dumps({"balance": razorpay_balance, "ts": time.time()}), ex=BALANCE_CACHE_TTL)
        except Exception as exc:
            log.error("balance_fetch_failed", error=str(exc))
            razorpay_balance = 0.0
            balance_stale    = True

    reserve_buffer   = settings.reserve_buffer_inr
    available_cash   = razorpay_balance + reserve_buffer

    pending = await conn.fetchval(
        "SELECT COALESCE(SUM(actual_payout),0) FROM claims WHERE status IN ('auto_cleared','soft_flagged') AND paid_at IS NULL"
    ) or 0.0

    active_triggers  = await conn.fetchval("SELECT COUNT(*) FROM trigger_events WHERE status IN ('active','resolving')") or 0
    avg_payout       = await conn.fetchval("SELECT COALESCE(AVG(amount),0) FROM payouts WHERE released_at>=NOW()-INTERVAL '7 days' AND payout_type!='premium_debit'") or 500.0
    avg_policies     = await conn.fetchval("""
        SELECT COALESCE(AVG(cnt),0) FROM (
            SELECT COUNT(*) AS cnt FROM policies JOIN hubs ON policies.hub_id=hubs.id
            WHERE policies.status='active' GROUP BY hubs.h3_index_res9
        ) t
    """) or 10.0

    expected_payouts_24h = float(pending) + int(active_triggers)*float(avg_payout)*float(avg_policies)
    liquidity_ratio      = available_cash / max(expected_payouts_24h, 1.0)
    mode                 = _classify_mode(liquidity_ratio, balance_stale)

    # GAP-06 FIX: Write mode to system_config so payout_service reads it
    await conn.execute(
        "UPDATE system_config SET value=$1, updated_at=NOW() WHERE key='liquidity_mode'",
        mode,
    )

    await conn.execute(
        """
        INSERT INTO liquidity_snapshots (
            razorpay_balance, reserve_buffer, available_cash,
            expected_payouts_24h, liquidity_ratio, mode,
            active_trigger_count, pending_payouts_inr, balance_stale
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        razorpay_balance, reserve_buffer, available_cash,
        expected_payouts_24h, liquidity_ratio, mode,
        int(active_triggers), float(pending), balance_stale,
    )

    # GAP-05 FIX: Loss ratio guardrails write lambda_floor + p_base_margin to system_config
    loss_ratio = await _compute_loss_ratio(conn)
    await _apply_loss_ratio_guardrails(conn, loss_ratio)

    log.info("liquidity_snapshot", ratio=round(liquidity_ratio, 3), mode=mode, loss_ratio=round(loss_ratio, 4))
    return {
        "liquidity_ratio": liquidity_ratio, "mode": mode,
        "available_cash": available_cash, "expected_payouts_24h": expected_payouts_24h,
        "razorpay_balance": razorpay_balance, "balance_stale": balance_stale,
        "loss_ratio": loss_ratio,
    }


async def _compute_loss_ratio(conn: asyncpg.Connection) -> float:
    row = await conn.fetchrow(
        """
        SELECT
            COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type != 'premium_debit'), 0) AS payouts,
            COALESCE(SUM(p.amount) FILTER (WHERE p.payout_type = 'premium_debit'), 0)  AS premiums
        FROM payouts p
        WHERE p.released_at >= NOW() - INTERVAL '30 days'
        """
    )
    premiums = float(row["premiums"] or 0)
    if premiums == 0:
        return 0.0
    return float(row["payouts"] or 0) / premiums


async def _apply_loss_ratio_guardrails(conn: asyncpg.Connection, loss_ratio: float) -> None:
    """
    GAP-05 FIX: Write lambda_floor and p_base_margin to system_config.
    Spec §12.1:
      ORANGE (0.80–0.85): λ_floor = 1.10
      RED    (> 0.85):    λ_floor = 1.20, p_base_margin = 0.15
      > 1.0:              trigger Solvency Swap
    """
    if loss_ratio > 1.0:
        await conn.execute("UPDATE system_config SET value='1.20' WHERE key='lambda_floor'")
        await conn.execute("UPDATE system_config SET value='0.15' WHERE key='p_base_margin_pct'")
        log.error("LOSS_RATIO_CRITICAL", loss_ratio=loss_ratio)
        await _send_admin_alert(f"🚨 LOSS RATIO CRITICAL: {loss_ratio:.2%}. Solvency swap triggered.")
        await _trigger_solvency_swap(conn)
    elif loss_ratio > 0.85:
        await conn.execute("UPDATE system_config SET value='1.20' WHERE key='lambda_floor'")
        await conn.execute("UPDATE system_config SET value='0.15' WHERE key='p_base_margin_pct'")
        log.error("loss_ratio_red", loss_ratio=loss_ratio)
        await _send_admin_alert(f"🔴 LOSS RATIO RED: {loss_ratio:.2%}. λ_floor=1.20, margin=15%.")
    elif loss_ratio > 0.80:
        await conn.execute("UPDATE system_config SET value='1.10' WHERE key='lambda_floor'")
        log.warning("loss_ratio_orange", loss_ratio=loss_ratio)
        await _send_admin_alert(f"🟠 LOSS RATIO ORANGE: {loss_ratio:.2%}. λ_floor=1.10.")
    else:
        # Healthy — restore defaults
        await conn.execute("UPDATE system_config SET value='1.0'  WHERE key='lambda_floor'")
        await conn.execute("UPDATE system_config SET value='0.25' WHERE key='p_base_margin_pct'")


async def _trigger_solvency_swap(conn: asyncpg.Connection) -> None:
    """GAP-12: Solvency swap — compute expected claims and log. Real reinsurance in Phase 3."""
    expected_claims = float(await conn.fetchval(
        "SELECT COALESCE(SUM(actual_payout),0) FROM claims WHERE status NOT IN ('paid','rejected')"
    ) or 0)
    inject_amount = max(0.0, expected_claims * 1.2)
    await conn.execute(
        """
        INSERT INTO entity_state_log (entity_type, entity_id, to_state, reason, metadata)
        VALUES ('solvency_swap', gen_random_uuid(), 'triggered', 'stop_loss', $1::jsonb)
        """,
        json.dumps({"inject_amount": inject_amount, "expected_claims": expected_claims}),
    )
    await _send_admin_alert(f"🚨 SOLVENCY SWAP TRIGGERED. Expected claims: ₹{expected_claims:.0f}. Inject: ₹{inject_amount:.0f}")


def _classify_mode(ratio: float, balance_stale: bool) -> str:
    if balance_stale and ratio < 1.2: return "cautious"
    if ratio >= 1.5:                  return "normal"
    elif ratio >= 1.2:                return "elevated"
    elif ratio >= 1.0:                return "cautious"
    elif ratio >= 0.8:                return "stressed"
    return "emergency"


async def _send_admin_alert(message: str) -> None:
    import httpx
    if not settings.admin_webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(settings.admin_webhook_url, json={"text": message})
    except Exception:
        pass


def get_rider_payout_message(mode: str, amount: float) -> str:
    """Never say 'liquidity'. Say 'high demand'."""
    msgs = {
        "normal":    f"₹{amount:.0f} sent to your UPI account.",
        "elevated":  f"₹{amount:.0f} sent to your UPI account.",
        "cautious":  f"Your payout of ₹{amount:.0f} is confirmed. Due to high demand, it will arrive within 1 hour.",
        "stressed":  f"Your payout of ₹{amount:.0f} is confirmed. Due to high demand, it will arrive within 2 hours.",
        "emergency": f"Your payout of ₹{amount:.0f} is confirmed and queued. Due to high demand today, it will arrive within 4 hours.",
    }
    return msgs.get(mode, msgs["normal"])
