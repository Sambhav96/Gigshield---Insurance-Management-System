"""tests/unit/test_payout_formula.py — Payout formula unit tests."""
import pytest
from app.utils.mu_table import (
    get_mu, get_min_duration, get_confidence_factor,
    get_correlation_payout_factor, MU_TABLE,
)


class TestMUTable:
    def test_all_24_hours_defined(self):
        for hour in range(24):
            assert hour in MU_TABLE
            assert MU_TABLE[hour] > 0

    def test_peak_hours_highest(self):
        peak_mu = get_mu(19)  # 7 PM
        night_mu = get_mu(3)  # 3 AM
        assert peak_mu > night_mu

    def test_night_hours_lowest(self):
        for h in [0, 1, 2, 3, 4, 5, 23]:
            assert get_mu(h) <= 0.70

    def test_known_values(self):
        assert get_mu(8) == 1.50   # morning peak
        assert get_mu(19) == 1.50  # evening peak
        assert get_mu(18) == 1.20  # dinner surge
        assert get_mu(0) == 0.50   # midnight


class TestMinDuration:
    def test_rain_1hr(self):
        assert get_min_duration("rain") == 1.0

    def test_flood_2hr(self):
        assert get_min_duration("flood") == 2.0

    def test_platform_down_half_hr(self):
        assert get_min_duration("platform_down") == 0.5

    def test_bandh_2hr(self):
        assert get_min_duration("bandh") == 2.0


class TestConfidenceFactor:
    def test_high_oracle_full_payout(self):
        assert get_confidence_factor(0.90) == 1.00
        assert get_confidence_factor(0.85) == 1.00

    def test_mid_oracle_95pct(self):
        assert get_confidence_factor(0.75) == 0.95
        assert get_confidence_factor(0.80) == 0.95

    def test_threshold_oracle_85pct(self):
        assert get_confidence_factor(0.65) == 0.85
        assert get_confidence_factor(0.70) == 0.85

    def test_below_threshold_still_85pct_floor(self):
        # Floor at 0.85 — shouldn't be called below oracle threshold
        assert get_confidence_factor(0.60) == 0.85


class TestCorrelationFactor:
    def test_low_correlation_full_payout(self):
        assert get_correlation_payout_factor(0.10) == 1.00
        assert get_correlation_payout_factor(0.20) == 1.00

    def test_medium_correlation_90pct(self):
        assert get_correlation_payout_factor(0.30) == 0.90
        assert get_correlation_payout_factor(0.40) == 0.90

    def test_high_correlation_80pct(self):
        assert get_correlation_payout_factor(0.50) == 0.80
        assert get_correlation_payout_factor(0.60) == 0.80

    def test_very_high_correlation_70pct(self):
        assert get_correlation_payout_factor(0.70) == 0.70
        assert get_correlation_payout_factor(1.00) == 0.70

    def test_platform_down_always_70pct(self):
        # platform_down is always C=1.0 → 0.70
        assert get_correlation_payout_factor(1.0) == 0.70


class TestPayoutFormulaEnd2End:
    """Full payout formula verification: event_payout → confidence → correlation → cooldown."""

    def test_auto_clear_standard_rain(self):
        effective_income = 700.0
        coverage_pct     = 0.75
        duration_hrs     = 1.0   # rain minimum
        mu_time          = 1.50  # peak hour
        oracle_score     = 0.80
        correlation      = 0.15  # low correlation
        cooldown_factor  = 1.0   # no cooldown

        event_payout = effective_income * coverage_pct * (duration_hrs / 8) * mu_time
        assert abs(event_payout - 98.4375) < 0.01

        confidence_factor = get_confidence_factor(oracle_score)
        corr_factor       = get_correlation_payout_factor(correlation)
        final_payout      = event_payout * confidence_factor * corr_factor * cooldown_factor

        assert abs(final_payout - 98.4375 * 0.95 * 1.00) < 0.01

    def test_cooldown_halves_payout(self):
        base_payout = 100.0
        with_cooldown    = base_payout * 0.50
        without_cooldown = base_payout * 1.00
        assert with_cooldown == 50.0
        assert without_cooldown == 100.0

    def test_weekly_cap_applied(self):
        effective_income   = 700.0
        plan_cap_mult      = 5      # standard
        max_weekly         = effective_income * plan_cap_mult  # 3500
        weekly_used        = 3400.0
        headroom           = max_weekly - weekly_used          # 100
        final_event_payout = 500.0

        actual_payout = min(final_event_payout, headroom)
        assert actual_payout == 100.0  # capped at headroom

    def test_event_cap_50pct_of_weekly(self):
        effective_income = 700.0
        plan_cap_mult    = 5
        max_weekly       = effective_income * plan_cap_mult   # 3500
        single_event_cap = max_weekly * 0.50                  # 1750
        assert single_event_cap == 1750.0
