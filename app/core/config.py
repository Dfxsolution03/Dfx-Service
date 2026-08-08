import json
from typing import List, Union, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "DFX Solution Enterprise SaaS API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database Configuration
    DATABASE_URL: str = "sqlite+aiosqlite:///./jros_dev.db"
    SYNC_DATABASE_URL: Optional[str] = "sqlite:///./jros_dev.db"
    DIRECT_URL: Optional[str] = None

    # Connection Pooling Settings
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800  # Recycle connections after 30 mins
    DB_POOL_TIMEOUT: int = 30

    # CORS Origins Configuration
    ALLOWED_ORIGINS: Union[List[str], str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        return v

    # JWT Configuration
    SECRET_KEY: str = "jros-super-secret-enterprise-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # SuperAdmin Initial Seed Configuration
    SUPERADMIN_EMAIL: str = "superadmin@dfxsolution.com"
    SUPERADMIN_PASSWORD: str = "SuperAdmin@123"

    # Module 18 — Authentication Hardening: reset/verification token lifetimes.
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Module 29 — Tenant Provisioning: a new Admin's activation link reuses
    # the exact same PasswordResetToken table/flow as "forgot password" (see
    # SuperAdminService.provision_tenant), just with a longer expiry — a
    # business owner opening an onboarding email is a slower, less time-
    # critical action than someone actively mid-login-recovery.
    TENANT_ACTIVATION_TOKEN_EXPIRE_HOURS: int = 72

    # Module 18 — Email provider configuration. Unset (empty SMTP_HOST) means
    # no real SMTP/email-service is configured yet; the app falls back to a
    # ConsoleEmailProvider that logs the email instead of sending it, so the
    # password-reset/email-verification flows are still fully functional and
    # testable end-to-end without real email infrastructure. Set SMTP_HOST
    # (+ the rest) in .env to switch to real delivery — see
    # app/services/email_service.py.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@dfxsolution.com"
    SMTP_FROM_NAME: str = "DFX Solution"
    SMTP_USE_TLS: bool = True

    # Base URL the frontend is served from — used to build password-reset and
    # email-verification links in outbound emails.
    FRONTEND_URL: str = "http://localhost:3000"

    # Module 20 — Catalogue Studio image storage. Unset (empty SUPABASE_URL)
    # means no real Supabase Storage bucket is configured yet; uploads fall
    # back to LocalDiskStorageProvider (genuinely functional, not a stub —
    # see app/services/storage_service.py) so Products/Media Library work
    # end-to-end today with zero external infrastructure. Set SUPABASE_URL +
    # SUPABASE_SERVICE_ROLE_KEY to switch to real Supabase Storage.
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "catalogue-media"
    LOCAL_UPLOAD_DIR: str = "uploads"
    # Base URL this backend itself is reachable at — used to build URLs for
    # locally-stored files (e.g. http://localhost:8000/media/<path>).
    # Irrelevant once Supabase Storage is configured, since Supabase serves
    # its own public URLs.
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    MAX_UPLOAD_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB per image

    # Module 31 / Phase 0 — Market Rate Infrastructure. Disabled by default:
    # the existing tenant-admin daily gold-rate system
    # (app/services/goldrate_service.py, backed by the untouched gold_rates
    # table) remains the only active rate source until this flag is
    # explicitly enabled in a later phase. See the Module 31 architecture
    # doc for the full design; sync()/get_effective_rate() are unimplemented
    # scaffolding until Phase 1/2 regardless of this flag's value.
    ENABLE_MARKET_RATE_SYNC: bool = False
    MARKET_RATE_PROVIDER: str = "METALPRICEAPI"
    MARKET_RATE_SYNC_INTERVAL_MINUTES: int = 10
    MARKET_RATE_FETCH_TIMEOUT_SECONDS: int = 10
    MARKET_RATE_RETRY_COUNT: int = 3
    MARKET_RATE_RETRY_DELAY_SECONDS: int = 2
    METALPRICEAPI_KEY: str = ""
    IBJA_API_KEY: str = ""
    GOLDAPI_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
