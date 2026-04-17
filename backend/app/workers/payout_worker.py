"""workers/payout_worker.py — BUG-01 FIX: trigger IST hour for initial payouts."""
from __future__ import annotations
import time, structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    c = psycopg2.connect(get_settings().database_url)
    c.autocommit = True
    return c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.payout_worker.process_claim_payout_task", bind=True, max_retries=3)
def process_claim_payout_task(self, claim_id: str, payout_type: str = "initial"):
    """Full idempotent payout with 4-layer race protection. BUG-01: trigger IST hour."""
    from app.core.redis_client import get_sync_redis
    from app.core.idempotency import make_payout_key
    from app.external.razorpay_client import create_payout
    from app.core.exceptions import CircuitOpenError
    from app.utils.mu_table import get_mu, get_min_duration, get_confidence_factor

    redis    = get_sync_redis()
    lock_key = f"payout_lock:{claim_id}"
    if not redis.set(lock_key, "1", nx=True, ex=60):
        return {"status": "skipped", "reason": "lock_held"}

    conn, cur = _conn()
    try:
        conn.autocommit = False
        # L2: SELECT FOR UPDATE SKIP LOCKED
        cur.execute("SELECT * FROM claims WHERE id=%s FOR UPDATE SKIP LOCKED", (claim_id,))
        claim = cur.fetchone()
        if not claim:
            conn.rollback(); return {"status": "skipped", "reason": "locked"}
        if claim["status"] in ("paid","rejected","cap_exhausted","manual_rejected"):
            conn.rollback(); return {"status": "skipped", "reason": f"terminal_{claim['status']}"}

        cur.execute("SELECT * FROM policies WHERE id=%s", (str(claim["policy_id"]),))
        policy = cur.fetchone()
        cur.execute("SELECT * FROM riders WHERE id=%s", (str(claim["rider_id"]),))
        rider = cur.fetchone()
        cur.execute("SELECT * FROM trigger_events WHERE id=%s", (str(claim["trigger_id"]),))
        trigger = cur.fetchone()

        # BUG-01 FIX: IST hour from trigger.triggered_at for initial, NOW() for continuation
        if payout_type == "initial":
            cur.execute("SELECT EXTRACT(HOUR FROM %s AT TIME ZONE 'Asia/Kolkata')::int AS h", (trigger["triggered_at"],))
        else:
            cur.execute("SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int AS h")
        ist_hour = cur.fetchone()["h"]
        mu_time  = get_mu(int(ist_hour))

        # Check liquidity mode
        cur.execute("SELECT value FROM system_config WHERE key='liquidity_mode'")
        row = cur.fetchone()
        mode = row["value"] if row else "normal"
        if mode == "emergency":
            conn.rollback()
            redis.zadd("payout_recovery_queue", {claim_id: time.time()})
            return {"status": "queued_emergency"}

        eff_income   = float(rider["effective_income"])
        cov_pct      = float(policy["coverage_pct"])
        dur_hrs      = get_min_duration(trigger["trigger_type"]) if payout_type == "initial" else 0.5
        event_payout = eff_income * cov_pct * (dur_hrs / 8) * mu_time

        oracle_score = float(claim.get("oracle_confidence") or trigger["oracle_score"] or 0.65)
        conf_factor  = get_confidence_factor(oracle_score)
        corr_factor  = float(trigger.get("correlation_factor") or 1.0)
        cool_factor  = float(trigger.get("cooldown_payout_factor") or 1.0)
        final_payout = event_payout * conf_factor * corr_factor * cool_factor
        if mode == "stressed":
            final_payout *= 0.90

        plan_cap_mult = int(policy["plan_cap_multiplier"])
        max_weekly    = eff_income * plan_cap_mult
        weekly_used   = float(policy.get("weekly_payout_used") or 0)
        headroom      = max_weekly - weekly_used
        if headroom <= 0:
            cur.execute("UPDATE claims SET status='cap_exhausted' WHERE id=%s", (claim_id,))
            conn.commit(); return {"status": "cap_exhausted"}
        actual_payout = min(final_payout, headroom)

        # Event cap
        cur.execute("SELECT COALESCE(SUM(p.amount),0) AS t FROM payouts p JOIN claims c ON p.claim_id=c.id WHERE c.trigger_id=%s AND c.rider_id=%s", (str(claim["trigger_id"]), str(claim["rider_id"])))
        event_total = float(cur.fetchone()["t"] or 0)
        if event_total >= max_weekly * 0.50:
            conn.rollback(); return {"status": "event_cap_reached"}

        # Daily soft limit
        if payout_type == "continuation":
            cur.execute("SELECT COALESCE(SUM(amount),0) AS t FROM payouts WHERE rider_id=%s AND released_at>=date_trunc('day',NOW() AT TIME ZONE 'Asia/Kolkata') AND payout_type!='premium_debit'", (str(claim["rider_id"]),))
            if float(cur.fetchone()["t"] or 0) >= max_weekly / 4:
                conn.rollback(); return {"status": "daily_limit_reached"}

        cur.execute("UPDATE policies SET weekly_payout_used=weekly_payout_used+%s WHERE id=%s", (actual_payout, str(policy["id"])))
        cur.execute("UPDATE riders SET annual_payout_total=COALESCE(annual_payout_total,0)+%s WHERE id=%s", (actual_payout, str(rider["id"])))

        # L3: atomic status guard
        # BUG-04 FIX: mark 'auto_cleared' here; Razorpay webhook sets 'paid' + paid_at
        cur.execute("UPDATE claims SET status='auto_cleared',actual_payout=%s WHERE id=%s AND status NOT IN ('paid','rejected','auto_cleared') RETURNING id", (actual_payout, claim_id))
        if not cur.fetchone():
            conn.rollback(); return {"status": "already_paid"}

        # L4: idempotency key
        idem_key = make_payout_key(claim_id, payout_type, actual_payout)
        cur.execute("""
            INSERT INTO payouts(claim_id,rider_id,policy_id,amount,payout_type,idempotency_key,razorpay_status,released_at)
            VALUES(%s,%s,%s,%s,%s,%s,'initiated',NOW())
            ON CONFLICT(idempotency_key) DO NOTHING RETURNING id
        """, (claim_id, str(claim["rider_id"]), str(claim["policy_id"]), actual_payout, payout_type, idem_key))
        if not cur.fetchone():
            conn.rollback(); return {"status": "idempotency_conflict"}

        conn.commit()

        # Stressed: > ₹1000 requires manual
        if mode == "stressed" and actual_payout > 1000:
            cur.execute("UPDATE payouts SET razorpay_status='pending_manual' WHERE idempotency_key=%s", (idem_key,))
            return {"status": "pending_manual", "amount": actual_payout}

        fund_account_id = policy.get("razorpay_fund_account_id")
        if not fund_account_id:
            return {"status": "queued_no_fund_account", "amount": actual_payout}

        try:
            rz = create_payout(fund_account_id, actual_payout, idem_key)
            # BUG-08 FIX: Wrap ref-update in try/except so a DB failure here
            # doesn't swallow the fact that Razorpay was called successfully.
            try:
                conn2, cur2 = _conn()
                cur2.execute("UPDATE payouts SET razorpay_ref=%s,razorpay_status='processing' WHERE idempotency_key=%s", (rz.get("id"), idem_key))
                cur2.close(); conn2.close()
            except Exception as ref_exc:
                log.error("razorpay_ref_update_failed_payout_was_sent",
                          idem_key=idem_key, razorpay_id=rz.get("id"), error=str(ref_exc))
            log.info("payout_done", claim_id=claim_id, amount=actual_payout, mode=mode)
            from app.services.notification_service import publish_notification
            publish_notification(str(rider["id"]), "payout_success", {"amount": actual_payout, "trigger_type": trigger["trigger_type"]})
            return {"status": "success", "amount": actual_payout, "idem_key": idem_key}
        except CircuitOpenError:
            conn2, cur2 = _conn()
            cur2.execute("UPDATE payouts SET razorpay_status='circuit_breaker_hold' WHERE idempotency_key=%s", (idem_key,))
            cur2.close(); conn2.close()
            redis.zadd("payout_recovery_queue", {idem_key: time.time()})
            return {"status": "circuit_breaker_hold", "amount": actual_payout}
        except Exception as exc:
            conn2, cur2 = _conn()
            cur2.execute("UPDATE payouts SET razorpay_status='failed' WHERE idempotency_key=%s", (idem_key,))
            cur2.close(); conn2.close()
            raise self.retry(exc=exc, countdown=300)

    except Exception as exc:
        if not conn.autocommit:
            try: conn.rollback()
            except: pass
        raise self.retry(exc=exc, countdown=30)
    finally:
        redis.delete(lock_key)
        try: cur.close(); conn.close()
        except: pass


