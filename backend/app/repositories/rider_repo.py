"""repositories/rider_repo.py — All DB operations for riders."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import asyncpg

from app.utils.crypto import sha256_hash
from app.utils.mu_table import get_city_median_income, get_plan_coverage


async def get_rider_by_id(conn: asyncpg.Connection, rider_id: str) -> Optional[dict]:
    row = await conn.fetchrow("SELECT * FROM riders WHERE id = $1", uuid.UUID(rider_id))
    return dict(row) if row else None


async def get_rider_by_phone(conn: asyncpg.Connection, phone: str) -> Optional[dict]:
    row = await conn.fetchrow("SELECT * FROM riders WHERE phone = $1", phone)
    return dict(row) if row else None


async def create_rider(
    conn: asyncpg.Connection,
    name: str,
    phone: str,
    platform: str,
    city: str,
    declared_income: float,
    hub_id: str,
    device_fingerprint: Optional[str] = None,
    enrollment_ip_prefix: Optional[str] = None,
) -> str:
    from app.utils.mu_table import get_city_median_income

    effective_income = min(declared_income, get_city_median_income(city))
    tier = "A" if effective_income > 700 else "B"

    rider_id = await conn.fetchval(
        """
        INSERT INTO riders (
            name, phone, platform, city, hub_id,
            declared_income, effective_income, tier,
            risk_score, risk_profile, phone_verified,
            device_fingerprint, enrollment_ip_prefix,
            experiment_group_id
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,50,'medium',false,$9,$10,'control')
        RETURNING id
        """,
        name, phone, platform, city, uuid.UUID(hub_id),
        declared_income, effective_income, tier,
        device_fingerprint, enrollment_ip_prefix,
    )
    return str(rider_id)


async def update_rider_phone_verified(conn: asyncpg.Connection, rider_id: str) -> None:
    await conn.execute(
        "UPDATE riders SET phone_verified = true WHERE id = $1", uuid.UUID(rider_id)
    )


async def update_effective_income(
    conn: asyncpg.Connection, rider_id: str, effective_income: float
) -> None:
    tier = "A" if effective_income > 700 else "B"
    await conn.execute(
        """
        UPDATE riders
        SET effective_income = $1, tier = $2, income_verified_at = NOW()
        WHERE id = $3
        """,
        effective_income, tier, uuid.UUID(rider_id),
    )


async def update_risk_score(
    conn: asyncpg.Connection,
    rider_id: str,
    risk_score: int,
    risk_profile: str,
) -> None:
    await conn.execute(
        "UPDATE riders SET risk_score = $1, risk_profile = $2 WHERE id = $3",
        risk_score, risk_profile, uuid.UUID(rider_id),
    )


async def store_aadhaar_hash(conn: asyncpg.Connection, rider_id: str, aadhaar: str) -> None:
    """Never store raw Aadhaar — SHA-256 only."""
    await conn.execute(
        "UPDATE riders SET aadhaar_hash = $1 WHERE id = $2",
        sha256_hash(aadhaar), uuid.UUID(rider_id),
    )


async def store_pan_hash(conn: asyncpg.Connection, rider_id: str, pan: str) -> None:
    await conn.execute(
        "UPDATE riders SET pan_hash = $1 WHERE id = $2",
        sha256_hash(pan.upper()), uuid.UUID(rider_id),
    )


async def get_rider_by_email(conn: asyncpg.Connection, email: str) -> Optional[dict]:
    """Look up a rider by email address (for email+password login)."""
    row = await conn.fetchrow("SELECT * FROM riders WHERE email = $1", email)
    return dict(row) if row else None
