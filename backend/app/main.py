"""app/main.py — FastAPI application factory."""
from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.core.database import get_pool, close_pool
from app.core.time_authority import check_clock_drift
from app.core.exceptions import register_exception_handlers

from app.api.v1.auth      import router as auth_router
from app.api.v1.riders    import router as riders_router
from app.api.v1.policies  import router as policies_router
from app.api.v1.claims    import router as claims_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.vov       import router as vov_router
from app.api.v1.hubs      import router as hubs_router
from app.api.v1.hub_manager import router as hub_manager_router
from app.api.internal.triggers import router as triggers_router
from app.api.internal.admin    import router as admin_router
from app.api.internal.webhooks import router as webhooks_router
from app.api.internal.ab_experiments import router as ab_experiments_router
from app.api.v1.b2b      import router as b2b_router
from app.api.v1.referral import router as referral_router

settings = get_settings()

structlog.configure(processors=[
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.JSONRenderer(),
], logger_factory=structlog.stdlib.LoggerFactory())

import sentry_sdk
if settings.sentry_dsn:
    try:
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)
    except Exception as exc:
        print(f"sentry_init_skipped: {exc}")


def create_app() -> FastAPI:
    app = FastAPI(
        title="GigShield API",
        description="Parametric income protection for Q-Commerce delivery riders — v3.0",
        version="3.0.0",
        docs_url="/docs"   if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    app.add_middleware(CORSMiddleware,
        # FIX #4: Use explicit origin list in production; specific localhost in dev.
        # allow_origins=["*"] with allow_credentials=True is invalid per CORS spec.
        allow_origins=settings.allowed_origins if settings.is_production else [
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    register_exception_handlers(app)
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # Rider-facing
    app.include_router(auth_router,      prefix="/api/v1")
    app.include_router(riders_router,    prefix="/api/v1")
    app.include_router(policies_router,  prefix="/api/v1")
    app.include_router(claims_router,    prefix="/api/v1")
    app.include_router(telemetry_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(vov_router,       prefix="/api/v1")
    app.include_router(hubs_router,      prefix="/api/v1")
    app.include_router(hub_manager_router, prefix="/api/v1")
    app.include_router(b2b_router,         prefix="/api/v1")
    app.include_router(referral_router,    prefix="/api/v1")

    # Internal / Admin
    app.include_router(triggers_router,  prefix="/internal")
    app.include_router(admin_router,     prefix="/internal")
    app.include_router(ab_experiments_router, prefix="/internal")
    app.include_router(webhooks_router,  prefix="/internal")

    @app.on_event("startup")
    async def startup():
        # FIX #2/#11: Validate production secrets BEFORE anything else.
        # Raises RuntimeError immediately if any secret is still a placeholder value.
        settings.validate_production_secrets()

        structlog.get_logger().info("gigshield_starting", env=settings.environment)
        app.state.db_ready = False
        try:
            pool = await get_pool()

            # BLOCKER #3 FIX: Auto-apply SQL migrations so fresh deployments
            # don't start with an empty schema.  Idempotent — already-applied
            # migrations are skipped.  Failure here aborts startup so the app
            # never serves requests against a broken schema.
            async with pool.acquire() as conn:
                from app.core.migrations import run_migrations
                await run_migrations(conn)

            await check_clock_drift()
            app.state.db_ready = True
            structlog.get_logger().info("gigshield_ready")
        except Exception as exc:
            structlog.get_logger().error("gigshield_startup_db_unavailable", error=str(exc))
            if settings.is_production:
                raise

    @app.on_event("shutdown")
    async def shutdown():
        await close_pool()

    @app.get("/health")
    async def health():
        db_ready = bool(getattr(app.state, "db_ready", False))
        return {
            "status": "ok" if db_ready else "degraded",
            "version": "3.0.0",
            "db_ready": db_ready,
        }

    return app


app = create_app()
