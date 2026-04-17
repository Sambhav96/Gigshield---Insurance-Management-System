"""workers/metrics_worker.py — GAP-15 FIX: metrics snapshot + alert dispatch."""
from __future__ import annotations
import asyncio, structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    c = psycopg2.connect(get_settings().database_url)
    c.autocommit = True
    return c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.metrics_worker.take_metrics_snapshot")
def take_metrics_snapshot():
    """Every 15 min: write metrics + GAP-15 dispatch alerts."""
    conn, cur = _conn()
    try:
        metrics = _collect_metrics(cur)
        for name, value in metrics.items():
            cur.execute(
                "INSERT INTO metrics_timeseries(metric_name,value,recorded_at) VALUES(%s,%s,NOW())",
                (name, float(value)),
            )
        log.debug("metrics_written", count=len(metrics))

        # GAP-15 FIX: Run alert evaluation after writing metrics
        _run_alert_evaluation_sync(metrics)

    finally:
        cur.close(); conn.close()


def _run_alert_evaluation_sync(current_metrics: dict):
    """Synchronous alert dispatch using current metric values."""
    from app.config import get_settings
    import httpx

    settings = get_settings()

    ALERT_RULES = [
        ("loss_ratio_realtime",       ">", 0.85,   "🔴 Loss ratio {val:.1%} > 85%"),
        ("liquidity_ratio",           "<", 1.2,    "⚠️ Liquidity ratio {val:.3f} < 1.2"),
        ("liquidity_ratio",           "<", 1.0,    "🚨 CRITICAL: Liquidity {val:.3f} < 1.0"),
        ("failed_payouts_last_hour",  ">", 3,      "Payout failures last hour: {val:.0f}"),
        ("hard_flag_rate_last_hour",  ">", 0.20,   "Hard-flag rate {val:.1%} > 20%"),
        ("auto_clear_rate_last_hour", "<", 0.50,   "Auto-clear rate {val:.1%} too low"),
        ("fraud_queue_depth",         ">", 50,     "Fraud queue depth: {val:.0f}"),
        ("pending_payouts_total_inr", ">", 500000, "Pending payouts ₹{val:,.0f}"),
    ]

    fired = []
    for metric, op, thr, tmpl in ALERT_RULES:
        val = current_metrics.get(metric)
        if val is None:
            continue
        val = float(val)
        if (op == ">" and val > thr) or (op == "<" and val < thr):
            msg = tmpl.format(val=val)
            fired.append(msg)
            log.warning("alert_fired", metric=metric, val=val, threshold=thr)

    # Razorpay circuit breaker
    from app.external.circuit_breaker import get_circuit_breaker, CBState
    rz_cb = get_circuit_breaker("razorpay")
    if rz_cb.get_state() == CBState.OPEN:
        fired.append("🚨 Razorpay circuit breaker OPEN — payouts halted")

    if fired and settings.admin_webhook_url:
        try:
            with httpx.Client(timeout=5) as client:
                client.post(settings.admin_webhook_url, json={
                    "text": "\n".join(fired), "source": "gigshield-alerts"
                })
        except Exception as e:
            log.error("alert_webhook_failed", error=str(e))

    return fired


@celery_app.task(name="app.workers.metrics_worker.take_liquidity_snapshot")
def take_liquidity_snapshot():
    """Every 5 min: GAP-06 FIX — writes liquidity_mode to system_config."""
    import asyncpg
    from app.config import get_settings
    from app.services.liquidity_service import compute_liquidity_snapshot

    async def _run():
        pool = await asyncpg.create_pool(get_settings().database_url, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            result = await compute_liquidity_snapshot(conn)
        await pool.close()
        return result

    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run())
        loop.close()
    except Exception as exc:
        log.error("liquidity_snapshot_failed", error=str(exc))


@celery_app.task(name="app.workers.metrics_worker.check_solvency")
def check_solvency():
    conn, cur = _conn()
    try:
        cur.execute("SELECT COALESCE(SUM(actual_payout),0) AS exp FROM claims WHERE status NOT IN ('paid','rejected')")
        expected = float(cur.fetchone()["exp"] or 0)
        cur.execute("SELECT value::float FROM system_config WHERE key='capital_reserves'")
        row = cur.fetchone()
        reserves = float(row["value"]) if row else 500000.0
        ratio = (reserves) / max(expected, 1.0)
        cur.execute("INSERT INTO metrics_timeseries(metric_name,value,recorded_at) VALUES('solvency_ratio',%s,NOW())", (ratio,))
        if ratio < 1.0:
            log.error("SOLVENCY_CRITICAL", ratio=ratio)
        elif ratio < 1.2:
            log.warning("solvency_warning", ratio=ratio)
    finally:
        cur.close(); conn.close()


def _collect_metrics(cur) -> dict:
    m = {}
    cur.execute("SELECT COUNT(*) AS c FROM policies WHERE status='active'")
    m["active_policies_count"] = cur.fetchone()["c"] or 0

    cur.execute("SELECT COUNT(*) AS c, COALESCE(SUM(amount),0) AS s FROM payouts WHERE released_at>=NOW()-INTERVAL '15 minutes' AND payout_type!='premium_debit'")
    r = cur.fetchone()
    m["payouts_last_15min_count"] = r["c"] or 0
    m["payouts_last_15min_sum"]   = r["s"] or 0

    cur.execute("SELECT COUNT(*) AS c FROM trigger_events WHERE status IN ('active','resolving')")
    m["active_trigger_count"] = cur.fetchone()["c"] or 0

    cur.execute("SELECT COUNT(*) AS c FROM claims WHERE status IN ('hard_flagged','manual_review')")
    m["fraud_queue_depth"] = cur.fetchone()["c"] or 0

    cur.execute("SELECT COUNT(*) FILTER(WHERE status='auto_cleared')*1.0/NULLIF(COUNT(*),0) AS r FROM claims WHERE initiated_at>=NOW()-INTERVAL '1 hour'")
    r = cur.fetchone()
    m["auto_clear_rate_last_hour"] = float(r["r"] or 0)

    cur.execute("SELECT COUNT(*) FILTER(WHERE status='hard_flagged')*1.0/NULLIF(COUNT(*),0) AS r FROM claims WHERE initiated_at>=NOW()-INTERVAL '1 hour'")
    r = cur.fetchone()
    m["hard_flag_rate_last_hour"] = float(r["r"] or 0)

    cur.execute("SELECT COUNT(*) AS c FROM payouts WHERE razorpay_status='failed' AND released_at>=NOW()-INTERVAL '1 hour'")
    m["failed_payouts_last_hour"] = cur.fetchone()["c"] or 0

    cur.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payouts WHERE razorpay_status IN ('initiated','processing') AND payout_type!='premium_debit'")
    m["pending_payouts_total_inr"] = float(cur.fetchone()["s"] or 0)

    cur.execute("""
        SELECT COALESCE(SUM(p.amount) FILTER(WHERE p.payout_type!='premium_debit'),0)*1.0/
               NULLIF(SUM(p.amount) FILTER(WHERE p.payout_type='premium_debit'),0) AS lr
        FROM payouts p WHERE p.released_at>=NOW()-INTERVAL '7 days'
    """)
    r = cur.fetchone()
    m["loss_ratio_realtime"] = float(r["lr"] or 0)

    # Last liquidity snapshot
    cur.execute("SELECT liquidity_ratio FROM liquidity_snapshots ORDER BY created_at DESC LIMIT 1")
    r = cur.fetchone()
    if r:
        m["liquidity_ratio"] = float(r["liquidity_ratio"] or 0)

    return m
