"""tests/unit/test_discount_engine.py — Discount weeks and beta tests."""
import pytest
from app.services.discount_service import compute_beta_from_discount, MAX_DISCOUNT_WEEKS, DISCOUNT_PER_WEEK


class TestDiscountEngine:
    def test_zero_clean_weeks_full_premium(self):
        beta = compute_beta_from_discount(0)
        assert beta == 1.0

    def test_one_week_5pct_discount(self):
        beta = compute_beta_from_discount(1)
        assert abs(beta - 0.95) < 0.001

    def test_two_weeks_10pct_discount(self):
        beta = compute_beta_from_discount(2)
        assert abs(beta - 0.90) < 0.001

    def test_four_weeks_max_20pct_discount(self):
        beta = compute_beta_from_discount(4)
        assert abs(beta - 0.80) < 0.001

    def test_exceeding_max_capped(self):
        # Any more than MAX_DISCOUNT_WEEKS = same as MAX
        assert compute_beta_from_discount(5) == compute_beta_from_discount(4)
        assert compute_beta_from_discount(10) == compute_beta_from_discount(4)

    def test_floor_at_80pct(self):
        for weeks in range(MAX_DISCOUNT_WEEKS + 1):
            beta = compute_beta_from_discount(weeks)
            assert beta >= 0.80

    def test_discount_per_week_is_5pct(self):
        assert DISCOUNT_PER_WEEK == 0.05

    def test_max_is_4_weeks(self):
        assert MAX_DISCOUNT_WEEKS == 4
