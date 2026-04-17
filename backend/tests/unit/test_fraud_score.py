"""tests/unit/test_fraud_score.py — Fraud detection unit tests."""
import pytest
from datetime import datetime, timedelta, timezone
from app.services.fraud_service import (
    check_intent, check_presence, compute_fraud_score, classify_fraud,
    GPS_VELOCITY_LIMIT_KMH,
)


def make_ping(lat, lng, speed=15.0, session=True, status="available", minutes_ago=0):
    t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "latitude": lat, "longitude": lng,
        "speed_kmh": speed, "session_active": session,
        "platform_status": status, "recorded_at": t,
        "h3_index_res9": "8b5225c50d4ffff",
    }


class TestIntentCheck:
    def test_all_factors_pass(self, sample_pings):
        trigger_time = datetime.now(timezone.utc)
        passed, factors = check_intent(sample_pings, trigger_time, "rider-123", "zepto")
        assert passed is True
        assert factors["f1_gps"] is True
        assert factors["f2_session"] is True

    def test_no_pings_fails_intent(self):
        trigger_time = datetime.now(timezone.utc)
        passed, factors = check_intent([], trigger_time, "rider-123", "zepto")
        assert passed is False
        assert factors["f1_gps"] is False

    def test_no_session_fails_intent(self):
        pings = [make_ping(19.11, 72.87, session=False, minutes_ago=i*10) for i in range(3)]
        trigger_time = datetime.now(timezone.utc)
        passed, factors = check_intent(pings, trigger_time, "rider-123", "zepto")
        assert factors["f2_session"] is False
        assert passed is False

    def test_stationary_residential_fails_f1(self):
        # All pings at exact same location for 50 min → stationary
        t_base = datetime.now(timezone.utc) - timedelta(minutes=50)
        pings = [
            {**make_ping(19.1136, 72.8697, speed=0.0, session=True),
             "recorded_at": t_base + timedelta(minutes=i*10)}
            for i in range(6)
        ]
        trigger_time = datetime.now(timezone.utc)
        passed, factors = check_intent(pings, trigger_time, "rider-123", "zepto")
        assert factors["f1_gps"] is False


class TestPresenceCheck:
    HUB_LAT = 19.1136
    HUB_LNG = 72.8697
    HUB_H3  = "8b5225c50d4ffff"

    def test_3_of_3_within_hub_full_confidence(self, sample_pings):
        conf, hard_flag = check_presence(
            sample_pings, self.HUB_LAT, self.HUB_LNG, 2.0, self.HUB_H3
        )
        assert conf >= 0.67
        assert hard_flag is False

    def test_velocity_spoofing_hard_flag(self):
        """Implied speed > 150 km/h between two pings."""
        t1 = datetime.now(timezone.utc) - timedelta(minutes=5)
        t2 = datetime.now(timezone.utc)
        pings = [
            {"latitude": 19.1136, "longitude": 72.8697, "speed_kmh": 10, "session_active": True,
             "platform_status": "available", "recorded_at": t1, "h3_index_res9": self.HUB_H3},
            # 500 km away in 5 minutes = 6000 km/h
            {"latitude": 23.0000, "longitude": 77.0000, "speed_kmh": 10, "session_active": True,
             "platform_status": "available", "recorded_at": t2, "h3_index_res9": "different_hex"},
        ]
        conf, hard_flag = check_presence(pings, self.HUB_LAT, self.HUB_LNG, 2.0, self.HUB_H3)
        assert hard_flag is True

    def test_far_from_hub_fails_presence(self):
        pings = [make_ping(28.6315, 77.2167, minutes_ago=i*5) for i in range(3)]  # Delhi
        conf, hard_flag = check_presence(pings, self.HUB_LAT, self.HUB_LNG, 2.0, self.HUB_H3)
        assert conf < 0.67
        assert hard_flag is False

    def test_no_pings_zero_confidence(self):
        conf, hard_flag = check_presence([], self.HUB_LAT, self.HUB_LNG, 2.0, self.HUB_H3)
        assert conf == 0.0
        assert hard_flag is False


class TestFraudScore:
    def test_high_oracle_high_presence_low_score(self):
        fs = compute_fraud_score(oracle_confidence=0.90, presence_confidence=1.00)
        # 1.0 - (0.60×0.90 + 0.40×1.00) = 1.0 - 0.94 = 0.06
        assert abs(fs - 0.06) < 0.01

    def test_low_oracle_low_presence_high_score(self):
        fs = compute_fraud_score(oracle_confidence=0.50, presence_confidence=0.33)
        # 1.0 - (0.60×0.50 + 0.40×0.33) = 1.0 - 0.432 = 0.568
        assert abs(fs - 0.568) < 0.01

    def test_real_flood_wrong_location(self):
        # Example from spec: oracle=0.90, presence=0.20
        fs = compute_fraud_score(0.90, 0.20)
        assert abs(fs - 0.38) < 0.01

    def test_marginal_oracle_correct_location(self):
        # Example from spec: oracle=0.67, presence=1.00
        fs = compute_fraud_score(0.67, 1.00)
        assert abs(fs - 0.198) < 0.01

    def test_score_bounded_0_to_1(self):
        fs1 = compute_fraud_score(1.0, 1.0)
        fs2 = compute_fraud_score(0.0, 0.0)
        assert 0.0 <= fs1 <= 1.0
        assert 0.0 <= fs2 <= 1.0


class TestClassifyFraud:
    def test_auto_clear_below_0_40(self):
        assert classify_fraud(0.39) == "auto_cleared"
        assert classify_fraud(0.01) == "auto_cleared"
        assert classify_fraud(0.00) == "auto_cleared"

    def test_soft_flag_between_thresholds(self):
        assert classify_fraud(0.40) == "soft_flagged"
        assert classify_fraud(0.55) == "soft_flagged"
        assert classify_fraud(0.70) == "soft_flagged"

    def test_hard_flag_above_0_70(self):
        assert classify_fraud(0.71) == "hard_flagged"
        assert classify_fraud(1.00) == "hard_flagged"

    def test_high_risk_profile_tightens_thresholds(self):
        # auto_clear drops to 0.30 for high risk
        assert classify_fraud(0.35, risk_profile="high") == "soft_flagged"  # would be auto_clear normally
        assert classify_fraud(0.35, risk_profile="medium") == "auto_cleared"

    def test_high_risk_hard_flag_at_0_60(self):
        assert classify_fraud(0.61, risk_profile="high") == "hard_flagged"
        assert classify_fraud(0.61, risk_profile="medium") == "soft_flagged"

    def test_spec_example_auto_clear(self):
        # Spec: oracle=0.90, presence=1.0 → FS=0.06 → auto_clear
        fs = compute_fraud_score(0.90, 1.00)
        assert classify_fraud(fs) == "auto_cleared"
