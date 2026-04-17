"""api/v1/auth.py — Auth endpoints: Supabase Phone OTP, Email/Password, Google OAuth, Admin login.

Changes:
  - Removed Twilio SMS dependency entirely
  - Phone OTP routed through Supabase Auth (their built-in Twilio at no cost)
  - Redis OTP fallback for local dev when Supabase credentials are placeholders
  - Added email+password register/login endpoints
  - Added Google OAuth exchange endpoint (frontend-driven via Supabase JS client)
  - Admin login unchanged (bcrypt via admin_users table)
"""
from __future__ import annotations

import random
import string
from datetime import timedelta
from typing import Optional

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.core.database import get_db_connection
from app.core.redis_client import get_async_redis
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.rider_repo import get_rider_by_phone, get_rider_by_email
from app.utils.mu_table import get_city_median_income

router = APIRouter(prefix="/auth", tags=["auth"])
log = structlog.get_logger()

OTP_TTL_SECONDS = 120
OTP_PREFIX = "otp:"


# ─── Models ───────────────────────────────────────────────────────────────────

class SendOTPRequest(BaseModel):
    phone: str


class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str


class RiderRegisterRequest(BaseModel):
    email: str
    password: str
    phone: Optional[str] = None
    name: Optional[str] = None
    declared_income: Optional[float] = 500.0
    city: Optional[str] = "Mumbai"
    # FIX #8: platform was hardcoded as 'zepto' in INSERT — add it to the model
    # so riders can correctly identify their platform at registration.
    platform: Optional[str] = "zepto"


class RiderLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class HubLoginRequest(BaseModel):
    hub_id: Optional[str] = None
    username: Optional[str] = None
    password: str

    @model_validator(mode="after")
    def ensure_identifier(self):
        if not (self.hub_id or self.username):
            raise ValueError("Either hub_id or username is required")
        return self


class GoogleExchangeRequest(BaseModel):
    """Exchange a Supabase access token (after Google OAuth on frontend) for a GigShield JWT."""
    supabase_access_token: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+91"):
        phone = "+91" + phone.lstrip("0")
    return phone


def _generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _get_supabase_client():
    """
    Return Supabase anon client for user-facing auth flows (respects RLS).
    Returns None if credentials are still placeholders (dev mode fallback).
    FIX #7: Uses anon key (not service role key) to respect Row-Level Security.
    """
    from app.config import get_settings
    settings = get_settings()
    if settings.supabase_url == "https://placeholder.supabase.co":
        return None
    try:
        from app.core.database import get_supabase_anon
        return get_supabase_anon()
    except Exception as exc:
        log.warning("supabase_anon_client_init_failed", error=str(exc))
        return None


# ─── Phone OTP via Supabase Auth (no direct Twilio cost) ──────────────────────

@router.post("/send-otp")
async def send_otp(
    body: SendOTPRequest,
    redis=Depends(lambda: get_async_redis()),
):
    """
    Send phone OTP. Uses Supabase Auth (their built-in Twilio, free for you).
    Falls back to Redis OTP logged to console for local dev.
    """
    phone = _normalize_phone(body.phone)
    supabase = _get_supabase_client()

    if supabase:
        try:
            supabase.auth.sign_in_with_otp({"phone": phone})
            log.info("otp_sent_via_supabase", phone=phone[:6] + "****")
            return {"otp_sent": True, "expires_in": OTP_TTL_SECONDS, "provider": "supabase"}
        except Exception as exc:
            log.warning("supabase_otp_failed_using_dev_fallback", error=str(exc))

    # Dev fallback: store in Redis, log OTP
    otp = _generate_otp()
    await redis.set(f"{OTP_PREFIX}{phone}", otp, ex=OTP_TTL_SECONDS)
    log.info("otp_generated_dev_fallback", phone=phone[:6] + "****", otp=otp)
    return {"otp_sent": True, "expires_in": OTP_TTL_SECONDS, "provider": "redis_dev"}


