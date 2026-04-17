"""tests/conftest.py — Pytest fixtures for unit and integration tests."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ── Event loop ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Mock DB connection ────────────────────────────────────────────────────────
@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.fetch    = AsyncMock(return_value=[])
    conn.execute  = AsyncMock(return_value="UPDATE 1")
    conn.transaction = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=None),
        __aexit__=AsyncMock(return_value=False),
    ))
    return conn


# ── Mock Redis ────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_redis():
    redis = MagicMock()
    redis.get    = MagicMock(return_value=None)
    redis.set    = MagicMock(return_value=True)
    redis.delete = MagicMock(return_value=1)
    redis.zadd   = MagicMock(return_value=1)
    return redis


# ── Sample data fixtures ──────────────────────────────────────────────────────
@pytest.fixture
def sample_rider():
    return {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "name": "Ravi Kumar",
        "phone": "+919876543210",
        "platform": "zepto",
        "city": "Mumbai",
        "declared_income": 800.0,
        "effective_income": 800.0,
        "telemetry_inferred_income": None,
        "tier": "A",
        "risk_score": 30,
        "risk_profile": "low",
        "phone_verified": True,
        "experiment_group_id": "control",
        "hub_id": "660e8400-e29b-41d4-a716-446655440001",
    }


@pytest.fixture
def sample_policy():
    return {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "rider_id": "550e8400-e29b-41d4-a716-446655440000",
        "hub_id": "660e8400-e29b-41d4-a716-446655440001",
        "plan": "standard",
        "status": "active",
        "coverage_pct": 0.75,
        "plan_cap_multiplier": 5,
        "weekly_premium": 49.0,
        "discount_weeks": 2,
        "pause_count_qtr": 0,
        "weekly_payout_used": 0.0,
        "week_start_date": "2024-01-01",
        "razorpay_mandate_id": "mandate_test_123",
        "razorpay_fund_account_id": "fa_test_456",
        "experiment_group_id": "control",
    }


@pytest.fixture
def sample_hub():
    return {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "name": "Zepto Andheri West Hub",
        "platform": "zepto",
        "city": "Mumbai",
        "latitude": 19.1136,
        "longitude": 72.8697,
        "h3_index_res9": "8b5225c50d4ffff",
        "h3_index_res8": "8a5225c50d7ffff",
        "radius_km": 2.0,
        "capacity": 150,
        "city_multiplier": 1.35,
        "drainage_index": 0.3,
        "rain_threshold_mm": 35.0,
    }


@pytest.fixture
def sample_trigger():
    return {
        "id": "880e8400-e29b-41d4-a716-446655440003",
        "trigger_type": "rain",
        "h3_index": "8b5225c50d4ffff",
        "hub_id": "660e8400-e29b-41d4-a716-446655440001",
        "oracle_score": 0.78,
        "weather_score": 0.80,
        "traffic_score": None,
        "satellite_score": None,
        "status": "active",
        "cold_start_mode": False,
        "cooldown_active": False,
        "cooldown_payout_factor": 1.0,
        "correlation_factor": 1.0,
        "triggered_at": datetime(2024, 7, 15, 14, 30, tzinfo=timezone.utc),
        "resolved_at": None,
        "weight_config": {"weather": 1.0},
    }


@pytest.fixture
def sample_pings():
    """3 recent GPS pings within 2km of the hub."""
    return [
        {
            "latitude": 19.1130, "longitude": 72.8690,
            "speed_kmh": 15.0, "session_active": True,
            "platform_status": "available",
            "recorded_at": datetime(2024, 7, 15, 14, 0, tzinfo=timezone.utc),
            "h3_index_res9": "8b5225c50d4ffff",
        },
        {
            "latitude": 19.1140, "longitude": 72.8700,
            "speed_kmh": 12.0, "session_active": True,
            "platform_status": "on_delivery",
            "recorded_at": datetime(2024, 7, 15, 14, 15, tzinfo=timezone.utc),
            "h3_index_res9": "8b5225c50d4ffff",
        },
        {
            "latitude": 19.1135, "longitude": 72.8695,
            "speed_kmh": 8.0, "session_active": True,
            "platform_status": "available",
            "recorded_at": datetime(2024, 7, 15, 14, 25, tzinfo=timezone.utc),
            "h3_index_res9": "8b5225c50d4ffff",
        },
    ]
