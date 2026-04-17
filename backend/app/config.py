from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ─── Supabase ────────────────────────────────────────────────────────────
    supabase_url: str = "https://placeholder.supabase.co"
    supabase_service_role_key: str = "placeholder"
    supabase_anon_key: str = "placeholder"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/gigshield"
    # Optional: set to Supabase pooler URI when direct db.<ref>.supabase.co is not routable.
    # Example: postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
    database_url_pooler: str = ""

    # ─── Redis ───────────────────────────────────────────────────────────────
    redis_url: str = "rediss://default:UPSTASH_PASSWORD@UPSTASH_ENDPOINT.upstash.io:6379/0"
    celery_broker_url: str = "rediss://default:UPSTASH_PASSWORD@UPSTASH_ENDPOINT.upstash.io:6379/0"
    celery_result_backend: str = "rediss://default:UPSTASH_PASSWORD@UPSTASH_ENDPOINT.upstash.io:6379/1"

    # ─── JWT ─────────────────────────────────────────────────────────────────
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 10080  # 7 days

    # ─── Razorpay ────────────────────────────────────────────────────────────
    razorpay_key_id: str = "rzp_test_placeholder"
    razorpay_key_secret: str = "placeholder"
    razorpay_account_number: str = "placeholder"
    razorpay_webhook_secret: str = "placeholder"

    # ─── External APIs ───────────────────────────────────────────────────────
    owm_api_key: str = "placeholder"
    waqi_api_key: str = "placeholder"
    here_api_key: str = "placeholder"
    weatherstack_api_key: str = "placeholder"
    google_routes_api_key: str = "placeholder"
    earth_engine_service_account_json: str = ""
    ndma_api_url: str = "https://sachet.ndma.gov.in/api"

    # ─── Platform Health URLs ─────────────────────────────────────────────────
    zepto_health_url: str = "https://api.zeptonow.com/health"
    blinkit_health_url: str = "https://blinkit.com/health"
    instamart_health_url: str = "https://www.swiggy.com/health"

    # ─── Notifications ───────────────────────────────────────────────────────
    # Twilio removed: Supabase Auth handles Phone OTP using their built-in Twilio.
    fcm_server_key: str = "placeholder"
    # WhatsApp feature REMOVED per product decision — use push + SMS only.

    # ─── Google OAuth (via Supabase dashboard) ────────────────────────────────────
    # Configure in Supabase: Authentication → Providers → Google
    # Backend only needs these for server-side token validation (optional)
    google_client_id: str = ""
    google_client_secret: str = ""

    # ─── Sentry ──────────────────────────────────────────────────────────────
    sentry_dsn: str = ""

    # ─── Admin ───────────────────────────────────────────────────────────────
    admin_webhook_url: str = ""
    admin_alert_email: str = "admin@gigshield.in"

    # ─── CORS ────────────────────────────────────────────────────────────────
    # FIX #4: explicit allowed origins list instead of wildcard in production
    allowed_origins: List[str] = ["https://gigshield.in", "https://app.gigshield.in"]

    # ─── App ─────────────────────────────────────────────────────────────────
    environment: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    reserve_buffer_inr: float = 500000.0

    # ─── ML ──────────────────────────────────────────────────────────────────
    ml_models_path: str = "./models"

    # ─── B2B Hub API ─────────────────────────────────────────────────────────
    # FIX #5: moved from module-level orphan into Settings so env vars work
    b2b_api_enabled: bool = True

    # ─── Referral ─────────────────────────────────────────────────────────────
    # FIX #5: moved from module-level orphan into Settings so env vars work
    referral_reward_inr: float = 50.0

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_production_secrets(self) -> None:
        """
        FIX #2: Call at startup. Raises RuntimeError if critical secrets are still
        placeholder values. This prevents silent production failures.
        """
        if not self.is_production:
            return

        PLACEHOLDER_TOKENS = {
            "placeholder",
            "dev-secret-change-in-production",
            "rzp_test_placeholder",
            "https://placeholder.supabase.co",
            "UPSTASH_PASSWORD",
        }

        def _is_placeholder(val: str) -> bool:
            if not val:
                return True
            return any(p in val for p in PLACEHOLDER_TOKENS)

        checks = {
            "JWT_SECRET_KEY": self.jwt_secret_key,
            "DATABASE_URL": self.database_url,
            "REDIS_URL": self.redis_url,
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
        }
        for name, val in checks.items():
            if _is_placeholder(val):
                raise RuntimeError(
                    f"PRODUCTION MISCONFIGURATION: {name} is still a placeholder value. "
                    f"Set the real value in your production .env before deploying."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ─── Backwards-compatibility shims ───────────────────────────────────────────
# FIX #5: These module-level variables are now inside Settings (above).
# These shims let any legacy import of `from app.config import b2b_api_enabled`
# still work without crashing, while reading from the real Settings object.
def __getattr__(name: str):
    _COMPAT = {
        "b2b_api_enabled": lambda: get_settings().b2b_api_enabled,
        "referral_reward_inr": lambda: get_settings().referral_reward_inr,
        # whatsapp_token and whatsapp_phone_number_id are REMOVED (feature removed)
    }
    if name in _COMPAT:
        return _COMPAT[name]()
    raise AttributeError(f"module 'app.config' has no attribute '{name}'")
