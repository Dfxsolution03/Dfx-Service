from typing import Optional
from sqlalchemy import String, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

PLATFORM_SETTINGS_SINGLETON_ID = "platform_settings"


class PlatformSettings(Base, TimestampMixin):
    """
    Single-row table (id is always PLATFORM_SETTINGS_SINGLETON_ID) for
    non-sensitive, platform-wide configuration only. Never a place for
    secrets — see app/core/integration_registry.py for how provider
    credentials are handled instead (env vars, never persisted here).
    """
    __tablename__ = "platform_settings"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=PLATFORM_SETTINGS_SINGLETON_ID)
    platform_name: Mapped[str] = mapped_column(String(100), default="DFX Solution", nullable=False)
    support_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata", nullable=False)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Comma-separated feature-flag keys that are currently "on" — same plain
    # Text convention as User.staff_permissions/CatalogueDesign.canvas_json.
    feature_flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # White-label / branding — platform-level defaults, distinct from
    # per-tenant Tenant.brand_color/logo_url (app/models/auth.py). None of
    # these are secrets, so they live here rather than the encrypted
    # integration config path.
    logo_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    favicon_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    brand_color_primary: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    brand_color_secondary: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    login_tagline: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_from_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Configuration/status only — no DNS/domain provisioning happens in this
    # application. status is one of: not_configured | pending | active.
    custom_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    custom_domain_status: Mapped[str] = mapped_column(String(20), default="not_configured", nullable=False)

    updated_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
