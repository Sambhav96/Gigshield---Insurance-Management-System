"""
workers/monday_worker.py — AUDIT FIXED

GAP-03 FIX: Checks beta_freeze_until before incrementing discount_weeks.
            After confirmed hard-flag: resets discount_weeks=0, sets freeze 14 days.
BUG-01 FIX: All timestamps from DB NOW().
"""
from __future__ import annotations
import json, structlog
from app.workers.celery_app import celery_app

log = structlog.get_logger()


def _conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    c = psycopg2.connect(get_settings().database_url)
    c.autocommit = True
    return c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.monday_worker.run_monday_cycle", bind=True, max_retries=1)
def run_monday_cycle(self):
    conn, cur = _conn()
    try:
        # Cron lock: double-run protection
        cur.execute("""
            INSERT INTO cron_locks(job_name,week_start)
            VALUES('monday_cycle', date_trunc('week',NOW())::date)
            ON CONFLICT(job_name,week_start) DO NOTHING RETURNING id
        """)
        if not cur.fetchone():
            log.info("monday_cycle_already_ran"); return

        cur.execute("SELECT date_trunc('week',NOW())::date AS ws")
        week_start = cur.fetchone()["ws"]
        log.info("monday_cycle_started", week_start=str(week_start))

        # Step 2: Reset weekly caps ALL policies
        cur.execute("UPDATE policies SET weekly_payout_used=0, week_start_date=%s WHERE status IN ('active','paused','lapsed')", (week_start,))

        # Step 3-11: Process each active policy
        cur.execute("SELECT id FROM policies WHERE status='active'")
        policy_ids = [str(r["id"]) for r in cur.fetchall()]
        log.info("processing_policies", count=len(policy_ids))

        for pid in policy_ids:
            _process_policy(pid, week_start, cur)

        # Quarterly reset
        cur.execute("SELECT EXTRACT(MONTH FROM NOW()) AS m, EXTRACT(DAY FROM NOW()) AS d")
        r = cur.fetchone()
        if int(r["d"]) == 1 and int(r["m"]) in (1,4,7,10):
            cur.execute("UPDATE policies SET pause_count_qtr=0")
            log.info("quarterly_pause_reset")

        _compute_segment_economics(cur, week_start)
        log.info("monday_cycle_complete", policies=len(policy_ids))

    except Exception as exc:
        log.error("monday_cycle_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300)
    finally:
        cur.close(); conn.close()


def _process_policy(policy_id: str, week_start, cur):
    from app.core.idempotency import make_debit_key
    from app.external.razorpay_client import charge_mandate
    from app.core.exceptions import CircuitOpenError
    from app.services.pricing_service import (
        compute_p_base, compute_lambda, compute_beta, RISK_MULTIPLIERS, P_BASE_MARGIN_DEFAULT
    )
    from app.services.discount_service import PAYOUT_TYPES_THAT_RESET
    from app.services.fraud_service import apply_risk_decay
    from app.utils.mu_table import PLAN_BASE_PREMIUM, get_plan_coverage
    import datetime

    try:
        cur.execute("SELECT * FROM policies WHERE id=%s", (policy_id,))
        policy = cur.fetchone()
        cur.execute("SELECT * FROM riders WHERE id=%s", (str(policy["rider_id"]),))
        rider  = cur.fetchone()
        cur.execute("SELECT * FROM hubs WHERE id=%s", (str(policy["hub_id"]),))
        hub    = cur.fetchone()
        if not rider or not hub:
            return

        rider_id = str(rider["id"])
        prev_week = week_start - datetime.timedelta(days=7)

        # Risk score computation
        new_score, new_profile = _compute_risk_score(cur, rider_id, rider["risk_score"])

        # GAP-03 FIX: Check beta_freeze_until
        cur.execute("SELECT NOW() AS now")
        db_now = cur.fetchone()["now"]
        freeze_until = policy.get("beta_freeze_until")
        is_frozen    = freeze_until and db_now < freeze_until

        # Discount weeks
        cur.execute("""
            SELECT COALESCE(SUM(amount),0) AS total FROM payouts
            WHERE rider_id=%s AND released_at>=%s AND released_at<%s
              AND payout_type=ANY(%s::text[])
        """, (rider_id, prev_week, week_start, list(PAYOUT_TYPES_THAT_RESET)))
        week_total = float(cur.fetchone()["total"] or 0)

        if is_frozen:
            new_dw = 0  # GAP-03: frozen → no discount accumulation
        else:
            new_dw = min(policy["discount_weeks"] + 1, 4) if week_total == 0 else 0

        # Risk score decay
        new_score = apply_risk_decay(new_score, week_total > 0)
        new_profile = "low" if new_score <= 30 else ("high" if new_score > 60 else "medium")

        cur.execute("UPDATE riders SET risk_score=%s, risk_profile=%s WHERE id=%s", (new_score, new_profile, rider_id))
        cur.execute("INSERT INTO rider_risk_scores(rider_id,risk_score,risk_profile,trigger_reason) VALUES(%s,%s,%s,'weekly_monday')", (rider_id, new_score, new_profile))

        # P_final computation
        eff_income = float(rider["effective_income"])
        plan = policy["plan"]
        tier = rider["tier"]
        cov_pct = get_plan_coverage(plan, tier)

        cur.execute("SELECT COUNT(*) AS c FROM policies WHERE hub_id=%s AND status='active'", (str(hub["id"]),))
        active_count = int(cur.fetchone()["c"] or 0)

        cur.execute("SELECT value::float FROM system_config WHERE key='lambda_floor'")
        row = cur.fetchone(); lambda_floor = float(row["value"]) if row else 1.0

        cur.execute("SELECT value::float FROM system_config WHERE key='p_base_margin_pct'")
        row = cur.fetchone(); margin = float(row["value"]) if row else P_BASE_MARGIN_DEFAULT

        # vulnerability_idx from zone_risk_cache
        cur.execute("SELECT vulnerability_idx FROM zone_risk_cache WHERE h3_index=%s", (hub["h3_index_res9"],))
        row = cur.fetchone(); vuln_idx = float(row["vulnerability_idx"]) if row else 0.50

        lambda_val = compute_lambda(active_count, hub["capacity"] or 100, lambda_floor)
        beta       = compute_beta(new_dw) if not is_frozen else 1.0
        risk_mult  = RISK_MULTIPLIERS.get(new_profile, 1.00)

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM trigger_events
            WHERE hub_id=%s AND status='resolved' AND oracle_score>=0.70
              AND triggered_at>=NOW()-INTERVAL '30 days'
        """, (str(hub["id"]),))
        events_30d    = int(cur.fetchone()["cnt"] or 0)
        recent_factor = min(1.0 + events_30d * 0.05, 1.40)

        # Rider 3-of-4 weeks personal multiplier
        cur.execute("""
            SELECT COUNT(DISTINCT date_trunc('week',initiated_at)) AS c
            FROM claims WHERE rider_id=%s AND initiated_at>=NOW()-INTERVAL '28 days'
              AND status NOT IN ('rejected','manual_rejected','cap_exhausted')
        """, (rider_id,))
        weeks_claimed = int(cur.fetchone()["c"] or 0)
        rider_mult    = 1.10 if weeks_claimed >= 3 else 1.00
        recent_factor = min(recent_factor * rider_mult, 1.40)

        p_base  = compute_p_base(eff_income, cov_pct, vuln_idx, margin)
        p_final = round(p_base * float(hub["city_multiplier"]) * lambda_val * beta * risk_mult * recent_factor, 2)
        p_final = max(p_final, PLAN_BASE_PREMIUM.get(plan, 29.0))

        cur.execute("UPDATE policies SET discount_weeks=%s, weekly_premium=%s, coverage_pct=%s WHERE id=%s",
                    (new_dw, p_final, cov_pct, policy_id))

        # Idempotency check
        idem_key = make_debit_key(policy_id, str(week_start))
        cur.execute("SELECT id FROM payouts WHERE idempotency_key=%s LIMIT 1", (idem_key,))
        if cur.fetchone():
            log.info("monday_debit_already_done", policy_id=policy_id); return

        # Razorpay mandate charge
        mandate_id = policy.get("razorpay_mandate_id")
        if not mandate_id:
            log.warning("no_mandate", policy_id=policy_id); return

        try:
            resp = charge_mandate(mandate_id, p_final, idem_key)
            cur.execute("""
                INSERT INTO payouts(rider_id,policy_id,amount,payout_type,razorpay_ref,razorpay_status,idempotency_key,released_at)
                VALUES(%s,%s,%s,'premium_debit',%s,'success',%s,NOW())
                ON CONFLICT(idempotency_key) DO NOTHING
            """, (rider_id, policy_id, p_final, resp.get("id"), idem_key))
            from app.services.notification_service import publish_notification
            publish_notification(rider_id, "policy_renewed", {"premium": p_final, "discount_weeks": new_dw})
            log.info("premium_debited", policy_id=policy_id, amount=p_final)

        except CircuitOpenError:
            log.error("monday_debit_circuit_open", policy_id=policy_id)
        except Exception as exc:
            log.error("monday_debit_failed", policy_id=policy_id, error=str(exc))
            cur.execute("UPDATE policies SET status='lapsed' WHERE id=%s", (policy_id,))
            from app.services.notification_service import publish_notification
            publish_notification(rider_id, "policy_lapsed", {})

    except Exception as exc:
        log.error("process_policy_failed", policy_id=policy_id, error=str(exc))


def _compute_risk_score(cur, rider_id: str, current: int) -> tuple[int, str]:
    cur.execute("SELECT COUNT(*)::float/13 AS cpw FROM claims WHERE rider_id=%s AND initiated_at>=NOW()-INTERVAL '90 days'", (rider_id,))
    cpw = float(cur.fetchone()["cpw"] or 0)
    if cpw > 2.0: freq = 40
    elif cpw > 1.0: freq = 20
    elif cpw > 0.5: freq = 10
    else: freq = 0

    cur.execute("SELECT AVG(fraud_score) AS af FROM claims WHERE rider_id=%s AND initiated_at>=NOW()-INTERVAL '90 days'", (rider_id,))
    af = float(cur.fetchone()["af"] or 0)
    if af > 0.60: fs_pts = 30
    elif af > 0.40: fs_pts = 15
    elif af > 0.25: fs_pts = 5
    else: fs_pts = 0

    cur.execute("SELECT COUNT(*) AS c FROM claims WHERE rider_id=%s AND status='hard_flagged' AND initiated_at>=NOW()-INTERVAL '90 days'", (rider_id,))
    flags = int(cur.fetchone()["c"] or 0)
    flag_pts = 20 if flags >= 2 else (10 if flags == 1 else 0)

    cur.execute("SELECT COUNT(*) AS c FROM claim_evidence WHERE rider_id=%s AND created_at>=NOW()-INTERVAL '90 days'", (rider_id,))
    vov_cnt = int(cur.fetchone()["c"] or 0)
    vov_pts = -10 if vov_cnt >= 3 else 0

    score   = max(0, min(100, freq + fs_pts + flag_pts + vov_pts))
    profile = "low" if score <= 30 else ("high" if score > 60 else "medium")
    return score, profile


def _compute_segment_economics(cur, week_start):
    try:
        cur.execute("""
            INSERT INTO segment_economics(city,plan,tier,risk_profile,week_start,
                active_policies,premiums_collected,payouts_issued,loss_ratio,gross_margin)
            SELECT h.city, p.plan, r.tier, r.risk_profile, %s::date,
                COUNT(DISTINCT p.id),
                SUM(p.weekly_premium),
                COALESCE(SUM(py.amount) FILTER(WHERE py.payout_type!='premium_debit'),0),
                COALESCE(SUM(py.amount) FILTER(WHERE py.payout_type!='premium_debit'),0)/NULLIF(SUM(p.weekly_premium),0),
                SUM(p.weekly_premium)-COALESCE(SUM(py.amount) FILTER(WHERE py.payout_type!='premium_debit'),0)
            FROM policies p
            JOIN riders r ON p.rider_id=r.id
            JOIN hubs h ON p.hub_id=h.id
            LEFT JOIN payouts py ON py.policy_id=p.id
                AND py.released_at>=%s-INTERVAL '7 days' AND py.released_at<%s
            WHERE p.week_start_date=%s-INTERVAL '7 days'
            GROUP BY h.city,p.plan,r.tier,r.risk_profile
            ON CONFLICT DO NOTHING
        """, (week_start, week_start, week_start, week_start))
    except Exception as exc:
        log.error("segment_economics_failed", error=str(exc))


@celery_app.task(name="app.workers.monday_worker.apply_risk_decay_all")
def apply_risk_decay_all():
    """Called Monday 00:05 IST — apply reputation decay to all riders."""
    from app.services.fraud_service import apply_risk_decay
    import datetime
    conn, cur = _conn()
    try:
        cur.execute("SELECT id, risk_score FROM riders")
        riders = cur.fetchall()
        cur.execute("""
            SELECT date_trunc('week',NOW())::date AS tw,
                   (date_trunc('week',NOW())-INTERVAL '7 days')::date AS pw
        """)
        row = cur.fetchone()
        tw, pw = row["tw"], row["pw"]
        updated = 0
        for r in riders:
            rid = str(r["id"])
            cur.execute("""
                SELECT COALESCE(SUM(amount),0) AS t FROM payouts
                WHERE rider_id=%s AND released_at>=%s AND released_at<%s AND payout_type!='premium_debit'
            """, (rid, pw, tw))
            had_payouts = float(cur.fetchone()["t"] or 0) > 0
            new_score   = apply_risk_decay(int(r["risk_score"]), had_payouts)
            new_profile = "low" if new_score <= 30 else ("high" if new_score > 60 else "medium")
            if new_score != int(r["risk_score"]):
                cur.execute("UPDATE riders SET risk_score=%s,risk_profile=%s WHERE id=%s", (new_score,new_profile,rid))
                cur.execute("INSERT INTO rider_risk_scores(rider_id,risk_score,risk_profile,delta,trigger_reason) VALUES(%s,%s,%s,%s,'weekly_decay')",
                            (rid,new_score,new_profile,new_score-int(r["risk_score"])))
                updated += 1
        log.info("risk_decay_applied", updated=updated)
    finally:
        cur.close(); conn.close()
