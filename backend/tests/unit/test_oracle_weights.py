"""tests/unit/test_oracle_weights.py — Oracle weight configs and signal scoring."""
import pytest
from app.services.oracle_service import (
    WEIGHT_CONFIGS, _apply_penalties, _renormalize
)


class TestWeightConfigs:
    def test_base_sums_to_1(self):
        weights = WEIGHT_CONFIGS["base"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_peer_sums_to_1(self):
        weights = WEIGHT_CONFIGS["peer"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_accel_sums_to_1(self):
        weights = WEIGHT_CONFIGS["accel"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_both_sums_to_1(self):
        weights = WEIGHT_CONFIGS["both"]
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_base_satellite_weight_highest(self):
        base = WEIGHT_CONFIGS["base"]
        assert base["satellite"] == 0.40  # highest in base config

    def test_peer_config_includes_peer_signal(self):
        assert "peer" in WEIGHT_CONFIGS["peer"]

    def test_both_config_includes_peer_and_accel(self):
        both = WEIGHT_CONFIGS["both"]
        assert "peer" in both
        assert "accel" in both


class TestRenormalization:
    def test_already_normalized_unchanged(self):
        w = {"a": 0.40, "b": 0.30, "c": 0.30}
        result = _renormalize(w)
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_skipped_signal_renormalized(self):
        """Simulate satellite signal unavailable → skip it → renormalize weather+traffic."""
        base = {"satellite": 0.40, "weather": 0.30, "traffic": 0.30}
        # satellite has penalty=None (skip), weather has penalty=0, traffic=0
        adjusted = _apply_penalties(base, {"satellite": None, "weather": 0.0, "traffic": 0.0})
        normalized = _renormalize(adjusted)
        assert abs(sum(normalized.values()) - 1.0) < 0.001
        assert "satellite" not in normalized

    def test_fallback_api_penalty_applied(self):
        """Fallback API used → 10% penalty on that signal's weight."""
        base = {"weather": 0.30, "traffic": 0.30, "satellite": 0.40}
        penalties = {"weather": 0.10, "traffic": 0.0, "satellite": 0.0}
        adjusted = _apply_penalties(base, penalties)
        # Weather weight reduced by 10%
        assert adjusted["weather"] < base["weather"]

    def test_stale_cache_15pct_penalty(self):
        base = {"weather": 1.0}
        penalties = {"weather": 0.15}
        adjusted = _apply_penalties(base, penalties)
        assert abs(adjusted["weather"] - 0.85) < 0.001

    def test_empty_weights_after_all_skipped(self):
        base = {"satellite": 0.40, "weather": 0.30, "traffic": 0.30}
        penalties = {"satellite": None, "weather": None, "traffic": None}
        adjusted = _apply_penalties(base, penalties)
        assert len(adjusted) == 0


class TestOracleScoreComputation:
    def test_all_signals_max_score_is_1(self):
        """If all signals are 1.0, oracle score should be 1.0."""
        weights = WEIGHT_CONFIGS["base"]
        signals = {"satellite": 1.0, "weather": 1.0, "traffic": 1.0}
        score = sum(weights.get(k, 0) * v for k, v in signals.items())
        assert abs(score - 1.0) < 0.001

    def test_all_signals_zero_score_is_0(self):
        weights = WEIGHT_CONFIGS["base"]
        signals = {"satellite": 0.0, "weather": 0.0, "traffic": 0.0}
        score = sum(weights.get(k, 0) * v for k, v in signals.items())
        assert score == 0.0

    def test_rain_score_at_50mm_is_1(self):
        from app.external.owm_client import _score_rain
        assert _score_rain(50.0) == 1.0

    def test_rain_score_at_35mm_is_0_70(self):
        from app.external.owm_client import _score_rain
        assert abs(_score_rain(35.0) - 0.70) < 0.001

    def test_rain_score_below_20mm_is_0(self):
        from app.external.owm_client import _score_rain
        assert _score_rain(15.0) == 0.0

    def test_aqi_score_at_450_is_1(self):
        from app.external.waqi_client import _score_aqi
        assert _score_aqi(450) == 1.0

    def test_aqi_score_below_200_is_0(self):
        from app.external.waqi_client import _score_aqi
        assert _score_aqi(199) == 0.0

    def test_platform_down_score_6_consecutive_is_1(self):
        from app.external.platform_adapter import _score_platform_down
        assert _score_platform_down(6) == 1.0
        assert _score_platform_down(7) == 1.0

    def test_platform_down_score_3_consecutive_is_0_5(self):
        from app.external.platform_adapter import _score_platform_down
        assert _score_platform_down(3) == 0.50

    def test_platform_down_score_below_3_is_0(self):
        from app.external.platform_adapter import _score_platform_down
        assert _score_platform_down(2) == 0.0
