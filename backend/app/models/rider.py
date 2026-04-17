"""models/rider.py — Rider request/response models."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
import re

from app.models.common import TierType, RiskProfile, PlatformType, BaseResponse


class RiderCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    phone: str
    platform: PlatformType
    city: str
    declared_income: float = Field(..., gt=0, le=5000)
    hub_id: UUID

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[6-9]\d{9}$", cleaned.replace("+91", "")):
            raise ValueError("Invalid Indian mobile number")
        return cleaned


class RiderOut(BaseResponse):
    id: UUID
    name: str
    phone: str
    platform: str
    city: str
    declared_income: float
    effective_income: float
    tier: TierType
    risk_score: int
    risk_profile: RiskProfile
    phone_verified: bool
    created_at: datetime


class IncomeUpdateRequest(BaseModel):
    new_declared_income: float = Field(..., gt=0, le=5000)
    reason: str = Field(..., min_length=5)


class RiderProfile(RiderOut):
    telemetry_inferred_income: float | None = None
    income_verified_at: datetime | None = None
    experiment_group_id: str
    hub_id: UUID | None = None
