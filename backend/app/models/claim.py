"""models/claim.py — Claim, payout, trigger models."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID
from typing import Any

from pydantic import BaseModel, Field

from app.models.common import (
    ClaimStatus, PayoutType, PayoutStatus, TriggerType, TriggerStatus, BaseResponse
)


class ClaimOut(BaseResponse):
    id: UUID
    rider_id: UUID
    policy_id: UUID
    trigger_id: UUID
    idempotency_key: str
    status: ClaimStatus
    fraud_score: float | None
    oracle_confidence: float | None
    presence_confidence: float | None
    event_payout: float | None
    actual_payout: float | None
    explanation_text: str | None
    admin_trace: dict | None
    initiated_at: datetime
    cleared_at: datetime | None
    paid_at: datetime | None


class ClaimProofResponse(BaseModel):
    claim_id: UUID
    trigger_type: str
    trigger_description: str
    oracle_score: float
    oracle_weight_config: dict
    signal_breakdown: dict
    fraud_score: float
    presence_confidence: float
    oracle_confidence: float
    payout_amount: float
    payout_breakdown: dict
    api_sources_used: list[dict]
    dispute_deadline: datetime | None


class PayoutOut(BaseResponse):
    id: UUID
    claim_id: UUID | None
    rider_id: UUID
    policy_id: UUID
    amount: float
    payout_type: PayoutType
    razorpay_ref: str | None
    razorpay_status: PayoutStatus
    idempotency_key: str
    released_at: datetime


class TriggerOut(BaseResponse):
    id: UUID
    trigger_type: TriggerType
    h3_index: str
    hub_id: UUID | None
    oracle_score: float | None
    status: TriggerStatus
    cooldown_active: bool
    cooldown_payout_factor: float
    correlation_factor: float
    vov_zone_certified: bool
    triggered_at: datetime
    resolved_at: datetime | None


class DisputeCreate(BaseModel):
    claim_id: UUID
    reason_text: str = Field(..., min_length=10, max_length=2000)


class DisputeOut(BaseResponse):
    id: UUID
    claim_id: UUID
    rider_id: UUID
    reason_text: str
    status: str
    sla_deadline: datetime
    created_at: datetime


class LiveDashboardResponse(BaseModel):
    active_trigger: dict | None
    weekly_remaining: float
    expected_payout_now: float
    mu_label: str
    policy_status: str
    discount_weeks: int
    next_debit: str
