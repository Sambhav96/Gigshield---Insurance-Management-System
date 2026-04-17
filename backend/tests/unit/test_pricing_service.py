"""tests/unit/test_pricing_service.py — Pricing formula unit tests."""
import pytest
from app.services.pricing_service import (
    compute_p_base,
    compute_lambda,
    compute_beta,
    compute_recent_trigger_factor,
    compute_p_final,
    compute_vulnerability_index,
    RISK_MULTIPLIERS,
)


class TestPBase:
    def test_standard_formula(self):
        # P_base = (vuln × income × coverage × 0.50) × 1.25
        p_base = compute_p_base(
            effective_income=700.0,
            coverage_pct=0.75,
            vulnerability_idx=0.50,
        )
        expected = (0.50 * 700.0 * 0.75 * 0.50) * 1.25
        assert abs(p_base - expected) < 0.01

    def test_higher_income_higher_premium(self):
        low  = compute_p_base(500.0, 0.75, 0.50)
        high = compute_p_base(1000.0, 0.75, 0.50)
        assert high > low

    def test_zero_vulnerability(self):
        p = compute_p_base(700.0, 0.75, 0.0)
        assert p == 0.0


class TestLambda:
    def test_floor_applied(self):
        lam = compute_lambda(active_policies_in_hub=0, hub_capacity=100, lambda_floor=1.0)
        assert lam == 1.0

    def test_surge_with_occupancy(self):
        lam = compute_lambda(active_policies_in_hub=100, hub_capacity=100, lambda_floor=1.0)
        # 1.0 + 100/100 = 2.0
        assert lam == 2.0

    def test_capped_at_2(self):
        lam = compute_lambda(active_policies_in_hub=500, hub_capacity=100)
        assert lam == 2.0

    def test_partial_occupancy(self):
        lam = compute_lambda(active_policies_in_hub=50, hub_capacity=100)
        assert lam == 1.5


class TestBeta:
    def test_zero_clean_weeks_no_discount(self):
        assert compute_beta(0) == 1.0

    def test_one_clean_week_5pct_off(self):
        assert compute_beta(1) == 0.95

    def test_four_clean_weeks_20pct_off(self):
        assert compute_beta(4) == 0.80

    def test_more_than_4_weeks_capped(self):
        # discount_weeks is capped at 4 in formula
        assert compute_beta(4) == compute_beta(8)

    def test_floor_at_80pct(self):
        assert compute_beta(10) >= 0.80


class TestRecentTriggerFactor:
    def test_no_events(self):
        assert compute_recent_trigger_factor(0) == 1.0

    def test_one_event_5pct_increase(self):
        assert abs(compute_recent_trigger_factor(1) - 1.05) < 0.001

    def test_capped_at_140pct(self):
        assert compute_recent_trigger_factor(100) == 1.40

    def test_cap_at_8_events(self):
        assert compute_recent_trigger_factor(8) == 1.40


class TestPFinal:
    def test_full_formula(self):
        p = compute_p_final(
            effective_income=700.0,
            coverage_pct=0.75,
            vulnerability_idx=0.50,
            city_multiplier=1.35,
            lambda_val=1.20,
            beta=0.95,
            risk_profile="medium",
            recent_trigger_factor=1.10,
        )
        p_base = compute_p_base(700.0, 0.75, 0.50)
        expected = p_base * 1.35 * 1.20 * 0.95 * 1.00 * 1.10
        assert abs(p - expected) < 0.01

    def test_high_risk_more_expensive(self):
        base_args = dict(
            effective_income=700.0, coverage_pct=0.75, vulnerability_idx=0.50,
            city_multiplier=1.35, lambda_val=1.20, beta=1.0, recent_trigger_factor=1.0,
        )
        low  = compute_p_final(**base_args, risk_profile="low")
        high = compute_p_final(**base_args, risk_profile="high")
        assert high > low

    def test_discount_reduces_premium(self):
        args = dict(
            effective_income=700.0, coverage_pct=0.75, vulnerability_idx=0.50,
            city_multiplier=1.35, lambda_val=1.0, recent_trigger_factor=1.0, risk_profile="medium",
        )
        no_disc = compute_p_final(**args, beta=1.0)
        with_disc = compute_p_final(**args, beta=0.80)
        assert with_disc < no_disc


class TestVulnerabilityIndex:
    def test_zero_risk(self):
        assert compute_vulnerability_index(0) == 0.0

    def test_max_risk(self):
        assert compute_vulnerability_index(100) == 1.0

    def test_medium(self):
        assert compute_vulnerability_index(50) == 0.50
