"""tests/unit/test_auth_fixes.py — Tests for auth refactor (Twilio removal, new endpoints)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


# ── Phone normalisation ────────────────────────────────────────────────────────
def test_normalize_phone_adds_country_code():
    from app.api.v1.auth import _normalize_phone
    assert _normalize_phone("9876543210") == "+919876543210"
    assert _normalize_phone("+919876543210") == "+919876543210"
    assert _normalize_phone(" 9876543210 ") == "+919876543210"


def test_normalize_phone_strips_leading_zero():
    from app.api.v1.auth import _normalize_phone
    assert _normalize_phone("09876543210") == "+919876543210"


def test_generate_otp_is_6_digits():
    from app.api.v1.auth import _generate_otp
    otp = _generate_otp()
    assert len(otp) == 6
    assert otp.isdigit()


# ── Supabase client: returns None for placeholder config ──────────────────────
def test_get_supabase_client_returns_none_for_placeholder():
    from app.api.v1.auth import _get_supabase_client
    with patch("app.config.get_settings") as mock_settings:
        mock_settings.return_value.supabase_url = "https://placeholder.supabase.co"
        client = _get_supabase_client()
        assert client is None


# ── send_otp: fallback to Redis when Supabase not configured ──────────────────
@pytest.mark.asyncio
async def test_send_otp_redis_fallback_when_supabase_not_configured():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with patch("app.api.v1.auth._get_supabase_client", return_value=None):
        from app.api.v1.auth import send_otp, SendOTPRequest
        result = await send_otp(SendOTPRequest(phone="9876543210"), redis=mock_redis)

    assert result["otp_sent"] is True
    assert result["provider"] == "redis_dev"
    mock_redis.set.assert_called_once()


# ── verify_otp: invalid OTP raises 401 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_verify_otp_invalid_raises_401():
    from fastapi import HTTPException
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="123456")
    mock_conn = AsyncMock()

    with patch("app.api.v1.auth._get_supabase_client", return_value=None):
        from app.api.v1.auth import verify_otp, VerifyOTPRequest
        with pytest.raises(HTTPException) as exc_info:
            await verify_otp(
                VerifyOTPRequest(phone="9876543210", otp="999999"),
                conn=mock_conn,
                redis=mock_redis,
            )
        assert exc_info.value.status_code == 401


# ── verify_otp: correct OTP returns token for existing rider ──────────────────
@pytest.mark.asyncio
async def test_verify_otp_success_existing_rider():
    import uuid
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="123456")
    mock_redis.delete = AsyncMock(return_value=1)
    mock_conn = AsyncMock()

    rider_id = uuid.uuid4()
    mock_conn.fetchrow = AsyncMock(return_value={"id": rider_id, "phone": "+919876543210"})
    mock_conn.execute = AsyncMock()

    with patch("app.api.v1.auth._get_supabase_client", return_value=None):
        with patch("app.api.v1.auth.create_access_token", return_value="test_jwt"):
            from app.api.v1.auth import verify_otp, VerifyOTPRequest
            result = await verify_otp(
                VerifyOTPRequest(phone="9876543210", otp="123456"),
                conn=mock_conn,
                redis=mock_redis,
            )

    assert result["access_token"] == "test_jwt"
    assert result["is_new_rider"] is False


# ── email/password login: wrong password raises 401 ──────────────────────────
@pytest.mark.asyncio
async def test_rider_login_wrong_password():
    from fastapi import HTTPException
    from app.core.security import hash_password
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "id": "some-uuid",
        "email": "rider@test.com",
        "password_hash": hash_password("correct_password"),
    })

    from app.api.v1.auth import rider_login, RiderLoginRequest
    with pytest.raises(HTTPException) as exc_info:
        await rider_login(
            RiderLoginRequest(email="rider@test.com", password="wrong_password"),
            conn=mock_conn,
        )
    assert exc_info.value.status_code == 401


# ── email/password login: correct password returns token ─────────────────────
@pytest.mark.asyncio
async def test_rider_login_correct_password():
    import uuid
    from app.core.security import hash_password
    rider_id = uuid.uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "id": rider_id,
        "email": "rider@test.com",
        "password_hash": hash_password("correct_password"),
    })

    with patch("app.api.v1.auth.create_access_token", return_value="test_jwt"):
        from app.api.v1.auth import rider_login, RiderLoginRequest
        result = await rider_login(
            RiderLoginRequest(email="rider@test.com", password="correct_password"),
            conn=mock_conn,
        )
    assert result["access_token"] == "test_jwt"


# ── register: duplicate email raises 409 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_rider_register_duplicate_email():
    from fastapi import HTTPException
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "existing-id", "email": "dup@test.com"})

    with patch("app.api.v1.auth._get_supabase_client", return_value=None):
        from app.api.v1.auth import rider_register, RiderRegisterRequest
        with pytest.raises(HTTPException) as exc_info:
            await rider_register(
                RiderRegisterRequest(email="dup@test.com", password="pass123"),
                conn=mock_conn,
            )
        assert exc_info.value.status_code == 409


# ── admin login: correct credentials return token ─────────────────────────────
@pytest.mark.asyncio
async def test_admin_login_success():
    import uuid
    from app.core.security import hash_password
    admin_id = uuid.uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={
        "id": admin_id,
        "username": "admin",
        "password_hash": hash_password("admin123"),
    })

    with patch("app.api.v1.auth.create_access_token", return_value="admin_jwt"):
        from app.api.v1.auth import admin_login, AdminLoginRequest
        result = await admin_login(
            AdminLoginRequest(username="admin", password="admin123"),
            conn=mock_conn,
        )
    assert result["access_token"] == "admin_jwt"


# ── Google exchange: no supabase configured returns 503 ──────────────────────
@pytest.mark.asyncio
async def test_google_exchange_no_supabase_returns_503():
    from fastapi import HTTPException
    mock_conn = AsyncMock()

    with patch("app.api.v1.auth._get_supabase_client", return_value=None):
        from app.api.v1.auth import google_oauth_exchange, GoogleExchangeRequest
        with pytest.raises(HTTPException) as exc_info:
            await google_oauth_exchange(
                GoogleExchangeRequest(supabase_access_token="some_token"),
                conn=mock_conn,
            )
        assert exc_info.value.status_code == 503


# ── Notification service: send_sms is a no-op (Twilio removed) ───────────────
def test_send_sms_is_noop():
    from app.services.notification_service import send_sms
    result = send_sms("+919876543210", "Test message")
    assert result is False  # no-op returns False


def test_publish_notification_does_not_call_twilio():
    """Ensure publish_notification doesn't import or call Twilio."""
    with patch("app.services.notification_service.get_sync_redis") as mock_redis_factory:
        mock_redis = MagicMock()
        mock_redis_factory.return_value = mock_redis
        from app.services.notification_service import publish_notification
        publish_notification("rider-123", "payout_success", {"amount": 150})
        mock_redis.publish.assert_called_once()
        # Verify no twilio import attempted
        import sys
        assert "twilio" not in str(sys.modules)
