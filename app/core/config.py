import json
from typing import List, Union, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Known-insecure repository defaults for SECRET_KEY/SUPERADMIN_PASSWORD.
# Kept as module-level constants (not class attributes) so pydantic's
# BaseSettings metaclass never treats them as a private model attribute —
# see Settings.validate_production_safety, which compares against these.
INSECURE_SECRET_KEY_DEFAULT = "jros-super-secret-enterprise-key-change-in-production"
INSECURE_SUPERADMIN_PASSWORD_DEFAULT = "SuperAdmin@123"


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

    # Isolated database for the pytest suite ONLY — never read by the running
    # application. tests/conftest.py refuses to start without this set to a
    # value distinct from DATABASE_URL, so a test run can never write to
    # whatever database DATABASE_URL happens to point at (dev, staging, or
    # production). See tests/conftest.py's _resolve_test_database_url().
    TEST_DATABASE_URL: Optional[str] = None

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
    #
    # SECRET_KEY/SUPERADMIN_PASSWORD default to known, repository-visible
    # values so local dev works with zero setup. validate_production_safety()
    # below refuses to start if these defaults (or DEBUG=True) are still in
    # effect when ENVIRONMENT=production — see that method for details.
    SECRET_KEY: str = INSECURE_SECRET_KEY_DEFAULT
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Phase 7 — Push notifications (FCM/APNs). Default "noop": with no provider
    # configured the backend registers device tokens and records in-app
    # notifications but never fakes a push delivery. Set PUSH_PROVIDER=fcm and
    # supply the two FCM values (service-account JSON + project id) in the
    # deployment environment to enable real delivery.
    PUSH_PROVIDER: str = "noop"  # noop|fcm
    FCM_PROJECT_ID: Optional[str] = None
    FCM_CREDENTIALS_JSON: Optional[str] = None

    # SuperAdmin Initial Seed Configuration
    SUPERADMIN_EMAIL: str = "superadmin@dfxsolution.com"
    SUPERADMIN_PASSWORD: str = INSECURE_SUPERADMIN_PASSWORD_DEFAULT

    # Temporary, startup-gated SuperAdmin credential rotation (see
    # app/core/credential_rotation.py). Off by default everywhere — only
    # set these three in the deployment environment (never in a committed
    # file) when a one-time rotation is actually needed, then unset
    # ROTATE_SUPERADMIN_CREDENTIALS again afterward to disarm it.
    ROTATE_SUPERADMIN_CREDENTIALS: bool = False
    NEW_SUPERADMIN_EMAIL: Optional[str] = None
    NEW_SUPERADMIN_PASSWORD: Optional[str] = None

    # Google Sign-In — the OAuth 2.0 client IDs whose ID tokens this backend
    # will accept as the `aud` claim. Comma-separated, or a JSON list.
    #
    # For this app that is the Google Cloud **Web application** client ID: both
    # the Android and iOS clients pass it as `serverClientId`, so the tokens
    # they mint are addressed to it. Add the iOS client ID as a second entry
    # only if an iOS build is ever configured without a serverClientId.
    #
    # Empty (the default) switches Google sign-in OFF: with nothing to validate
    # `aud` against there is no safe way to accept a token, so the endpoint
    # returns a configuration error rather than trusting one. This is not a
    # secret — client IDs are public by design and ship inside the mobile app.
    GOOGLE_OAUTH_CLIENT_IDS: Union[List[str], str] = []

    @field_validator("GOOGLE_OAUTH_CLIENT_IDS", mode="before")
    @classmethod
    def assemble_google_client_ids(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        return v

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
    # Phase 7 — overdue reminder scheduler. Off by default (deploy opts in).
    ENABLE_COLLECTION_REMINDERS: bool = False
    COLLECTION_REMINDER_INTERVAL_HOURS: int = 24
    MARKET_RATE_PROVIDER: str = "METALPRICEAPI"
    MARKET_RATE_SYNC_INTERVAL_MINUTES: int = 10
    MARKET_RATE_FETCH_TIMEOUT_SECONDS: int = 10
    MARKET_RATE_RETRY_COUNT: int = 3
    MARKET_RATE_RETRY_DELAY_SECONDS: int = 2
    METALPRICEAPI_KEY: str = ""
    IBJA_API_KEY: str = ""
    GOLDAPI_KEY: str = ""

    # How stale a tenant's last published rate may be before the customer
    # endpoint stops serving it (see GoldRateService.get_customer_today_rate).
    # A store that hasn't entered today's rate yet should still show
    # yesterday's rather than nothing, but a rate from last week is
    # misinformation on a screen customers value their holdings from — past
    # this many days the endpoint reports the rate as unavailable instead.
    # Three days covers a weekend plus a public holiday.
    CUSTOMER_RATE_FALLBACK_MAX_AGE_DAYS: int = 3

    # SuperAdmin Integrations — providers with no credentials yet. Same
    # convention as SMTP_HOST/SUPABASE_URL above: empty string means
    # "not configured", the provider status API reports that truthfully, and
    # setting these env vars is the entire "configure the provider" step —
    # no code or UI change needed once real credentials exist.
    WHATSAPP_API_KEY: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    SMS_API_KEY: str = ""
    SMS_SENDER_ID: str = ""
    PAYMENT_GATEWAY_API_KEY: str = ""
    PAYMENT_GATEWAY_SECRET: str = ""

    # Encrypts SuperAdmin-entered integration credentials at rest (see
    # app/core/crypto.py). Must be a urlsafe-base64 32-byte Fernet key,
    # generated once via `Fernet.generate_key()` and set only in the
    # deployment environment — never committed. Unset means credential
    # encrypt/decrypt is unavailable and the UI-based "Configure" flow
    # reports a configuration error rather than ever storing plaintext.
    INTEGRATION_ENCRYPTION_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def validate_production_safety(self) -> None:
        """
        Fail fast on startup if ENVIRONMENT=production but the app is still
        running with insecure repository defaults. Never logs secret values —
        only whether each check passed. No-op for any other ENVIRONMENT
        (development/test/staging keep using their existing defaults).
        """
        if self.ENVIRONMENT.lower() != "production":
            return

        errors = []
        if self.DEBUG:
            errors.append("DEBUG must be False when ENVIRONMENT=production")
        if self.SECRET_KEY == INSECURE_SECRET_KEY_DEFAULT:
            errors.append("SECRET_KEY must be overridden from its insecure default when ENVIRONMENT=production")
        if self.SUPERADMIN_PASSWORD == INSECURE_SUPERADMIN_PASSWORD_DEFAULT:
            errors.append("SUPERADMIN_PASSWORD must be overridden from its insecure default when ENVIRONMENT=production")

        if errors:
            raise RuntimeError(
                "Refusing to start with an insecure production configuration:\n  - "
                + "\n  - ".join(errors)
            )


settings = Settings()