@celery_app.task(name="app.workers.payout_worker.process_provisional_payout")
def process_provisional_payout(claim_id: str, full_amount: float):
    """Soft-flagged: 70% now (or 60% in cautious mode), remainder after 2h."""
    from app.core.idempotency import make_payout_key
    from app.external.razorpay_client import create_payout

    conn, cur = _conn()
    cur.execute("SELECT value FROM system_config WHERE key='liquidity_mode'")
    row = cur.fetchone(); mode = row["value"] if row else "normal"

    # GAP-06: cautious mode → 60/40 split
    prov_pct = 0.60 if mode == "cautious" else 0.70
    hold_hrs = 4 if mode == "cautious" else 2

    prov_amt = round(full_amount * prov_pct, 2)
    rem_amt  = round(full_amount * (1 - prov_pct), 2)

    cur.execute("SELECT * FROM claims WHERE id=%s", (claim_id,))
    claim = cur.fetchone()
    cur.execute("SELECT * FROM policies WHERE id=%s", (str(claim["policy_id"]),))
    policy = cur.fetchone()

    ikey = make_payout_key(claim_id, "provisional", prov_amt)
    cur.execute("""
        INSERT INTO payouts(claim_id,rider_id,policy_id,amount,payout_type,idempotency_key,razorpay_status,released_at)
        VALUES(%s,%s,%s,%s,'provisional',%s,'initiated',NOW())
        ON CONFLICT(idempotency_key) DO NOTHING RETURNING id
    """, (claim_id, str(claim["rider_id"]), str(claim["policy_id"]), prov_amt, ikey))

    faid = policy.get("razorpay_fund_account_id")
    if faid and cur.fetchone():
        try:
            rz = create_payout(faid, prov_amt, ikey)
            cur.execute("UPDATE payouts SET razorpay_ref=%s,razorpay_status='processing' WHERE idempotency_key=%s", (rz.get("id"), ikey))
        except Exception as e:
            log.error("provisional_failed", error=str(e))
    cur.execute("UPDATE policies SET weekly_payout_used=weekly_payout_used+%s WHERE id=%s", (prov_amt, str(policy["id"])))
    cur.close(); conn.close()

    release_remainder_payout.apply_async(args=[claim_id, rem_amt], countdown=hold_hrs * 3600)
    log.info("provisional_sent", claim_id=claim_id, amount=prov_amt, mode=mode, hold_hrs=hold_hrs)


