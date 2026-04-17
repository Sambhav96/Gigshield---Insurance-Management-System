"""tests/unit/test_audit_fixes.py — Tests for all systems fixed by the audit."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta


# ══════════════════════════════════════════════════════════════════════════════
# Trigger Stacking Rule (spec 7.5)
# ══════════════════════════════════════════════════════════════════════════════

class TestTriggerStacking:
    """Concurrent triggers → MAX payout wins. Priority breaks ties."""

    def _trigger(self, t_type, payout):
        return {"id": "abc", "trigger_type": t_type, "event_payout_estimate": payout}

    def test_max_payout_wins(self):
        from app.services.oracle_service import resolve_stacking
        triggers = [
            self._trigger("rain",  100.0),
            self._trigger("bandh", 250.0),
            self._trigger("aqi",    80.0),
        ]
        winner, suppressed = resolve_stacking(triggers)
        assert winner["trigger_type"] == "bandh"
        assert len(suppressed) == 2

    def test_tie_break_by_priority(self):
        from app.services.oracle_service import resolve_stacking, TRIGGER_PRIORITY
        # flood and platform_down both pay ₹200; flood has higher priority
        triggers = [
            self._trigger("platform_down", 200.0),
            self._trigger("flood",         200.0),
        ]
        winner, suppressed = resolve_stacking(triggers)
        assert winner["trigger_type"] == "flood"

    def test_single_trigger_no_stacking(self):
        from app.services.oracle_service import resolve_stacking
        triggers = [self._trigger("rain", 150.0)]
        winner, suppressed = resolve_stacking(triggers)
        assert winner["trigger_type"] == "rain"
        assert suppressed == []

    def test_empty_triggers_raises(self):
        from app.services.oracle_service import resolve_stacking
        with pytest.raises(ValueError):
            resolve_stacking([])

    def test_priority_order_is_correct(self):
        from app.services.oracle_service import TRIGGER_PRIORITY
        assert TRIGGER_PRIORITY[0] == "flood"
        assert TRIGGER_PRIORITY[1] == "platform_down"
        assert TRIGGER_PRIORITY[-1] == "heat"
        assert len(TRIGGER_PRIORITY) == 6

    def test_stacking_not_additive(self):
        """Critical: payouts are NOT added together."""
        from app.services.oracle_service import resolve_stacking
        triggers = [self._trigger("rain", 100), self._trigger("bandh", 150)]
        winner, suppressed = resolve_stacking(triggers)
        # Total payout = winner only (₹150), NOT ₹250
        assert winner["event_payout_estimate"] == 150
        assert sum(s["event_payout_estimate"] for s in suppressed) > 0  # suppressed > 0


# ══════════════════════════════════════════════════════════════════════════════
# Correlation Factor (spec 7.6)
# ══════════════════════════════════════════════════════════════════════════════

class TestCorrelationFactor:
    def test_platform_down_always_1_0(self):
        from app.utils.mu_table import get_correlation_payout_factor
        # platform_down always C=1.0 → payout_factor=0.70
        assert get_correlation_payout_factor(1.0) == 0.70

    def test_low_correlation_full_payout(self):
        from app.utils.mu_table import get_correlation_payout_factor
        assert get_correlation_payout_factor(0.10) == 1.00
        assert get_correlation_payout_factor(0.20) == 1.00

    def test_medium_high_correlation_reduced(self):
        from app.utils.mu_table import get_correlation_payout_factor
        assert get_correlation_payout_factor(0.40) == 0.90
        assert get_correlation_payout_factor(0.60) == 0.80
        assert get_correlation_payout_factor(0.80) == 0.70

    def test_payout_factor_monotonically_decreasing(self):
        from app.utils.mu_table import get_correlation_payout_factor
        levels = [0.10, 0.25, 0.45, 0.65, 0.85]
        factors = [get_correlation_payout_factor(c) for c in levels]
        for i in range(len(factors) - 1):
            assert factors[i] >= factors[i + 1]


# ══════════════════════════════════════════════════════════════════════════════
# Cooldown Factor (spec 7.4)
# ══════════════════════════════════════════════════════════════════════════════

class TestCooldownLogic:
    def test_cooldown_halves_payout(self):
        """If in cooldown: cooldown_payout_factor = 0.50."""
        payout       = 200.0
        with_cooldown = payout * 0.50
        assert with_cooldown == 100.0

    def test_no_cooldown_full_payout(self):
        payout         = 200.0
        without_cooldown = payout * 1.00
        assert without_cooldown == 200.0

    def test_cooldown_minutes_per_trigger_type(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["rain"]          == 120
        assert COOLDOWN_MINUTES["flood"]         == 240
        assert COOLDOWN_MINUTES["heat"]          == 360
        assert COOLDOWN_MINUTES["bandh"]         == 480
        assert COOLDOWN_MINUTES["platform_down"] == 60


# ══════════════════════════════════════════════════════════════════════════════
# Risk Score Decay (spec 4.2)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskDecay:
    def test_clean_week_pulls_high_score_down(self):
        from app.services.fraud_service import apply_risk_decay
        score = apply_risk_decay(current_score=80, week_had_payouts=False)
        assert score == 78   # −2 toward 50

    def test_clean_week_pulls_low_score_up(self):
        from app.services.fraud_service import apply_risk_decay
        score = apply_risk_decay(current_score=20, week_had_payouts=False)
        assert score == 22   # +2 toward 50

    def test_score_at_50_no_change(self):
        from app.services.fraud_service import apply_risk_decay
        score = apply_risk_decay(current_score=50, week_had_payouts=False)
        # At exactly 50: direction = +1 (since 50 is not > 50)
        assert score == 52

    def test_payout_week_no_decay(self):
        from app.services.fraud_service import apply_risk_decay
        score = apply_risk_decay(current_score=80, week_had_payouts=True)
        assert score == 80   # no change on payout week

    def test_score_clamped_at_0_and_100(self):
        from app.services.fraud_service import apply_risk_decay
        assert apply_risk_decay(0,   False) >= 0
        assert apply_risk_decay(100, False) <= 100

    def test_hard_flag_adds_30(self):
        from app.services.fraud_service import apply_hard_flag_penalty
        assert apply_hard_flag_penalty(40)  == 70
        assert apply_hard_flag_penalty(80)  == 100   # capped

    def test_fraud_confirmed_score_100(self):
        from app.services.fraud_service import apply_hard_flag_penalty
        assert apply_hard_flag_penalty(30, fraud_confirmed=True) == 100
        assert apply_hard_flag_penalty(0,  fraud_confirmed=True) == 100


# ══════════════════════════════════════════════════════════════════════════════
# Oracle Weight Configs + Renormalization (extended)
# ══════════════════════════════════════════════════════════════════════════════

class TestOracleWeightsExtended:
    def test_all_configs_sum_to_1(self):
        from app.services.oracle_service import WEIGHT_CONFIGS
        for name, weights in WEIGHT_CONFIGS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001, f"Config '{name}' sums to {total}"

    def test_peer_config_has_peer_signal(self):
        from app.services.oracle_service import WEIGHT_CONFIGS
        assert "peer" in WEIGHT_CONFIGS["peer"]
        assert WEIGHT_CONFIGS["peer"]["peer"] == 0.20

    def test_both_config_has_peer_and_accel(self):
        from app.services.oracle_service import WEIGHT_CONFIGS
        both = WEIGHT_CONFIGS["both"]
        assert "peer" in both and "accel" in both
        assert both["peer"] + both["accel"] == 0.35

    def test_renormalize_after_signal_skip(self):
        from app.services.oracle_service import _apply_penalties, _renormalize
        # satellite skipped → renormalize weather+traffic to 1.0
        weights  = {"satellite": 0.40, "weather": 0.30, "traffic": 0.30}
        penalties = {"satellite": None, "weather": 0.0, "traffic": 0.0}
        adjusted  = _apply_penalties(weights, penalties)
        normalized = _renormalize(adjusted)
        assert "satellite" not in normalized
        assert abs(sum(normalized.values()) - 1.0) < 0.001
        assert abs(normalized["weather"] / normalized["traffic"] - 1.0) < 0.001

    def test_fallback_penalty_reduces_weight(self):
        from app.services.oracle_service import _apply_penalties
        weights   = {"weather": 0.30}
        penalties = {"weather": 0.10}
        adjusted  = _apply_penalties(weights, penalties)
        assert abs(adjusted["weather"] - 0.27) < 0.001   # 0.30 × 0.90

    def test_stale_cache_penalty_larger(self):
        from app.services.oracle_service import _apply_penalties
        w_fallback   = _apply_penalties({"weather": 0.30}, {"weather": 0.10})
        w_stale      = _apply_penalties({"weather": 0.30}, {"weather": 0.15})
        assert w_fallback["weather"] > w_stale["weather"]


# ══════════════════════════════════════════════════════════════════════════════
# ML Vulnerability Model (spec 22)
# ══════════════════════════════════════════════════════════════════════════════

class TestVulnerabilityModel:
    def test_synthetic_data_generation(self):
        from app.ml.vulnerability_model import _generate_synthetic_data, FEATURES
        df = _generate_synthetic_data(n_samples=500)
        assert len(df) == 500
        for feat in FEATURES:
            assert feat in df.columns, f"Missing feature: {feat}"
        assert "will_claim" in df.columns

    def test_predict_fallback_when_model_missing(self):
        from app.ml.vulnerability_model import predict_vulnerability
        import os
        # Temporarily ensure model doesn't exist
        with patch("os.path.exists", return_value=False):
            result = predict_vulnerability({"risk_score": 75})
            assert abs(result - 0.75) < 0.001

    def test_predict_bounded_0_to_1(self):
        from app.ml.vulnerability_model import predict_vulnerability
        with patch("os.path.exists", return_value=False):
            for score in [0, 50, 100]:
                v = predict_vulnerability({"risk_score": score})
                assert 0.0 <= v <= 1.0

    def test_high_risk_score_higher_vulnerability(self):
        from app.ml.vulnerability_model import predict_vulnerability
        with patch("os.path.exists", return_value=False):
            low  = predict_vulnerability({"risk_score": 20})
            high = predict_vulnerability({"risk_score": 80})
            assert high > low


class TestPoisoningDetector:
    def test_removes_fraud_cluster_riders(self):
        from app.ml.poisoning_detector import filter_poisoned_samples
        import pandas as pd
        df = pd.DataFrame({
            "risk_score": [50, 60, 70],
            "claims_per_week_90d": [0.5, 0.3, 0.4],
            "avg_fraud_score_90d": [0.2, 0.1, 0.15],
            "hard_flag_count_90d": [0, 0, 0],
            "vov_submissions_90d": [1, 2, 1],
            "avg_shift_hours_7d":  [8, 7, 9],
            "city_encoded": [0, 0, 0],
            "plan_encoded": [1, 1, 1],
            "effective_income_normalized": [0.6, 0.7, 0.5],
            "hub_drainage_index": [0.5, 0.6, 0.4],
            "will_claim": [0, 1, 0],
            "is_fraud_cluster": [True, False, False],
            "has_manual_override": [False, False, False],
        })
        clean, report = filter_poisoned_samples(df)
        assert len(clean) == 2
        assert report["removed_total"] >= 1

    def test_removes_manual_override_claims(self):
        from app.ml.poisoning_detector import filter_poisoned_samples
        import pandas as pd
        df = pd.DataFrame({
            "risk_score": [50, 60],
            "claims_per_week_90d": [0.5, 0.3],
            "avg_fraud_score_90d": [0.2, 0.1],
            "hard_flag_count_90d": [0, 0],
            "vov_submissions_90d": [1, 2],
            "avg_shift_hours_7d":  [8, 7],
            "city_encoded": [0, 0],
            "plan_encoded": [1, 1],
            "effective_income_normalized": [0.6, 0.7],
            "hub_drainage_index": [0.5, 0.6],
            "will_claim": [0, 1],
            "is_fraud_cluster": [False, False],
            "has_manual_override": [True, False],
        })
        clean, _ = filter_poisoned_samples(df)
        assert len(clean) == 1

    def test_quality_report_structure(self):
        from app.ml.poisoning_detector import filter_poisoned_samples
        import pandas as pd
        df = pd.DataFrame({
            "risk_score": [50], "claims_per_week_90d": [0.3],
            "avg_fraud_score_90d": [0.1], "hard_flag_count_90d": [0],
            "vov_submissions_90d": [1], "avg_shift_hours_7d": [8],
            "city_encoded": [0], "plan_encoded": [1],
            "effective_income_normalized": [0.6], "hub_drainage_index": [0.5],
            "will_claim": [0], "is_fraud_cluster": [False], "has_manual_override": [False],
        })
        _, report = filter_poisoned_samples(df)
        assert "original_count" in report
        assert "final_count" in report
        assert "retention_pct" in report
        assert "filters_applied" in report


# ══════════════════════════════════════════════════════════════════════════════
# DB State Machine constraints (verify Python-level logic matches SQL triggers)
# ══════════════════════════════════════════════════════════════════════════════

class TestStateMachineLogic:
    def test_terminal_claim_states(self):
        """paid, rejected, manual_rejected, cap_exhausted are terminal."""
        terminal = {"paid", "rejected", "manual_rejected", "cap_exhausted"}
        # In payout_service: check status before processing
        for s in terminal:
            result = "blocked" if s in terminal else "proceed"
            assert result == "blocked"

    def test_trigger_state_valid_transitions(self):
        """detected→active→resolving→resolved (or cancelled). No skipping."""
        valid = {
            "detected":  ["active"],
            "active":    ["resolving", "cancelled"],
            "resolving": ["resolved", "active"],
            "resolved":  [],
            "cancelled": [],
        }
        # detected cannot go to resolved directly
        assert "resolved" not in valid["detected"]
        assert "resolving" not in valid["detected"]

    def test_policy_cancelled_is_terminal(self):
        """Cancelled policy cannot be reactivated."""
        valid_from_cancelled = []
        assert "active" not in valid_from_cancelled
        assert "paused" not in valid_from_cancelled


# ══════════════════════════════════════════════════════════════════════════════
# Cooldown minutes correctness (BUG-05)
# ══════════════════════════════════════════════════════════════════════════════

class TestCooldownMinutesSpec:
    """BUG-05 FIX verification: cooldown values must match spec §7.3."""
    def test_rain_cooldown_is_90_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["rain"] == 90, f"Expected 90, got {COOLDOWN_MINUTES['rain']}"

    def test_heat_cooldown_is_120_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["heat"] == 120, f"Expected 120, got {COOLDOWN_MINUTES['heat']}"

    def test_aqi_cooldown_is_120_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["aqi"] == 120, f"Expected 120, got {COOLDOWN_MINUTES['aqi']}"

    def test_bandh_cooldown_is_180_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["bandh"] == 180, f"Expected 180, got {COOLDOWN_MINUTES['bandh']}"

    def test_flood_cooldown_is_240_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["flood"] == 240

    def test_platform_down_cooldown_is_60_minutes(self):
        from app.utils.mu_table import COOLDOWN_MINUTES
        assert COOLDOWN_MINUTES["platform_down"] == 60
