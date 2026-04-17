"""models/common.py — Shared enums, base models, common types."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TriggerType(str, Enum):
    rain = "rain"
    flood = "flood"
    heat = "heat"
    aqi = "aqi"
    bandh = "bandh"
    platform_down = "platform_down"


class PlanType(str, Enum):
    basic = "basic"
    standard = "standard"
    pro = "pro"


class PolicyStatus(str, Enum):
    active = "active"
    paused = "paused"
    lapsed = "lapsed"
    cancelled = "cancelled"


class ClaimStatus(str, Enum):
    initiated = "initiated"
    evaluating = "evaluating"
    auto_cleared = "auto_cleared"
    soft_flagged = "soft_flagged"
    hard_flagged = "hard_flagged"
    manual_review = "manual_review"
    manual_approved = "manual_approved"
    manual_rejected = "manual_rejected"
    manual_adjusted = "manual_adjusted"
    cap_exhausted = "cap_exhausted"
    disputed = "disputed"
    paid = "paid"
    rejected = "rejected"


class PayoutType(str, Enum):
    initial = "initial"
    continuation = "continuation"
    provisional = "provisional"
    remainder = "remainder"
    goodwill = "goodwill"
    vov_reward = "vov_reward"
    premium_debit = "premium_debit"
    refund = "refund"


class PayoutStatus(str, Enum):
    initiated = "initiated"
    processing = "processing"
    success = "success"
    failed = "failed"
    reversed = "reversed"
    circuit_breaker_hold = "circuit_breaker_hold"


class TriggerStatus(str, Enum):
    detected = "detected"
    active = "active"
    resolving = "resolving"
    resolved = "resolved"
    cancelled = "cancelled"


class RiskProfile(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TierType(str, Enum):
    A = "A"
    B = "B"


class PlatformType(str, Enum):
    zepto = "zepto"
    blinkit = "blinkit"
    instamart = "instamart"


class LiquidityMode(str, Enum):
    normal = "normal"
    elevated = "elevated"
    cautious = "cautious"
    stressed = "stressed"
    emergency = "emergency"


class ShiftStatus(str, Enum):
    active = "active"
    idle = "idle"
    offline = "offline"


class BaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UUIDModel(BaseResponse):
    id: UUID


class TimestampedModel(UUIDModel):
    created_at: datetime