@celery_app.task(name="app.workers.payout_worker.release_remainder_payout")
def release_remainder_payout(claim_id: str, remainder: float):
    from app.core.idempotency import make_payout_key
    from app.external.razorpay_client import create_payout

    conn, cur = _conn()
    cur.execute("SELECT * FROM claims WHERE id=%s", (claim_id,))
    claim = cur.fetchone()
    if not claim or claim["status"] not in ("soft_flagged","auto_cleared"):
        cur.close(); conn.close(); return

    cur.execute("SELECT * FROM policies WHERE id=%s", (str(claim["policy_id"]),))
    policy = cur.fetchone()
    ikey   = make_payout_key(claim_id, "remainder", remainder)
    cur.execute("""
        INSERT INTO payouts(claim_id,rider_id,policy_id,amount,payout_type,idempotency_key,razorpay_status,released_at)
        VALUES(%s,%s,%s,%s,'remainder',%s,'initiated',NOW())
        ON CONFLICT(idempotency_key) DO NOTHING RETURNING id
    """, (claim_id, str(claim["rider_id"]), str(claim["policy_id"]), remainder, ikey))
    faid = policy.get("razorpay_fund_account_id")
    if faid and cur.fetchone():
        try:
            rz = create_payout(faid, remainder, ikey)
            cur.execute("UPDATE payouts SET razorpay_ref=%s,razorpay_status='processing' WHERE idempotency_key=%s", (rz.get("id"), ikey))
            cur.execute("UPDATE policies SET weekly_payout_used=weekly_payout_used+%s WHERE id=%s", (remainder, str(policy["id"])))
            cur.execute("UPDATE claims SET status='paid',paid_at=NOW() WHERE id=%s", (claim_id,))
            cur.execute("UPDATE riders SET annual_payout_total=COALESCE(annual_payout_total,0)+%s WHERE id=%s", (remainder, str(claim["rider_id"])))
        except Exception as e:
            log.error("remainder_failed", error=str(e))
    cur.close(); conn.close()


