"""
core/database.py — asyncpg connection pool + Supabase client singleton.
All timestamps come from PostgreSQL NOW() — never local Python time.
"""
from __future__ import annotations

import socket
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import asyncpg
import structlog
from supabase import create_client, Client
from app.config import get_settings

settings = get_settings()
log = structlog.get_logger()

# ─── Supabase client (used for auth, storage, RPC) ───────────────────────────
_supabase_client: Client | None = None
_supabase_anon_client: Client | None = None


def get_supabase() -> Client:
    """
    Service-role Supabase client — bypasses RLS.
    Use ONLY for privileged server-side operations (admin actions, background jobs).
    NEVER use for user-facing auth flows — use get_supabase_anon() instead.
    """
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _supabase_client


def get_supabase_anon() -> Client:
    """
    FIX #7: Anon-key Supabase client — respects Row-Level Security (RLS).
    Use for all user-facing auth flows: OTP send/verify, Google OAuth exchange.
    This prevents accidental RLS bypass on user-facing endpoints.
    """
    global _supabase_anon_client
    if _supabase_anon_client is None:
        _supabase_anon_client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key,
        )
    return _supabase_anon_client


# ─── asyncpg pool (used for all raw SQL — high throughput) ───────────────────
_pool: asyncpg.Pool | None = None


def _is_supabase_host(host: str) -> bool:
    h = (host or "").lower()
    return h.endswith(".supabase.co") or h.endswith(".pooler.supabase.com")


def _sanitize_dsn(dsn: str) -> str:
    p = urlparse(dsn)
    host = p.hostname or ""
    port = p.port or 5432
    user = p.username or ""
    db = (p.path or "").lstrip("/") or "postgres"
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    sslmode = query.get("sslmode", "")
    return (
        f"scheme={p.scheme or 'postgresql'} host={host} port={port} "
        f"user={user} db={db} sslmode={sslmode or 'unset'}"
    )


def _ensure_supabase_sslmode(dsn: str) -> str:
    p = urlparse(dsn)
    host = p.hostname or ""
    if not _is_supabase_host(host):
        return dsn

    query = dict(parse_qsl(p.query, keep_blank_values=True))
    if "sslmode" not in query:
        query["sslmode"] = "require"
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(query), p.fragment))


def _classify_connect_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if isinstance(exc, socket.gaierror) or "getaddrinfo" in msg:
        return "dns_resolution_failed"
    if "tenant or user not found" in msg:
        return "pooler_tenant_or_username_mismatch"
    if "password authentication failed" in msg or "invalid_password" in msg:
        return "db_auth_failed"
    if "timeout" in msg:
        return "network_timeout"
    if "ssl" in msg:
        return "ssl_handshake_or_mode_error"
    return "db_connection_error"


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        base_dsn = settings.database_url_pooler or settings.database_url
        dsn = _ensure_supabase_sslmode(base_dsn)
        parsed = urlparse(dsn)
        host = (parsed.hostname or "").lower()
        pool_kwargs = {
            "dsn": dsn,
            "min_size": 2,
            "max_size": 20,
            "command_timeout": 30,
            "server_settings": {"application_name": "gigshield-api"},
        }
        # Supabase pooler commonly runs in transaction mode (pgbouncer).
        # Disable prepared statement cache to avoid duplicate prepared statement errors.
        if host.endswith(".pooler.supabase.com"):
            pool_kwargs["statement_cache_size"] = 0
        log.info("db_connect_attempt", dsn=_sanitize_dsn(dsn))
        try:
            _pool = await asyncpg.create_pool(**pool_kwargs)
            log.info("db_pool_ready")
        except Exception as exc:
            log.error(
                "db_pool_failed",
                error_type=type(exc).__name__,
                category=_classify_connect_error(exc),
                error=str(exc),
                dsn=_sanitize_dsn(dsn),
            )
            raise
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_db_time() -> str:
    """Return DB server time as ISO string. ALWAYS use this — never datetime.now()."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.fetchval("SELECT NOW() AT TIME ZONE 'UTC'")
        return result.isoformat()


async def get_db_connection():
    """FastAPI dependency — yields an asyncpg connection."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
