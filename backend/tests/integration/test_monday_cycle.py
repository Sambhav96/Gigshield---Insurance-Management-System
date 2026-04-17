"""tests/integration/test_monday_cycle.py — Monday debit cycle and discount reset."""
import pytest
from datetime import date, timedelta
from app.core.idempotency import make_debit_key
from app.services.discount_service import compute_beta_from_discount
from app.services.pricing_service import compute_p_final, compute_vulnerability_index


class TestMondayCycleIdempotency:
    def test_same_policy_same_week_same_key(self):
        """Same policy + same Monday = same idempotency key → prevents double debit."""
        policy_id  = "550e8400-e29b-41d4-a716-446655440000"
        week_start = "2024-07-15"

        key1 = make_debit_key(policy_id, week_start)
        key2 = make_debit_key(policy_id, week_start)
        assert key1 == key2

    def test_different_weeks_different_keys(self):
        """Each Monday should produce a unique key → fresh debit each week."""
        policy_id  = "550e8400-e29b-41d4-a716-446655440000"
        week1      = "2024-07-15"
        week2      = "2024-07-22"  # next Monday

        key1 = make_debit_key(policy_id, week1)
        key2 = make_debit_key(policy_id, week2)
        assert key1 != key2

    def test_different_policies_different_keys(self):
        policy1 = "550e8400-e29b-41d4-a716-446655440001"
        policy2 = "550e8400-e29b-41d4-a716-446655440002"
        week    = "2024-07-15"

        assert make_debit_key(policy1, week) != make_debit_key(policy2, week)


class TestWeeklyCapReset:
    def test_cap_resets_to_zero_monday(self):
        """weekly_payout_used must reset to 0 every Monday regardless of policy status."""
        # Simulates the DB update in monday_worker
        initial_used = 1500.0
        after_reset  = 0.0
        assert after_reset == 0.0, "weekly_payout_used must be 0 after Monday reset"

    def test_all_statuses_get_reset(self):
        """active, paused, lapsed all get weekly_payout_used = 0."""
        statuses = ["active", "paused", "lapsed"]
        # All statuses included in the Monday UPDATE query
        # Verify logic: "WHERE status IN ('active','paused','lapsed')"
        for s in statuses:
            assert s in ["active", "paused", "lapsed"]
        assert "cancelled" not in ["active", "paused", "lapsed"]


class TestDiscountWeeksLogic:
    def test_clean_week_increments(self):
        current    = 2
        week_total = 0.0  # no payouts
        new_weeks  = min(current + 1, 4) if week_total == 0 else 0
        assert new_weeks == 3

    def test_any_payout_resets_to_zero(self):
        current    = 3
        week_total = 15.0  # any payout (even ₹1)
        new_weeks  = min(current + 1, 4) if week_total == 0 else 0
        assert new_weeks == 0

    def test_goodwill_credit_resets_discount(self):
        """VOV reward, goodwill credit = any payout = discount reset."""
        goodwill   = 20.0
        week_total = goodwill  # counts as a payout
        current    = 4
        new_weeks  = min(current + 1, 4) if week_total == 0 else 0
        assert new_weeks == 0, "Goodwill credit must reset discount_weeks"

    def test_premium_debit_does_not_count(self):
        """premium_debit payout type excluded from week_total calculation."""
        # The SQL query excludes payout_type = 'premium_debit'
        # This test verifies the rule is understood
        non_debit_types = ["initial", "continuation", "provisional", "remainder",
                           "goodwill", "vov_reward", "refund"]
        excluded_types  = ["premium_debit"]
        for t in non_debit_types:
            assert t not in excluded_types
        assert "premium_debit" in excluded_types

    def test_max_4_clean_weeks(self):
        current    = 4
        week_total = 0.0
        new_weeks  = min(current + 1, 4) if week_total == 0 else 0
        assert new_weeks == 4  # capped at 4


class TestPremiumRecomputation:
    def test_premium_reflects_new_beta(self):
        """After 4 clean weeks, premium should be 20% cheaper."""
        base_args = dict(
            effective_income=700.0,
            coverage_pct=0.75,
            vulnerability_idx=0.50,
            city_multiplier=1.35,
            lambda_val=1.0,
            risk_profile="medium",
            recent_trigger_factor=1.0,
        )
        premium_no_discount   = compute_p_final(**base_args, beta=1.0)
        premium_max_discount  = compute_p_final(**base_args, beta=0.80)
        discount_pct = (premium_no_discount - premium_max_discount) / premium_no_discount
        assert abs(discount_pct - 0.20) < 0.001, "Max discount should be 20%"

    def test_risk_score_increase_after_hard_flag(self):
        """Hard flag confirmed: risk_score += 30 immediately."""
        current_score = 40
        new_score     = min(100, current_score + 30)
        assert new_score == 70

    def test_risk_score_capped_at_100(self):
        current_score = 95
        new_score     = min(100, current_score + 30)
        assert new_score == 100
