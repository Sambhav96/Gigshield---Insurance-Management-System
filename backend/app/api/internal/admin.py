"""api/internal/admin.py — All 7 admin tabs with backtesting wired (GAP-17)."""
from __future__ import annotations

import json
import uuid
from datetime import date as _date
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_db, get_current_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Tab 1: Dashboard ──────────────────────────────────────────────────────────
@router.get("/dashboard")
async def admin_dashboard(admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    from app.external.circuit_breaker import get_circuit_breaker

    active_policies = await conn.fetchval("SELECT COUNT(*) FROM policies WHERE status='active'")
    payouts_today   = await conn.fetchrow("SELECT COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total FROM payouts WHERE released_at>=NOW()-INTERVAL '24 hours' AND payout_type!='premium_debit'")
    pending_claims  = await conn.fetchval("SELECT COUNT(*) FROM claims WHERE status IN ('evaluating','soft_flagged','hard_flagged','manual_review')")
    active_triggers = await conn.fetchval("SELECT COUNT(*) FROM trigger_events WHERE status IN ('active','resolving')")

    lr = await conn.fetchrow("SELECT COALESCE(SUM(p.amount) FILTER(WHERE p.payout_type!='premium_debit'),0) AS pay, COALESCE(SUM(p.amount) FILTER(WHERE p.payout_type='premium_debit'),0) AS prem FROM payouts p WHERE p.released_at>=NOW()-INTERVAL '7 days'")
    loss_ratio = float(lr["pay"]) / float(lr["prem"]) if float(lr["prem"]) > 0 else 0

    try:
        liquidity = await conn.fetchrow("SELECT * FROM liquidity_snapshots ORDER BY snapshot_at DESC LIMIT 1")
    except Exception:
        liquidity = None
    try:
        kill_switch = await conn.fetchval("SELECT value FROM system_config WHERE key='global_kill_switch'")
    except Exception:
        kill_switch = 'off' 

    cb_states = {}
    for svc in ["razorpay","owm","waqi","here","platform_zepto","platform_blinkit","earth_engine","weatherstack"]:
        cb = get_circuit_breaker(svc)
        cb_states[svc] = cb.get_state().value

    # API budget status
    try:
        from app.core.api_budget import get_budget_status
        from app.core.redis_client import get_sync_redis
        budget_status = get_budget_status(get_sync_redis())
    except Exception:
        budget_status = {}
    
    # ML model status  
    try:
        from app.ml.vulnerability_model import get_model_metrics
        ml_metrics = get_model_metrics()
    except Exception:
        ml_metrics = {}

    return {
        "kpis": {
            "active_policies": int(active_policies or 0),
            "payouts_today_count": int(payouts_today["cnt"] or 0),
            "payouts_today_inr": float(payouts_today["total"] or 0),
            "pending_claims": int(pending_claims or 0),
            "active_triggers": int(active_triggers or 0),
            "loss_ratio_7d": round(loss_ratio, 4),
        },
        "liquidity": dict(liquidity) if liquidity else {},
        "circuit_breakers": cb_states,
        "kill_switch": kill_switch or "off",
        "api_budget": budget_status,
        "ml_model": ml_metrics,
    }


@router.post("/dashboard/kill-switch")
async def set_kill_switch(body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    if body.get("confirm") != "CONFIRM":
        raise HTTPException(status_code=400, detail="Type CONFIRM to proceed")
    val = body.get("value","off")
    if val not in ("off","triggers_only","payouts_only","full"):
        raise HTTPException(status_code=400, detail="Invalid value")
    await conn.execute("UPDATE system_config SET value=$1 WHERE key='global_kill_switch'", val)
    await conn.execute(
        "INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) VALUES($1,'kill_switch','system','global',$2::jsonb,NOW())",
        admin["id"], json.dumps({"value": val, "reason": body.get("reason","")})
    )
    return {"status": "updated", "kill_switch": val}


@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    total = await conn.fetchval("SELECT COUNT(*) FROM admin_audit_log")
    rows = await conn.fetch(
        """
        SELECT id, action AS action_type, action, entity_type, entity_id, performed_at, diff
        FROM admin_audit_log
        ORDER BY performed_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return {"logs": [dict(r) for r in rows], "total": int(total or 0)}


@router.get("/claims")
async def get_claims_database(
    page: int = Query(1, ge=1),
    status: str = Query("all"),
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    page_size = 20
    offset = (page - 1) * page_size

    # FIX #6: Replace fragile dynamic ${len(params)-1} indexing with explicit,
    # readable SQL queries. Each branch has unambiguous $1/$2/$3 placeholders.
    BASE_SELECT = """
        SELECT
            c.id,
            c.rider_id,
            r.phone,
            r.name AS rider_name,
            c.status,
            c.initiated_at,
            c.trigger_id,
            c.event_payout,
            c.actual_payout,
            c.fraud_score,
            c.admin_action,
            te.trigger_type,
            COALESCE(SUM(p.amount), 0)::float AS payout_amount
        FROM claims c
        JOIN riders r ON c.rider_id = r.id
        JOIN trigger_events te ON c.trigger_id = te.id
        LEFT JOIN payouts p ON p.claim_id = c.id AND p.payout_type != 'premium_debit'
    """

    if status == "all":
        total = await conn.fetchval("SELECT COUNT(*) FROM claims")
        rows = await conn.fetch(
            BASE_SELECT + """
            GROUP BY c.id, r.phone, r.name, te.trigger_type
            ORDER BY c.initiated_at DESC
            LIMIT $1 OFFSET $2
            """,
            page_size, offset,
        )
    else:
        total = await conn.fetchval("SELECT COUNT(*) FROM claims WHERE status = $1", status)
        rows = await conn.fetch(
            BASE_SELECT + """
            WHERE c.status = $1
            GROUP BY c.id, r.phone, r.name, te.trigger_type
            ORDER BY c.initiated_at DESC
            LIMIT $2 OFFSET $3
            """,
            status, page_size, offset,
        )

    pages = int((int(total or 0) + page_size - 1) / page_size) if page_size else 1
    return {
        "claims": [dict(r) for r in rows],
        "items": [dict(r) for r in rows],
        "total": int(total or 0),
        "page": page,
        "pages": pages,
    }


@router.get("/actuarial/parameters")
async def get_actuarial_parameters(
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    keys = [
        "oracle_threshold",
        "auto_clear_fs_threshold",
        "hard_flag_fs_threshold",
        "single_event_cap_pct",
        "lambda_floor",
        "risk_profile_high_mult",
        "vov_reward_individual",
        "discount_per_clean_week",
        "max_discount_weeks",
        "confidence_band_1_factor",
        "confidence_band_2_factor",
        "daily_soft_limit_divisor",
        "vov_reward_zone_cert",
        "p_base_margin_pct",
    ]
    try:
        rows = await conn.fetch("SELECT key, value FROM system_config WHERE key = ANY($1::text[])", keys)
        values = {r["key"]: r["value"] for r in rows}
    except Exception:
        values = {}
    # Return defaults if config not seeded yet
    PARAM_DEFAULTS = {
        "oracle_threshold": 0.65, "auto_clear_fs_threshold": 0.40,
        "hard_flag_fs_threshold": 0.80, "single_event_cap_pct": 0.50,
        "lambda_floor": 1.4, "risk_profile_high_mult": 1.25,
        "vov_reward_individual": 10.0, "discount_per_clean_week": 1,
        "max_discount_weeks": 4, "confidence_band_1_factor": 0.70,
        "confidence_band_2_factor": 0.90, "daily_soft_limit_divisor": 4.0,
        "vov_reward_zone_cert": 20.0, "p_base_margin_pct": 0.85,
    }
    return {k: float(values.get(k, PARAM_DEFAULTS.get(k, 0))) for k in keys}


@router.put("/actuarial/parameters")
async def update_actuarial_parameters(
    body: dict,
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    allowed = {
        "oracle_threshold",
        "auto_clear_fs_threshold",
        "hard_flag_fs_threshold",
        "single_event_cap_pct",
        "lambda_floor",
        "risk_profile_high_mult",
        "vov_reward_individual",
        "discount_per_clean_week",
        "max_discount_weeks",
        "confidence_band_1_factor",
        "confidence_band_2_factor",
        "daily_soft_limit_divisor",
        "vov_reward_zone_cert",
        "p_base_margin_pct",
    }

    updated: dict[str, float] = {}
    for key, value in body.items():
        if key not in allowed:
            continue
        try:
            val = float(value)
        except Exception:
            continue
        await conn.execute(
            """
            INSERT INTO system_config(key, value, updated_at)
            VALUES($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            key,
            str(val),
        )
        updated[key] = val

    await conn.execute(
        "INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) VALUES($1,'actuarial_parameters_update','system','actuarial',$2::jsonb,NOW())",
        admin["id"],
        json.dumps(updated),
    )
    return {"status": "updated", "parameters": updated}


# ── Tab 2: Fraud Queue ────────────────────────────────────────────────────────
@router.get("/fraud-queue")
async def get_fraud_queue(limit: int = Query(50, le=200), admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("""
        SELECT c.*, r.phone AS rider_phone, r.name AS rider_name, r.risk_profile,
               te.trigger_type, te.triggered_at, te.oracle_score AS trigger_oracle_score
        FROM claims c JOIN riders r ON c.rider_id=r.id JOIN trigger_events te ON c.trigger_id=te.id
        WHERE c.status IN ('hard_flagged','manual_review')
        ORDER BY c.fraud_score DESC LIMIT $1
    """, limit)
    return {"claims": [dict(r) for r in rows], "total": len(rows)}


@router.post("/fraud-queue/{claim_id}/action")
async def fraud_action(claim_id: uuid.UUID, body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    action = body.get("action")
    if action not in ("approve","approve_partial","reject","escalate","request_info"):
        raise HTTPException(status_code=400, detail="Invalid action")

    claim = await conn.fetchrow("SELECT * FROM claims WHERE id=$1", claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if action == "approve":
        await conn.execute("UPDATE claims SET status='manual_approved',admin_id=$1,admin_action='approve',admin_action_at=NOW() WHERE id=$2", admin["id"], claim_id)
        from app.workers.payout_worker import process_claim_payout_task
        process_claim_payout_task.delay(str(claim_id), "initial")

    elif action == "approve_partial":
        amt = body.get("amount")
        if not amt: raise HTTPException(status_code=400, detail="amount required")
        await conn.execute("UPDATE claims SET status='manual_adjusted',admin_id=$1,admin_custom_amount=$2,admin_action='approve_partial',admin_action_at=NOW() WHERE id=$3", admin["id"], amt, claim_id)
        from app.workers.payout_worker import process_claim_payout_task
        process_claim_payout_task.delay(str(claim_id), "initial")

    elif action == "reject":
        await conn.execute("UPDATE claims SET status='manual_rejected',admin_id=$1,admin_note=$2,admin_action='reject',admin_action_at=NOW() WHERE id=$3", admin["id"], body.get("reason",""), claim_id)

    elif action == "escalate":
        await conn.execute("UPDATE claims SET status='manual_review',admin_id=$1,admin_action='escalate',admin_action_at=NOW() WHERE id=$2", admin["id"], claim_id)
        if body.get("fraud_confirmed"):
            await conn.execute("UPDATE riders SET risk_score=100,risk_profile='high' WHERE id=$1", claim["rider_id"])
            # GAP-03: Apply beta freeze on confirmed fraud
            from app.services.discount_service import apply_fraud_freeze
            pol = await conn.fetchrow("SELECT id FROM policies WHERE rider_id=$1 AND status='active' LIMIT 1", claim["rider_id"])
            if pol:
                await apply_fraud_freeze(conn, str(pol["id"]), str(claim["rider_id"]))

    elif action == "request_info":
        await conn.execute("INSERT INTO support_messages(rider_id,claim_id,direction,message) VALUES($1,$2,'admin_to_rider',$3)", claim["rider_id"], claim_id, body.get("message","Please provide additional information."))

    await conn.execute("INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) VALUES($1,$2,'claim',$3,$4::jsonb,NOW())", admin["id"], action, str(claim_id), json.dumps(body))
    return {"status": "applied", "action": action}


# ── Tab 3: Rider Support ──────────────────────────────────────────────────────
@router.get("/riders/search")
async def search_rider(phone: str = Query(None), rider_id: str = Query(None), admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    if phone:
        rider = await conn.fetchrow("SELECT * FROM riders WHERE phone LIKE $1", f"%{phone}%")
    elif rider_id:
        rider = await conn.fetchrow("SELECT * FROM riders WHERE id=$1", uuid.UUID(rider_id))
    else:
        raise HTTPException(status_code=400, detail="Provide phone or rider_id")
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    rid = rider["id"]
    # DPDP Act: log admin PII access
    await conn.execute("INSERT INTO data_access_log(admin_id,rider_id,action,fields_accessed) VALUES($1,$2,'view_profile',ARRAY['phone','income','risk_score'])", admin["id"], rid)

    policy  = await conn.fetchrow("SELECT * FROM policies WHERE rider_id=$1 AND status='active'", rid)
    claims  = await conn.fetch("SELECT * FROM claims WHERE rider_id=$1 ORDER BY initiated_at DESC LIMIT 20", rid)
    payouts = await conn.fetch("SELECT * FROM payouts WHERE rider_id=$1 ORDER BY released_at DESC LIMIT 20", rid)
    disputes = await conn.fetch("SELECT * FROM disputes WHERE rider_id=$1 ORDER BY created_at DESC", rid)

    return {"rider": dict(rider), "policy": dict(policy) if policy else None,
            "claims": [dict(c) for c in claims], "payouts": [dict(p) for p in payouts],
            "disputes": [dict(d) for d in disputes]}


@router.post("/riders/{rider_id}/override")
async def rider_override(rider_id: uuid.UUID, body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    action = body.get("action")
    reason = body.get("reason","admin_override")

    if action == "adjust_income":
        inc  = float(body["effective_income"])
        tier = "A" if inc > 700 else "B"
        await conn.execute("UPDATE riders SET effective_income=$1,tier=$2 WHERE id=$3", inc, tier, rider_id)
    elif action == "override_risk_profile":
        p = body.get("risk_profile")
        if p not in ("low","medium","high"): raise HTTPException(status_code=400, detail="Invalid profile")
        await conn.execute("UPDATE riders SET risk_profile=$1 WHERE id=$2", p, rider_id)
    elif action == "reset_discount_weeks":
        pol = await conn.fetchrow("SELECT id FROM policies WHERE rider_id=$1 AND status='active'", rider_id)
        if pol:
            await conn.execute("UPDATE policies SET discount_weeks=0 WHERE id=$1", pol["id"])
    elif action == "goodwill_credit":
        amt = float(body["amount"])
        pol = await conn.fetchrow("SELECT * FROM policies WHERE rider_id=$1 AND status='active'", rider_id)
        if not pol: raise HTTPException(status_code=400, detail="No active policy")
        from app.core.idempotency import make_payout_key
        ikey = make_payout_key(str(rider_id)+reason, "goodwill", amt)
        await conn.execute("""
            INSERT INTO payouts(rider_id,policy_id,amount,payout_type,idempotency_key,razorpay_status,released_at)
            VALUES($1,$2,$3,'goodwill',$4,'initiated',NOW()) ON CONFLICT(idempotency_key) DO NOTHING
        """, rider_id, pol["id"], amt, ikey)
        await conn.execute("UPDATE policies SET discount_weeks=0,weekly_payout_used=weekly_payout_used+$1 WHERE id=$2", amt, pol["id"])
        await conn.execute("UPDATE riders SET annual_payout_total=COALESCE(annual_payout_total,0)+$1 WHERE id=$2", amt, rider_id)
    elif action == "send_message":
        await conn.execute("INSERT INTO support_messages(rider_id,direction,message) VALUES($1,'admin_to_rider',$2)", rider_id, body.get("message",""))

    await conn.execute("INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) VALUES($1,$2,'rider',$3,$4::jsonb,NOW())", admin["id"], action, str(rider_id), json.dumps(body))
    return {"status": "applied", "action": action}


# ── Tab 4: Backtesting — GAP-17 FIX ──────────────────────────────────────────
@router.post("/backtesting/run")
async def run_backtest(body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    """Run historical backtest. Wired to improved backtest_service."""
    from app.services.backtest_service import run_historical_backtest
    result = await run_historical_backtest(
        conn,
        city=body.get("city", "Mumbai"),
        start_date=body.get("start_date", "2024-06-01"),
        end_date=body.get("end_date", "2024-09-01"),
        plan=body.get("plan", "standard"),
        n_synthetic_riders=int(body.get("n_synthetic_riders", 100)),
    )
    return result


@router.get("/backtesting/status/{task_id}")
async def backtest_status(task_id: str, admin: dict = Depends(get_current_admin)):
    from celery.result import AsyncResult
    from app.workers.celery_app import celery_app
    result = AsyncResult(task_id, app=celery_app)
    if result.ready():
        return {"status": "SUCCESS", "result": result.result}
    elif result.failed():
        return {"status": "FAILURE", "error": str(result.result)}
    return {"status": "PENDING"}


# ── Tab 5: Stress Testing — GAP-18 FIX ───────────────────────────────────────
@router.post("/stress-test/run")
async def run_stress_test(body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    from app.utils.mu_table import get_mu, get_plan_coverage, PLAN_CAP_MULTIPLIER

    city          = body.get("city","Mumbai")
    pct_affected  = float(body.get("pct_riders_affected", 0.3))
    trigger_type  = body.get("trigger_type","rain")
    duration_hrs  = float(body.get("avg_duration_hrs", 2.0))
    avg_income    = float(body.get("avg_income", 700))
    plan          = body.get("plan","standard")
    tier          = body.get("tier","B")

    active_policies = await conn.fetchval(
        "SELECT COUNT(*) FROM policies p JOIN hubs h ON p.hub_id=h.id WHERE h.city=$1 AND p.status='active' AND p.plan=$2",
        city, plan,
    ) or 0
    affected = int(int(active_policies) * pct_affected)
    cov_pct  = get_plan_coverage(plan, tier)
    mu       = get_mu(19)  # peak hour

    payout_per_rider = avg_income * cov_pct * (duration_hrs / 8) * mu
    total_payout     = payout_per_rider * affected

    total_premiums = float(await conn.fetchval(
        "SELECT COALESCE(SUM(weekly_premium),0) FROM policies p JOIN hubs h ON p.hub_id=h.id WHERE h.city=$1 AND p.status='active' AND p.plan=$2",
        city, plan,
    ) or 1)

    sim_loss_ratio = total_payout / total_premiums
    from app.services.liquidity_service import _classify_mode
    cap_reserves   = float(await conn.fetchval("SELECT value::float FROM system_config WHERE key='capital_reserves'") or 500000)
    liq_mode       = _classify_mode(cap_reserves / max(total_payout, 1), False)

    # Save scenario
    await conn.execute(
        "INSERT INTO stress_test_scenarios(name,scenario_type,params,last_result) VALUES($1,$2,$3::jsonb,$4::jsonb)",
        f"{city}_{trigger_type}_{pct_affected:.0%}", trigger_type, json.dumps(body), json.dumps({
            "affected_riders": affected, "total_payout_inr": total_payout,
            "simulated_loss_ratio": sim_loss_ratio,
        }),
    )

    return {
        "disclaimer": "SIMULATION ONLY — No live state changed.",
        "inputs": body,
        "results": {
            "affected_riders": affected,
            "total_payout_inr": round(total_payout, 2),
            "payout_per_rider_inr": round(payout_per_rider, 2),
            "simulated_loss_ratio": round(sim_loss_ratio, 4),
            "liquidity_mode_triggered": liq_mode,
            "recommended_action": _stress_recommendation(sim_loss_ratio, liq_mode),
        },
    }


def _stress_recommendation(lr: float, mode: str) -> str:
    if lr > 0.85 or mode in ("stressed","emergency"):
        return f"Pre-load reserve before this scenario. Current mode would be '{mode}'. Recommend increasing capital reserves or tightening oracle threshold."
    elif lr > 0.70:
        return "Monitor closely. Consider activating cautious liquidity mode preemptively."
    return "Within acceptable bounds. No immediate action required."


# ── Tab 6: Experiments ────────────────────────────────────────────────────────
# ARCH-03 FIX: all 13 controllable parameters with bounds (spec §15.6)
EXPERIMENT_BOUNDS = {
    "oracle_threshold":           (0.50, 0.80),
    "auto_clear_fs_threshold":    (0.25, 0.50),
    "hard_flag_fs_threshold":     (0.55, 0.80),
    "single_event_cap_pct":       (0.30, 0.70),
    "lambda_floor":               (1.0,  1.5),
    "risk_profile_high_mult":     (1.05, 1.30),
    "vov_reward_individual":      (5.0,  30.0),
    "discount_per_clean_week":    (0.01, 0.10),
    "max_discount_weeks":         (2.0,  8.0),
    # 4 missing parameters added (ARCH-03 fix):
    "confidence_band_1_factor":   (0.80, 1.00),  # oracle 0.85+ confidence multiplier
    "confidence_band_2_factor":   (0.70, 0.95),  # oracle 0.75–0.85 confidence multiplier
    "daily_soft_limit_divisor":   (3.0,  6.0),   # max_weekly / X = daily soft limit
    "vov_reward_zone_cert":       (10.0, 50.0),  # ₹ reward for zone certification contribution
}

@router.post("/experiments/set")
async def set_experiment(body: dict, admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    if body.get("confirm") != "CONFIRM":
        raise HTTPException(status_code=400, detail="Type CONFIRM to apply.")
    param    = body.get("parameter_name")
    value    = float(body.get("parameter_value"))
    group_id = body.get("group_id","all")

    if group_id == "holdout":
        raise HTTPException(status_code=400, detail="Holdout group cannot be modified.")

    bounds = EXPERIMENT_BOUNDS.get(param)
    if bounds:
        lo, hi = bounds
        if not (lo <= value <= hi):
            raise HTTPException(status_code=400, detail=f"{param} must be between {lo} and {hi}")

    # auto_clear hard cap
    if param == "auto_clear_fs_threshold" and value > 0.50:
        raise HTTPException(status_code=400, detail="auto_clear_fs_threshold cannot exceed 0.50")

    # Get current value for rollback
    cur_row = await conn.fetchrow("SELECT parameter_value FROM experiments WHERE parameter_name=$1 AND group_id=$2 AND active=true LIMIT 1", param, group_id)
    rollback_val = cur_row["parameter_value"] if cur_row else None

    await conn.execute("UPDATE experiments SET active=false WHERE parameter_name=$1 AND group_id=$2", param, group_id)
    exp_id = await conn.fetchval(
        "INSERT INTO experiments(parameter_name,parameter_value,group_id,active,rollback_value,created_by) VALUES($1,$2,$3,true,$4,$5) RETURNING id",
        param, str(value), group_id, rollback_val, admin["id"],
    )
    await conn.execute("INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) VALUES($1,'experiment_change','experiment',$2,$3::jsonb,NOW())", admin["id"], str(exp_id), json.dumps({"param": param, "value": value, "group": group_id}))
    return {"status": "applied", "experiment_id": str(exp_id), "note": "Takes effect within 15 min."}


@router.get("/experiments")
async def list_experiments(admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT * FROM experiments ORDER BY created_at DESC LIMIT 100")
    return {"experiments": [dict(r) for r in rows]}


@router.get("/experiments/config")
async def get_experiment_config(admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    try:
        rows = await conn.fetch("SELECT key, value FROM experiment_configs ORDER BY key")
        params = {r["key"]: r["value"] for r in rows}
    except Exception:
        # experiment_configs table not yet seeded - return defaults
        params = {}
    return {"params": params, "bounds": EXPERIMENT_BOUNDS, "config": []}


# ── Tab 7: Economics ──────────────────────────────────────────────────────────
@router.get("/economics")
async def get_economics(city: str = Query(None), admin: dict = Depends(get_current_admin), conn: asyncpg.Connection = Depends(get_db)):
    q = "SELECT * FROM segment_economics WHERE week_start=(SELECT MAX(week_start) FROM segment_economics)"
    params = []
    if city:
        q += " AND city=$1"
        params.append(city)
    q += " ORDER BY loss_ratio DESC NULLS LAST"
    rows = await conn.fetch(q, *params)
    segs = [dict(r) for r in rows]

    alerts = []
    for s in segs:
        lr = float(s.get("loss_ratio") or 0)
        if lr > 0.85:
            alerts.append({"type":"high","segment":s,"message":f"{s['city']} {s['plan']} Tier-{s['tier']} {s['risk_profile']}: loss ratio {lr:.0%} — recommend premium increase"})
        elif lr > 0 and lr < 0.30:
            alerts.append({"type":"opportunity","segment":s,"message":f"{s['city']} {s['plan']} Tier-{s['tier']}: very low {lr:.0%} — consider expanding coverage"})

    try:
        recon = await conn.fetch("SELECT * FROM reconciliation_reports ORDER BY run_at DESC LIMIT 10")
    except Exception:
        recon = []
    return {"segments": segs, "alerts": alerts, "reconciliation_reports": [dict(r) for r in recon]}


# ── Claims action alias (matches frontend call to /admin/claims/{id}/action) ──
@router.post("/claims/{claim_id}/action")
async def claim_action_alias(
    claim_id: uuid.UUID,
    body: dict,
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Alias for /fraud-queue/{claim_id}/action.
    Frontend calls this endpoint for all admin claim actions.
    Supports: approve | approve_partial | reject | escalate
    """
    return await fraud_action(claim_id, body, admin, conn)


# ── ML model status and training endpoints ────────────────────────────────────
@router.get("/ml/status")
async def ml_model_status(admin: dict = Depends(get_current_admin)):
    """Return current ML model metrics and training status."""
    from app.ml.vulnerability_model import get_model_metrics
    metrics = get_model_metrics()
    return {"status": "ok", "metrics": metrics}


@router.post("/ml/train")
async def trigger_ml_training(
    body: dict,
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Trigger ML model retraining via Celery (async, non-blocking).
    body: { use_synthetic: bool, min_samples: int, sync: bool }
    Returns task_id for polling, or metrics if sync=True.
    """
    use_sync = body.get("sync", False)  # sync=True for quick demo

    if use_sync:
        # Synchronous path for demo/admin quick-train
        from app.ml.vulnerability_model import train_vulnerability_model
        try:
            metrics = train_vulnerability_model()
            await conn.execute(
                "INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) "
                "VALUES($1,'ml_retrain','ml_model','vulnerability_model',$2::jsonb,NOW())",
                admin["id"], json.dumps({"triggered_by": "admin_sync", "metrics": metrics})
            )
            return {"status": "trained", "mode": "sync", "metrics": metrics}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Training failed: {str(exc)}")
    else:
        # Async Celery path for production
        try:
            from app.workers.ml_worker import retrain_vulnerability_model
            task = retrain_vulnerability_model.delay()
            await conn.execute(
                "INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) "
                "VALUES($1,'ml_retrain_queued','ml_model','vulnerability_model',$2::jsonb,NOW())",
                admin["id"], json.dumps({"triggered_by": "admin_async", "task_id": task.id})
            )
            return {"status": "queued", "mode": "async", "task_id": task.id,
                    "message": "Training queued. Poll /internal/admin/ml/status for completion."}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to queue training: {str(exc)}")


# ── God Mode: force a synthetic trigger (for demos/testing) ──────────────────
@router.post("/god-mode/trigger")
async def god_mode_trigger(
    body: dict,
    admin: dict = Depends(get_current_admin),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Force a synthetic trigger event for demo/testing purposes.
    body: { trigger_type: str, hub_id: str, oracle_score: float }
    """
    trigger_type = body.get("trigger_type", "rain")
    hub_id = body.get("hub_id")
    oracle_score = float(body.get("oracle_score", 0.85))

    if trigger_type not in ("rain", "flood", "heat", "aqi", "bandh", "platform_down"):
        raise HTTPException(status_code=400, detail="Invalid trigger_type")

    hub = None
    if hub_id:
        hub = await conn.fetchrow("SELECT * FROM hubs WHERE id = $1::uuid", hub_id)

    if not hub:
        hub = await conn.fetchrow("SELECT * FROM hubs LIMIT 1")

    if not hub:
        raise HTTPException(status_code=404, detail="No hub found to attach trigger")

    trigger_id = await conn.fetchval(
        """
        INSERT INTO trigger_events (
            trigger_type, h3_index, hub_id, oracle_score,
            consensus_score, status, is_synthetic, triggered_at
        ) VALUES ($1, $2, $3, $4, $4, 'active', true, NOW())
        RETURNING id
        """,
        trigger_type, hub["h3_index_res9"], hub["id"], oracle_score,
    )

    await conn.execute(
        "INSERT INTO admin_audit_log(admin_id,action,entity_type,entity_id,diff,performed_at) "
        "VALUES($1,'god_mode_trigger','trigger_event',$2,$3::jsonb,NOW())",
        admin["id"], str(trigger_id),
        json.dumps({"trigger_type": trigger_type, "hub_id": str(hub["id"]), "oracle_score": oracle_score})
    )

    # KEY FIX: initiate claims for all active riders in this zone
    # This is what makes the end-to-end demo flow work
    try:
        from app.workers.oracle_worker import initiate_claims_for_hex
        initiate_claims_for_hex.delay(hub["h3_index_res9"], str(trigger_id), trigger_type)
        claims_queued = True
    except Exception as exc:
        log.warning("god_mode_claims_queue_failed", error=str(exc))
        claims_queued = False

    return {
        "status": "trigger_created",
        "trigger_id": str(trigger_id),
        "trigger_type": trigger_type,
        "hub_name": hub["name"],
        "hub_id": str(hub["id"]),
        "h3_index": hub["h3_index_res9"],
        "oracle_score": oracle_score,
        "is_synthetic": True,
        "claims_queued": claims_queued,
        "message": "Trigger fired. Claims queued for all active riders in zone. Payout in ~60s if fraud checks pass.",
    }


@router.get("/ml/versions")
async def list_ml_versions(admin: dict = Depends(get_current_admin)):
    """List all archived ML model versions available for rollback."""
    import os
    from app.config import get_settings
    from app.ml.vulnerability_model import get_model_metrics
    
    settings = get_settings()
    archive_dir = os.path.join(settings.ml_models_path, "archive")
    
    versions = []
    if os.path.exists(archive_dir):
        for fname in sorted(os.listdir(archive_dir), reverse=True):
            if fname.startswith("vulnerability_model_") and fname.endswith(".pkl"):
                fpath = os.path.join(archive_dir, fname)
                versions.append({
                    "filename": fname,
                    "timestamp": fname.replace("vulnerability_model_", "").replace(".pkl", ""),
                    "size_kb": round(os.path.getsize(fpath) / 1024, 1),
                    "path": fpath,
                })
    
    current_metrics = get_model_metrics()
    return {
        "current_model": current_metrics,
        "archived_versions": versions,
        "total_versions": len(versions),
    }


@router.post("/ml/rollback")
async def rollback_ml_model(
    body: dict,
    admin: dict = Depends(get_current_admin),
):
    """Rollback to a previously archived ML model version."""
    import os, shutil
    from app.config import get_settings
    settings = get_settings()
    
    version_ts = body.get("timestamp")
    if not version_ts:
        raise HTTPException(status_code=400, detail="timestamp required")
    
    archive_path = os.path.join(settings.ml_models_path, "archive", f"vulnerability_model_{version_ts}.pkl")
    if not os.path.exists(archive_path):
        raise HTTPException(status_code=404, detail=f"Version {version_ts} not found")
    
    model_path = os.path.join(settings.ml_models_path, "vulnerability_model.pkl")
    shutil.copy2(archive_path, model_path + ".staging")
    shutil.move(model_path + ".staging", model_path)
    
    log.info("ml_model_rolled_back", version=version_ts, admin_id=str(admin["id"]))
    return {"status": "rolled_back", "version": version_ts}
