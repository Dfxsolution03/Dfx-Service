from app.core.config import settings as app_settings, INSECURE_SECRET_KEY_DEFAULT
from app.core.integration_registry import get_provider
from app.models.auth import User
from app.models.platform_settings import PlatformSettings
from app.repositories.audit_repository import AuditRepository
from app.repositories.platform_settings_repository import PlatformSettingsRepository
from app.schemas.platform_settings import (
    PlatformSettingsResponse,
    PlatformSettingsStatusResponse,
    PlatformSettingsUpdateRequest,
    ProviderStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession


def _parse_flags(feature_flags: str | None) -> list[str]:
    if not feature_flags:
        return []
    return [f.strip() for f in feature_flags.split(",") if f.strip()]


def _serialize_flags(flags: list[str]) -> str | None:
    return ",".join(flags) if flags else None


def _security_status() -> dict:
    """Boolean status flags only — never the actual secret values."""
    return {
        "secret_key_rotated": app_settings.SECRET_KEY != INSECURE_SECRET_KEY_DEFAULT,
        "cors_configured": bool(app_settings.ALLOWED_ORIGINS),
    }


def _provider_status(key: str) -> ProviderStatus:
    provider = get_provider(key)
    return ProviderStatus(provider=key, label=provider.label if provider else key, configured=bool(provider and provider.is_configured()))


def _to_response(row: PlatformSettings) -> PlatformSettingsResponse:
    return PlatformSettingsResponse(
        platform_name=row.platform_name,
        support_email=row.support_email,
        support_phone=row.support_phone,
        default_currency=row.default_currency,
        default_timezone=row.default_timezone,
        maintenance_mode=row.maintenance_mode,
        feature_flags=_parse_flags(row.feature_flags),
        updated_at=row.updated_at,
        email_status=_provider_status("email"),
        whatsapp_status=_provider_status("whatsapp"),
        security_status=_security_status(),
        logo_url=row.logo_url,
        favicon_url=row.favicon_url,
        brand_color_primary=row.brand_color_primary,
        brand_color_secondary=row.brand_color_secondary,
        login_tagline=row.login_tagline,
        email_from_name=row.email_from_name,
        custom_domain=row.custom_domain,
        custom_domain_status=row.custom_domain_status,
    )


class PlatformSettingsService:
    """SuperAdmin-only. Persists only non-sensitive platform configuration —
    see app/models/platform_settings.py; secrets are never accepted or
    stored here (app/core/integration_registry.py handles those via env
    vars)."""

    @staticmethod
    async def get(db: AsyncSession) -> PlatformSettingsResponse:
        row = await PlatformSettingsRepository.get(db)
        if not row:
            row = await PlatformSettingsRepository.create_default(db)
            await db.commit()
            await db.refresh(row)
        return _to_response(row)

    @staticmethod
    async def get_status(db: AsyncSession) -> PlatformSettingsStatusResponse:
        row = await PlatformSettingsRepository.get(db)
        maintenance_mode = row.maintenance_mode if row else False
        return PlatformSettingsStatusResponse(
            maintenance_mode=maintenance_mode,
            email_status=_provider_status("email"),
            whatsapp_status=_provider_status("whatsapp"),
            security_status=_security_status(),
        )

    @staticmethod
    async def update(
        db: AsyncSession, current_user: User, req: PlatformSettingsUpdateRequest
    ) -> PlatformSettingsResponse:
        row = await PlatformSettingsRepository.get(db)
        if not row:
            row = await PlatformSettingsRepository.create_default(db)

        before = {
            "platform_name": row.platform_name,
            "support_email": row.support_email,
            "support_phone": row.support_phone,
            "default_currency": row.default_currency,
            "default_timezone": row.default_timezone,
            "maintenance_mode": row.maintenance_mode,
        }

        if req.platform_name is not None:
            row.platform_name = req.platform_name
        if req.support_email is not None:
            row.support_email = req.support_email
        if req.support_phone is not None:
            row.support_phone = req.support_phone
        if req.default_currency is not None:
            row.default_currency = req.default_currency
        if req.default_timezone is not None:
            row.default_timezone = req.default_timezone
        if req.maintenance_mode is not None:
            row.maintenance_mode = req.maintenance_mode
        if req.feature_flags is not None:
            row.feature_flags = _serialize_flags(req.feature_flags)
        if req.logo_url is not None:
            row.logo_url = req.logo_url or None
        if req.favicon_url is not None:
            row.favicon_url = req.favicon_url or None
        if req.brand_color_primary is not None:
            row.brand_color_primary = req.brand_color_primary
        if req.brand_color_secondary is not None:
            row.brand_color_secondary = req.brand_color_secondary
        if req.login_tagline is not None:
            row.login_tagline = req.login_tagline or None
        if req.email_from_name is not None:
            row.email_from_name = req.email_from_name or None
        if req.custom_domain is not None:
            row.custom_domain = req.custom_domain or None
            # Honest status only — no DNS/TLS provisioning happens here.
            row.custom_domain_status = "pending" if row.custom_domain else "not_configured"
        row.updated_by = current_user.id

        await AuditRepository.create_log(
            db,
            tenant_id=None,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="PLATFORM_SETTINGS_UPDATE",
            target_entity="platform_settings",
            target_id=row.id,
            before_state=before,
            after_state={
                "platform_name": row.platform_name,
                "support_email": row.support_email,
                "support_phone": row.support_phone,
                "default_currency": row.default_currency,
                "default_timezone": row.default_timezone,
                "maintenance_mode": row.maintenance_mode,
            },
        )

        await db.commit()
        await db.refresh(row)
        return _to_response(row)