@router.post("/verify-otp")
async def verify_otp(
    body: VerifyOTPRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
    redis=Depends(lambda: get_async_redis()),
):
    """Verify phone OTP via Supabase Auth or Redis fallback."""
    phone = _normalize_phone(body.phone)
    supabase = _get_supabase_client()

    supabase_user_id: Optional[str] = None

    if supabase:
        try:
            session = supabase.auth.verify_otp({"phone": phone, "token": body.otp, "type": "sms"})
            if not session or not session.user:
                raise HTTPException(status_code=401, detail="Invalid or expired OTP")
            supabase_user_id = str(session.user.id)
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("supabase_verify_failed_using_redis_fallback", error=str(exc))
            # fall through to Redis check

    if not supabase_user_id:
        stored_otp = await redis.get(f"{OTP_PREFIX}{phone}")
        if not stored_otp or stored_otp != body.otp:
            raise HTTPException(status_code=401, detail="Invalid or expired OTP")
        await redis.delete(f"{OTP_PREFIX}{phone}")

    return await _complete_phone_login(conn, phone, supabase_user_id)


async def _complete_phone_login(
    conn: asyncpg.Connection, phone: str, supabase_user_id: Optional[str]
) -> dict:
    rider = await get_rider_by_phone(conn, phone)
    if not rider:
        token = create_access_token(
            {"sub": supabase_user_id or phone, "role": "new_rider", "phone": phone},
            expires_delta=timedelta(minutes=30),
        )
        return {"access_token": token, "is_new_rider": True, "rider_id": None}

    await conn.execute("UPDATE riders SET phone_verified = true WHERE id = $1", rider["id"])
    token = create_access_token({"sub": str(rider["id"]), "role": "rider", "phone": phone})
    log.info("rider_authenticated_phone", rider_id=str(rider["id"]))
    return {"access_token": token, "rider_id": str(rider["id"]), "is_new_rider": False}


# ─── Email / Password ──────────────────────────────────────────────────────────