@celery_app.task(name="app.workers.payout_worker.drain_recovery_queue")
def drain_recovery_queue():
    from app.core.redis_client import get_sync_redis
    from app.external.razorpay_client import create_payout
    from app.external.circuit_breaker import get_circuit_breaker, CBState

    redis = get_sync_redis()
    cb    = get_circuit_breaker("razorpay")
    if cb.get_state() != CBState.CLOSED:
        return

    held = redis.zrangebyscore("payout_recovery_queue", 0, time.time(), start=0, num=50)
    # Spec §19.3: max 50 payouts/min to prevent thundering herd after outage
    _DRAIN_INTERVAL = 60.0 / max(len(held), 1) if held else 0
    for idem_key in held:
        conn, cur = _conn()
        cur.execute("SELECT p.*,po.razorpay_fund_account_id FROM payouts p JOIN policies po ON p.policy_id=po.id WHERE p.idempotency_key=%s AND p.razorpay_status='circuit_breaker_hold'", (idem_key,))
        payout = cur.fetchone()
        if not payout:
            redis.zrem("payout_recovery_queue", idem_key)
            cur.close(); conn.close(); continue
        try:
            rz = create_payout(payout["razorpay_fund_account_id"], float(payout["amount"]), idem_key)
            cur.execute("UPDATE payouts SET razorpay_ref=%s,razorpay_status='processing' WHERE idempotency_key=%s", (rz.get("id"), idem_key))
            redis.zrem("payout_recovery_queue", idem_key)
        except Exception as exc:
            log.error("recovery_failed", error=str(exc))
        finally:
            cur.close(); conn.close()
        if _DRAIN_INTERVAL > 0:
            time.sleep(_DRAIN_INTERVAL)  # rate limit: spec §19.3 max 50/min


@celery_app.task(name="app.workers.payout_worker.retry_dead_letter_payouts")
def retry_dead_letter_payouts():
    """
    Dead Letter Queue: retry claims stuck in auto_cleared with no payout row.
    Runs every hour. Catches claims where payout task silently failed.
    
    A claim is 'stuck' if:
      - status = 'auto_cleared' AND cleared_at > 5 minutes ago
      - No corresponding row in payouts table
    """
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    settings = get_settings()
    conn = psycopg2.connect(settings.database_url)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("""
            SELECT c.id, c.rider_id, c.policy_id, c.trigger_id, c.fraud_score,
                   c.confidence_adjusted_payout, c.cleared_at
            FROM claims c
            WHERE c.status = 'auto_cleared'
              AND c.cleared_at < NOW() - INTERVAL '5 minutes'
              AND NOT EXISTS (
                SELECT 1 FROM payouts p WHERE p.claim_id = c.id
              )
            LIMIT 50
        """)
        stuck = cur.fetchall()
        
        retried = 0
        for claim in stuck:
            try:
                # Re-queue the payout
                process_claim_payout_task.delay(str(claim['id']), 'initial')
                log.warning("dead_letter_payout_requeued", 
                           claim_id=str(claim['id']),
                           cleared_at=str(claim['cleared_at']))
                retried += 1
            except Exception as exc:
                log.error("dead_letter_retry_failed", claim_id=str(claim['id']), error=str(exc))
        
        if retried > 0:
            log.info("dead_letter_drain_complete", retried=retried, total_stuck=len(stuck))
        
    except Exception as exc:
        log.error("dead_letter_scan_failed", error=str(exc))
    finally:
        conn.close()
