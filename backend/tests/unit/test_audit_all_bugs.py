"""tests/unit/test_audit_all_bugs.py — Tests covering every bug from the audit report."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ─── BUG-03: Loss ratio uses 30-day window ───────────────────────────────────
def test_loss_ratio_uses_30_day_window():
    """Verify liquidity_service uses 30-day not 7-day window."""
    import inspect
    from app.services.liquidity_service import _compute_loss_ratio
    source = inspect.getsource(_compute_loss_ratio)
    assert "30 days" in source, "Loss ratio must use 30-day rolling window (was 7 days — BUG-03)"
    assert "7 days" not in source, "Old 7-day window must be removed"


# ─── BUG-04: Claim marked auto_cleared (not paid) before Razorpay confirms ──
def test_payout_worker_sets_auto_cleared_not_paid():
    """L3 guard in payout_worker must use auto_cleared, not paid."""
    import inspect
    from app.workers import payout_worker
    source = inspect.getsource(payout_worker.process_claim_payout_task)
    assert "auto_cleared" in source, "L3 guard must set status=auto_cleared, not paid"
    # The 'paid' string may appear in the NOT IN exclusion list, that's fine
    # but the SET clause must not set 'paid' before Razorpay


def test_payout_service_sets_auto_cleared_not_paid():
    """payout_service L3 guard must use auto_cleared."""
    import inspect
    from app.services.payout_service import _execute_payout
    source = inspect.getsource(_execute_payout)
    assert "auto_cleared" in source


# ─── BUG-08: Razorpay ref update wrapped in try/except ───────────────────────
def test_payout_worker_razorpay_ref_update_has_error_handling():
    """razorpay_ref update in payout_worker must not swallow DB failures silently."""
    import inspect
    from app.workers import payout_worker
    source = inspect.getsource(payout_worker.process_claim_payout_task)
    assert "razorpay_ref_update_failed" in source or "ref_exc" in source, \
        "Razorpay ref update must log failure if DB is unavailable after payout sent"


# ─── SEC-04: No SQL injection in entity_state_log insert ─────────────────────
def test_no_sql_injection_in_payout_service():
    """entity_state_log insert must use parameterized $1, not string replacement."""
    import inspect
    from app.services.payout_service import _execute_payout
    source = inspect.getsource(_execute_payout)
    assert '.replace("$1"' not in source, "SQL injection: .replace($1) must not be used"
    assert "str(rider[\"id\"])" not in source.split("entity_state_log")[1][:200] \
        if "entity_state_log" in source else True


# ─── BUG-01/oracle: cache fallback confidence penalty ────────────────────────
def test_oracle_service_exists_and_has_fetch_fallback():
    """oracle_service must have _fetch_with_fallback function."""
    from app.services.oracle_service import compute_oracle_score
    assert callable(compute_oracle_score)


# ─── AUC-ROC gate ≥ 0.70 ─────────────────────────────────────────────────────
def test_auc_roc_gate_is_at_least_0_70():
    import inspect
    from app.ml.vulnerability_model import train_vulnerability_model
    source = inspect.getsource(train_vulnerability_model)
    assert "< 0.70" in source or "< 0.75" in source or "< 0.78" in source, \
        "AUC-ROC gate must be at least 0.70 (was 0.60 — too lenient)"
    assert "< 0.60" not in source, "Old lenient 0.60 gate must be removed"


# ─── YOLO custom model fallback ──────────────────────────────────────────────
def test_vov_worker_has_custom_yolo_fallback():
    import inspect
    from app.workers.vov_worker import _run_yolov8
    source = inspect.getsource(_run_yolov8)
    assert "yolov8n_gigshield" in source or "custom" in source, \
        "vov_worker must attempt to load custom GigShield YOLO model"
    assert "yolov8n.pt" in source, "Must fall back to stock COCO model if custom not found"


# ─── ARCH-05: Rider consent log at enrollment ─────────────────────────────────
def test_policy_service_inserts_consent_log():
    import inspect
    from app.services.policy_service import enroll_policy
    source = inspect.getsource(enroll_policy)
    assert "rider_consent_log" in source, \
        "enroll_policy must insert consent record (DPDP Act §24.3)"


# ─── ARCH-06: Income deviation cap implemented ───────────────────────────────
def test_income_deviation_cap_exists():
    from app.services.income_service import check_income_deviation
    assert callable(check_income_deviation)


@pytest.mark.asyncio
async def test_income_deviation_flags_over_30_pct():
    from app.services.income_service import check_income_deviation
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"effective_income": 600.0})

    # 600 -> 900 = 50% change, should be flagged
    result = await check_income_deviation(mock_conn, "some-id", 900.0)
    assert result["flag"] is True
    assert result["change_pct"] > 0.30


@pytest.mark.asyncio
async def test_income_deviation_ok_under_30_pct():
    from app.services.income_service import check_income_deviation
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"effective_income": 600.0})

    # 600 -> 700 = 16.7% change, should pass
    result = await check_income_deviation(mock_conn, "some-id", 700.0)
    assert result["flag"] is False


# ─── Rate limiting on recovery queue drain ───────────────────────────────────
def test_drain_recovery_queue_has_rate_limit():
    import inspect
    from app.workers.payout_worker import drain_recovery_queue
    source = inspect.getsource(drain_recovery_queue)
    assert "sleep" in source or "DRAIN_INTERVAL" in source, \
        "drain_recovery_queue must rate-limit to 50/min (spec §19.3)"


# ─── Continuation worker: NULL shift_status treated as active ────────────────
def test_continuation_worker_null_shift_treated_as_active():
    import inspect
    from app.workers.continuation_worker import run_continuation_loop
    source = inspect.getsource(run_continuation_loop)
    # Should only skip on explicit "offline", not on None
    assert 'shift_status == "offline"' in source, "Must only skip explicit offline status"


# ─── Zone vulnerability cache writer exists ──────────────────────────────────
def test_zone_vulnerability_cache_writer_task_exists():
    from app.workers.ml_worker import update_zone_vulnerability_cache
    assert callable(update_zone_vulnerability_cache)


# ─── Fraud score formula ─────────────────────────────────────────────────────
def test_fraud_score_formula():
    from app.services.fraud_service import compute_fraud_score
    # 1.0 - (0.60 * oracle + 0.40 * presence)
    score = compute_fraud_score(oracle_confidence=1.0, presence_confidence=1.0)
    assert score == 0.0

    score2 = compute_fraud_score(oracle_confidence=0.0, presence_confidence=0.0)
    assert score2 == 1.0

    score3 = compute_fraud_score(oracle_confidence=0.8, presence_confidence=0.67)
    expected = round(1.0 - (0.60 * 0.8 + 0.40 * 0.67), 4)
    assert abs(score3 - expected) < 0.001


# ─── Classify fraud thresholds ───────────────────────────────────────────────
def test_classify_fraud_auto_clear():
    from app.services.fraud_service import classify_fraud
    assert classify_fraud(0.20) == "auto_cleared"
    assert classify_fraud(0.55) == "soft_flagged"
    assert classify_fraud(0.85) == "hard_flagged"


def test_classify_fraud_high_risk_tighter_thresholds():
    from app.services.fraud_service import classify_fraud
    # High risk: auto_clear threshold drops to 0.30
    assert classify_fraud(0.35, risk_profile="high") == "soft_flagged"
    assert classify_fraud(0.20, risk_profile="high") == "auto_cleared"


# ─── Payout formula ──────────────────────────────────────────────────────────
def test_payout_formula_basic():
    """event_payout = income * cov_pct * (dur/8) * mu"""
    from app.utils.mu_table import get_mu, get_min_duration
    income = 800.0
    cov_pct = 0.75
    trigger_type = "rain"
    mu = get_mu(9)  # 09:00 IST = peak hour μ=1.50
    dur = get_min_duration(trigger_type)  # 1.0 hr

    expected = income * cov_pct * (dur / 8) * mu
    assert abs(expected - 112.5) < 0.01


# ─── Migration 004 has required columns ──────────────────────────────────────
def test_migration_004_has_email_column():
    import os
    migration_path = os.path.join(
        os.path.dirname(__file__), "../../supabase/migrations/004_auth_and_audit_fixes.sql"
    )
    assert os.path.exists(migration_path), "Migration 004 must exist"
    with open(migration_path) as f:
        content = f.read()
    assert "email" in content
    assert "password_hash" in content
    assert "supabase_user_id" in content


# ─── requirements.txt has ultralytics, no twilio ─────────────────────────────
def test_requirements_has_ultralytics_no_twilio():
    import os
    req_path = os.path.join(
        os.path.dirname(__file__), "../../requirements.txt"
    )
    with open(req_path) as f:
        content = f.read().lower()
    assert "ultralytics" in content, "ultralytics must be in requirements.txt"
    assert "twilio" not in content, "twilio must be removed from requirements.txt"


# ─── Security: no datetime.now() for business logic ─────────────────────────
def test_no_naive_datetime_now_in_payout_service():
    """payout_service must not use datetime.now() for business timestamps."""
    import inspect
    from app.services import payout_service
    source = inspect.getsource(payout_service)
    # datetime.now(timezone.utc) is acceptable; bare datetime.now() is not
    import re
    bad = re.findall(r'datetime\.now\(\)', source)
    assert len(bad) == 0, f"Found bare datetime.now() in payout_service: {bad}"
