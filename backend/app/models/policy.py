"""models/policy.py — Policy request/response models."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.common import PlanType, PolicyStatus, BaseResponse


class PolicyCreate(BaseModel):
    plan: PlanType
    hub_id: UUID
    razorpay_fund_account_id: str


class PolicyOut(BaseResponse):
    id: UUID
    rider_id: UUID
    hub_id: UUID
    plan: PlanType
    status: PolicyStatus
    coverage_pct: float
    plan_cap_multiplier: int
    weekly_premium: float
    discount_weeks: int
    pause_count_qtr: int
    weekly_payout_used: float
    week_start_date: date
    activated_at: datetime
    created_at: datetime


class PolicyStatusUpdate(BaseModel):
    action: str = Field(..., pattern="^(pause|resume|cancel)$")
    reason: str = Field(..., min_length=3)


class PremiumQuoteResponse(BaseModel):
    plan: str
    daily_income: float
    p_base: float
    city_multiplier: float
    lambda_val: float
    beta: float
    risk_multiplier: float
    recent_trigger_factor: float
    p_final: float
    discount_weeks: int
    weekly_cap: float
    coverage_pct: float
    triggers_covered: list[str]
    expected_payout_example: dict


class PolicyPauseResponse(BaseModel):
    new_status: str
    pause_count_qtr: int
    pauses_remaining: int
    next_debit_date: date | None


class PolicyCancelResponse(BaseModel):
    new_status: str
    refund_amount: float
    refund_eta: str
