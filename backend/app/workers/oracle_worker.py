"""workers/oracle_worker.py — Oracle cycle + platform health + trigger evaluation."""
from __future__ import annotations

import json
import structlog

from app.workers.celery_app import celery_app
from app.external.platform_adapter import check_platform_health

log = structlog.get_logger()


def _conn():
    import psycopg2, psycopg2.extras
    from app.config import get_settings
    c = psycopg2.connect(get_settings().database_url)
    c.autocommit = True
    return c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


@celery_app.task(name="app.workers.oracle_worker.run_oracle_cycle", bind=True, max_retries=2)
def run_oracle_cycle(self):
    """Every 15 min: fetch signals for all active hubs and evaluate triggers."""
    from app.services.oracle_service import (
        compute_oracle_score, compute_correlation_factor,
        compute_cooldown_factor, get_oracle_threshold,
    )
    from app.utils.mu_table import PLAN_TRIGGERS

    conn, cur = _conn()
    try:
        cur.execute("SELECT * FROM hubs")
        hubs = cur.fetchall()

        for hub in hubs:
            h3     = hub["h3_index_res9"]
            lat, lng = float(hub["latitude"]), float(hub["longitude"])

            # Which trigger types to check (based on active plans in hub)
            cur.execute("SELECT DISTINCT plan FROM policies WHERE hub_id=%s AND status='active'", (str(hub["id"]),))
            plans   = [r["plan"] for r in cur.fetchall()]
            ttypes  = set()
            for p in plans:
                ttypes.update(PLAN_TRIGGERS.get(p, []))
            if not ttypes:
                continue

            # Cold-start check for threshold
            cur.execute("SELECT COUNT(*) AS cnt FROM trigger_events WHERE h3_index=%s AND status='resolved'", (h3,))
            cold_start = int(cur.fetchone()["cnt"] or 0) < 20

            for ttype in ttypes:
                try:
                    threshold = get_oracle_threshold(cur, "control", cold_start)
                    result    = compute_oracle_score(
                        ttype, lat, lng, h3,
                        hub_threshold_mm=float(hub.get("rain_threshold_mm", 35.0)),
                    )
                    score = result["oracle_score"]

                    # Store snapshot for backtesting
                    cur.execute(
                        "INSERT INTO oracle_api_snapshots(h3_index,trigger_type,api_source,raw_value,signal_score) VALUES(%s,%s,%s,%s,%s)",
                        (h3, ttype, "oracle_engine", score, score),
                    )

                    if score < threshold:
                        continue

                    # Duplicate check
                    cur.execute(
                        "SELECT id FROM trigger_events WHERE h3_index=%s AND trigger_type=%s AND triggered_at>=NOW()-INTERVAL '15 minutes' AND status!='cancelled' LIMIT 1",
                        (h3, ttype),
                    )
                    if cur.fetchone():
                        continue

                    in_cd, cd_factor = compute_cooldown_factor(cur, h3, ttype)
                    C, corr_factor   = compute_correlation_factor(cur, hub["city"], ttype)

                    cur.execute(
                        """INSERT INTO trigger_events(
                             trigger_type,h3_index,hub_id,oracle_score,
                             weather_score,traffic_score,satellite_score,
                             weight_config,raw_api_data,status,
                             cold_start_mode,cooldown_active,cooldown_payout_factor,correlation_factor
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,'active',%s,%s,%s,%s) RETURNING id""",
                        (ttype, h3, str(hub["id"]), score,
                         result["signal_scores"].get("weather"),
                         result["signal_scores"].get("traffic"),
                         result["signal_scores"].get("satellite"),
                         json.dumps(result.get("weight_config", {})),
                         json.dumps({}),
                         cold_start, in_cd, cd_factor, corr_factor),
                    )
                    tid = str(cur.fetchone()["id"])
                    log.info("trigger_fired", type=ttype, h3=h3, score=score, tid=tid)
                    initiate_claims_for_hex.delay(h3, tid, ttype)

                except Exception as exc:
                    log.error("oracle_hub_error", hub=str(hub["id"]), ttype=ttype, error=str(exc))

        log.info("oracle_cycle_complete", hubs=len(hubs))
    except Exception as exc:
        log.error("oracle_cycle_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=60)
    finally:
        cur.close(); conn.close()


@celery_app.task(name="app.workers.oracle_worker.check_all_platform_health")
def check_all_platform_health():
    """Every 5 min: CODE-05 FIX — pass actual platform_down_score into oracle."""
    from app.services.oracle_service import compute_correlation_factor, compute_cooldown_factor, get_oracle_threshold

    for platform in ["zepto", "blinkit", "instamart"]:
        try:
            result = check_platform_health(platform)
            score  = result["platform_down_score"]
            if score < 0.65:
                continue

            conn, cur = _conn()
            try:
                cur.execute("SELECT id, h3_index_res9, latitude, longitude, city FROM hubs WHERE platform=%s", (platform,))
                hubs = cur.fetchall()
                for hub in hubs:
                    h3 = hub["h3_index_res9"]
                    # Dedup check
                    cur.execute(
                        "SELECT id FROM trigger_events WHERE h3_index=%s AND trigger_type='platform_down' AND triggered_at>=NOW()-INTERVAL '15 minutes' AND status!='cancelled' LIMIT 1",
                        (h3,),
                    )
                    if cur.fetchone():
                        continue

                    in_cd, cd_factor = compute_cooldown_factor(cur, h3, "platform_down")
                    C, corr_factor   = 1.0, 0.70  # platform_down always C=1.0

                    # CODE-05 FIX: pass platform_down_score directly as oracle score
                    cur.execute(
                        """INSERT INTO trigger_events(
                             trigger_type,h3_index,hub_id,oracle_score,
                             weather_score,weight_config,raw_api_data,status,
                             cold_start_mode,cooldown_active,cooldown_payout_factor,correlation_factor
                           ) VALUES('platform_down',%s,%s,%s,%s,%s::jsonb,%s::jsonb,'active',false,%s,%s,%s) RETURNING id""",
                        (h3, str(hub["id"]), score, score,
                         json.dumps({"weather": 1.0}), json.dumps({}),
                         in_cd, cd_factor, corr_factor),
                    )
                    tid = str(cur.fetchone()["id"])
                    initiate_claims_for_hex.delay(h3, tid, "platform_down")
                    log.info("platform_down_triggered", platform=platform, h3=h3, score=score)
            finally:
                cur.close(); conn.close()
        except Exception as exc:
            log.error("platform_health_check_failed", platform=platform, error=str(exc))


@celery_app.task(name="app.workers.payout_worker.initiate_claims_for_hex", bind=True, max_retries=3)
def initiate_claims_for_hex(self, h3_index: str, trigger_id: str, trigger_type: str):
    """For every eligible active policy in hex: run fraud check → create claim → queue payout."""
    from app.services.fraud_service import (
        check_intent, check_presence, compute_fraud_score, classify_fraud, get_fraud_thresholds
    )
    from app.utils.mu_table import get_mu, get_min_duration, PLAN_TRIGGERS, get_confidence_factor, get_correlation_payout_factor
    from app.core.idempotency import make_claim_key, make_payout_key
    from app.workers.payout_worker import process_claim_payout_task

    conn, cur = _conn()
    try:
        cur.execute("SELECT * FROM trigger_events WHERE id=%s", (trigger_id,))
        trigger = cur.fetchone()
        if not trigger:
            return

        # BUG-01 FIX: IST hour from trigger.triggered_at
        cur.execute("SELECT EXTRACT(HOUR FROM %s AT TIME ZONE 'Asia/Kolkata')::int AS h", (trigger["triggered_at"],))
        ist_hour = cur.fetchone()["h"]
        mu_time  = get_mu(ist_hour)

        # Fetch active policies in this hex covered for this trigger type
        cur.execute("""
            SELECT p.*, r.effective_income, r.risk_profile, r.platform,
                   r.phone, r.name AS rider_name, r.id AS rider_uuid,
                   h.latitude AS hub_lat, h.longitude AS hub_lng,
                   h.radius_km, h.h3_index_res9 AS hub_h3
            FROM policies p
            JOIN riders r ON p.rider_id=r.id
            JOIN hubs h ON p.hub_id=h.id
            WHERE h.h3_index_res9=%s AND p.status='active'
              AND %s=ANY(CASE p.plan
                WHEN 'basic'    THEN ARRAY['rain','bandh','platform_down']
                WHEN 'standard' THEN ARRAY['rain','bandh','platform_down','flood','aqi']
                WHEN 'pro'      THEN ARRAY['rain','bandh','platform_down','flood','aqi','heat']
              END)
        """, (h3_index, trigger_type))
        policies = cur.fetchall()

        log.info("claims_initiating", hex=h3_index, trigger=trigger_id, policies=len(policies))

        for pol in policies:
            try:
                rider_id  = str(pol["rider_uuid"])
                policy_id = str(pol["id"])
                idem_key  = make_claim_key(rider_id, trigger_id, policy_id)

                # Idempotency check
                cur.execute("SELECT id FROM claims WHERE idempotency_key=%s LIMIT 1", (idem_key,))
                if cur.fetchone():
                    continue

                eff_income   = float(pol["effective_income"])
                cov_pct      = float(pol["coverage_pct"])
                oracle_score = float(trigger["oracle_score"] or 0.65)

                # Fraud evaluation
                cur.execute("""
                    SELECT latitude,longitude,speed_kmh,recorded_at,session_active,platform_status,h3_index_res9
                    FROM telemetry_pings
                    WHERE rider_id=%s AND recorded_at BETWEEN %s-INTERVAL '60 minutes' AND %s
                    ORDER BY recorded_at ASC
                """, (rider_id, trigger["triggered_at"], trigger["triggered_at"]))
                pings = [dict(p) for p in cur.fetchall()]

                intent_passed, factors = check_intent(pings, trigger["triggered_at"], rider_id, pol["platform"])
                if not intent_passed:
                    fraud_score = 1.0; disposition = "hard_flagged"; presence_conf = 0.0
                else:
                    presence_conf, vel_flag = check_presence(
                        pings, float(pol["hub_lat"]), float(pol["hub_lng"]),
                        float(pol["radius_km"]), pol["hub_h3"],
                    )
                    if vel_flag or presence_conf < 0.67:
                        fraud_score = 1.0; disposition = "hard_flagged"
                    else:
                        fraud_score = compute_fraud_score(oracle_score, presence_conf)
                        ac_thr, hf_thr = get_fraud_thresholds(cur, pol.get("experiment_group_id","control"), pol["risk_profile"])
                        disposition    = classify_fraud(fraud_score, pol["risk_profile"], ac_thr, hf_thr)

                conf_factor = get_confidence_factor(oracle_score)
                corr_factor = float(trigger["correlation_factor"] or 1.0)
                cool_factor = float(trigger["cooldown_payout_factor"] or 1.0)
                dur_hrs     = get_min_duration(trigger_type)
                event_payout = eff_income * cov_pct * (dur_hrs / 8) * mu_time
                final_payout = event_payout * conf_factor * corr_factor * cool_factor

                admin_trace = {
                    "oracle_score": oracle_score, "fraud_score": fraud_score,
                    "intent_factors": factors, "presence_confidence": presence_conf,
                    "coverage_pct": cov_pct, "mu_time": mu_time,
                    "duration_hrs": dur_hrs, "confidence_factor": conf_factor,
                    "correlation_factor": corr_factor, "cooldown_factor": cool_factor,
                    "ist_hour_trigger": ist_hour,
                }

                cur.execute("""
                    INSERT INTO claims(
                        rider_id,policy_id,trigger_id,idempotency_key,
                        status,oracle_confidence,presence_confidence,
                        intent_factor1_gps,intent_factor2_session,intent_factor3_platform,
                        intent_platform_unavailable,fraud_score,
                        event_payout,actual_payout,duration_hrs,mu_time,
                        explanation_text,admin_trace
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (idempotency_key) DO NOTHING RETURNING id
                """, (rider_id, policy_id, trigger_id, idem_key,
                      "evaluating", oracle_score, presence_conf,
                      factors.get("f1_gps",False), factors.get("f2_session",False), factors.get("f3_platform",False),
                      factors.get("f3_platform_unavailable",False), fraud_score,
                      event_payout, final_payout, dur_hrs, mu_time,
                      _explanation(trigger_type, oracle_score, eff_income, cov_pct, mu_time, dur_hrs),
                      json.dumps(admin_trace)))
                row = cur.fetchone()
                if not row:
                    continue
                claim_id = str(row["id"])

                if disposition == "auto_cleared":
                    cur.execute("UPDATE claims SET status='auto_cleared' WHERE id=%s", (claim_id,))
                    process_claim_payout_task.delay(claim_id, "initial")
                elif disposition == "soft_flagged":
                    cur.execute("UPDATE claims SET status='soft_flagged' WHERE id=%s", (claim_id,))
                    from app.workers.payout_worker import process_provisional_payout
                    process_provisional_payout.delay(claim_id, final_payout)
                else:
                    cur.execute("UPDATE claims SET status='hard_flagged' WHERE id=%s", (claim_id,))
                    from app.services.notification_service import publish_notification
                    publish_notification(rider_id, "claim_hard_flagged", {})

            except Exception as exc:
                log.error("claim_init_failed", policy_id=str(pol.get("id","?")), error=str(exc))

    except Exception as exc:
        log.error("initiate_claims_failed", error=str(exc))
        raise self.retry(exc=exc, countdown=30)
    finally:
        cur.close(); conn.close()


def _explanation(tt, oracle, income, cov, mu, dur):
    lbl = {"rain":"heavy rainfall","flood":"flooding","heat":"extreme heat",
           "aqi":"poor air quality","bandh":"civic strike","platform_down":"app outage"}.get(tt, tt)
    pay = income * cov * (dur / 8) * mu
    return (f"A {lbl} event was detected in your zone (confidence: {oracle:.0%}). "
            f"Estimated payout: ₹{pay:.0f} based on ₹{income:.0f}/day income, "
            f"{cov:.0%} coverage, {dur:.1f}h duration, {mu:.1f}× time multiplier.")


@celery_app.task(name="app.workers.oracle_worker.apply_stacking_rule")
def apply_stacking_rule(h3_index: str, rider_id: str, policy_id: str):
    from app.services.oracle_service import resolve_stacking
    from app.utils.mu_table import get_min_duration, get_mu, PLAN_TRIGGERS
    conn, cur = _conn()
    try:
        cur.execute("SELECT * FROM trigger_events WHERE h3_index=%s AND status IN ('active','resolving')", (h3_index,))
        triggers = [dict(t) for t in cur.fetchall()]
        if len(triggers) <= 1:
            return
        cur.execute("SELECT * FROM policies WHERE id=%s", (policy_id,))
        pol = cur.fetchone()
        cur.execute("SELECT * FROM riders WHERE id=%s", (rider_id,))
        rider = cur.fetchone()
        if not pol or not rider:
            return
        cur.execute("SELECT EXTRACT(HOUR FROM NOW() AT TIME ZONE 'Asia/Kolkata')::int AS h")
        ist_hour = cur.fetchone()["h"]
        mu = get_mu(ist_hour)
        covered = PLAN_TRIGGERS.get(pol["plan"], [])
        for t in triggers:
            if t["trigger_type"] in covered:
                t["event_payout_estimate"] = float(rider["effective_income"]) * float(pol["coverage_pct"]) * (get_min_duration(t["trigger_type"])/8) * mu
            else:
                t["event_payout_estimate"] = 0
        covered_t = [t for t in triggers if t["event_payout_estimate"] > 0]
        if not covered_t:
            return
        winner, suppressed = resolve_stacking(covered_t)
        log.info("stacking_applied", h3=h3_index, winner=winner["trigger_type"],
                 suppressed=[s["trigger_type"] for s in suppressed])
    except Exception as exc:
        log.error("stacking_failed", error=str(exc))
    finally:
        cur.close(); conn.close()