@router.post("/register")
async def rider_register(
    body: RiderRegisterRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """Register a new rider with email + password."""
    existing = await get_rider_by_email(conn, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    normalized_phone = _normalize_phone(body.phone) if body.phone else None
    if normalized_phone:
        existing_phone = await get_rider_by_phone(conn, normalized_phone)
        if existing_phone:
            raise HTTPException(status_code=409, detail="Phone already registered")

    supabase_user_id: Optional[str] = None
    supabase = _get_supabase_client()
    if supabase:
        try:
            result = supabase.auth.sign_up({"email": body.email, "password": body.password})
            if result and result.user:
                supabase_user_id = str(result.user.id)
        except Exception as exc:
            log.warning("supabase_signup_failed_continuing_local", error=str(exc))

    password_hash = hash_password(body.password)
    _city_median = get_city_median_income(body.city or "Mumbai")
    _effective_income = round(min(body.declared_income or 500.0, _city_median), 2)
    log.info(
        "rider_income_bounded",
        declared=body.declared_income,
        city_median=_city_median,
        effective=_effective_income,
    )
    rider_id = await conn.fetchval(
        """
        INSERT INTO riders (
            email, password_hash, phone, name, supabase_user_id,
            phone_verified, declared_income, effective_income, risk_score, risk_profile,
            city, platform, experiment_group_id
        ) VALUES ($1, $2, $3, $4, $5, false, $6, $7, 50, 'medium', $8, $9, 'control')
        RETURNING id
        """,
        body.email,
        password_hash,
        normalized_phone,
        body.name,
        supabase_user_id,
        float(body.declared_income or 500.0),
        _effective_income,
        body.city or 'Mumbai',
        # FIX #8: use the platform provided by the rider, fallback to 'zepto'
        body.platform or 'zepto',
    )

    token = create_access_token({"sub": str(rider_id), "role": "rider", "email": body.email})
    log.info("rider_registered", rider_id=str(rider_id))
    return {"access_token": token, "rider_id": str(rider_id), "is_new_rider": True}


@router.post("/login")
async def rider_login(
    body: RiderLoginRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """Login with email + password."""
    rider = await get_rider_by_email(conn, body.email)
    if not rider:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    pw_hash = rider.get("password_hash")
    if not pw_hash or not verify_password(body.password, pw_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(rider["id"]), "role": "rider", "email": body.email})
    log.info("rider_authenticated_email", rider_id=str(rider["id"]))
    return {"access_token": token, "rider_id": str(rider["id"])}


# ─── Google OAuth (frontend-driven, Supabase JS client) ───────────────────────

@router.get("/google/setup-info")
async def google_oauth_setup_info():
    """
    Returns instructions for setting up Google OAuth via Supabase.
    The actual OAuth flow is entirely frontend-driven — no backend route needed for the redirect.

    Frontend flow:
      1. const { data } = await supabase.auth.signInWithOAuth({ provider: 'google' })
      2. User signs in with Google → redirected back with Supabase session
      3. Frontend sends supabase_access_token to POST /auth/google/exchange
      4. Backend returns GigShield JWT

    Supabase dashboard setup:
      Authentication → Providers → Google → Enable
      Add Google Client ID + Secret (from Google Cloud Console)
      Add https://<project>.supabase.co/auth/v1/callback to Google redirect URIs
    """
    return {
        "flow": "frontend_supabase_oauth",
        "exchange_endpoint": "POST /auth/google/exchange",
        "required_body": {"supabase_access_token": "string"},
    }


@router.post("/google/exchange")
async def google_oauth_exchange(
    body: GoogleExchangeRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Exchange Supabase access token (after Google OAuth on frontend) for GigShield JWT.
    Frontend calls this after receiving supabase session from signInWithOAuth.
    """
    supabase = _get_supabase_client()
    if not supabase:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.",
        )

    try:
        user_response = supabase.auth.get_user(body.supabase_access_token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid Supabase token")
        user = user_response.user
        supabase_user_id = str(user.id)
        email = user.email
        name = (user.user_metadata or {}).get("full_name") or (user.user_metadata or {}).get("name")
    except HTTPException:
        raise
    except Exception as exc:
        log.error("google_token_verification_failed", error=str(exc))
        raise HTTPException(status_code=401, detail="Token verification failed")

    # Look up existing rider
    rider = await conn.fetchrow(
        "SELECT * FROM riders WHERE supabase_user_id = $1 OR email = $2 LIMIT 1",
        supabase_user_id, email,
    )

    if not rider:
        _city_median = get_city_median_income("Mumbai")
        _effective_income = round(min(500.0, _city_median), 2)
        rider_id = await conn.fetchval(
            """
            INSERT INTO riders (
                email, supabase_user_id, name,
                phone_verified, effective_income, risk_score, risk_profile
            ) VALUES ($1, $2, $3, false, $4, 50, 'medium')
            RETURNING id
            """,
            email, supabase_user_id, name, _effective_income,
        )
        is_new = True
    else:
        rider_id = rider["id"]
        if not rider.get("supabase_user_id"):
            await conn.execute(
                "UPDATE riders SET supabase_user_id = $1 WHERE id = $2",
                supabase_user_id, rider_id,
            )
        is_new = False

    token = create_access_token({"sub": str(rider_id), "role": "rider", "email": email})
    log.info("rider_authenticated_google", rider_id=str(rider_id), is_new=is_new)
    return {"access_token": token, "rider_id": str(rider_id), "is_new_rider": is_new}


# ─── Admin login ───────────────────────────────────────────────────────────────

@router.post("/admin/login")
async def admin_login(
    body: AdminLoginRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """Admin login with username/password (bcrypt hash in admin_users table)."""
    admin = await conn.fetchrow(
        "SELECT * FROM admin_users WHERE username = $1", body.username
    )
    if not admin or not verify_password(body.password, admin["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        {"sub": str(admin["id"]), "role": "admin", "username": body.username},
    )
    return {"access_token": token, "admin_id": str(admin["id"])}


@router.post("/hub/login")
async def hub_login(
    body: HubLoginRequest,
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    if not body.password.strip():
        raise HTTPException(status_code=401, detail="Invalid credentials")

    hub_user = None
    if body.username:
        hub_user = await conn.fetchrow(
            """
            SELECT hmu.id, hmu.hub_id, hmu.username, hmu.password_hash, h.name AS hub_name
            FROM hub_manager_users hmu
            JOIN hubs h ON h.id = hmu.hub_id
            WHERE hmu.username = $1
            """,
            body.username.strip(),
        )
    elif body.hub_id:
        hub_user = await conn.fetchrow(
            """
            SELECT hmu.id, hmu.hub_id, hmu.username, hmu.password_hash, h.name AS hub_name
            FROM hub_manager_users hmu
            JOIN hubs h ON h.id = hmu.hub_id
            WHERE hmu.hub_id::text = $1
            """,
            body.hub_id.strip(),
        )

    if not hub_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(body.password, hub_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        {
            "sub": str(hub_user["id"]),
            "role": "hub",
            "hub_id": str(hub_user["hub_id"]),
        }
    )
    return {
        "access_token": token,
        "hub_manager_id": str(hub_user["id"]),
        "hub_id": str(hub_user["hub_id"]),
    }
