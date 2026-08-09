import secrets
import smtplib
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.integration_registry import get_provider, list_providers
from app.core.security import hash_password
from app.exceptions.base import ResourceNotFoundException, ValidationException
from app.models.auth import User
from app.models.integration import PlatformIntegration, Webhook
from app.repositories.audit_repository import AuditRepository
from app.repositories.integration_repository import IntegrationRepository
from app.schemas.integration import (
    IntegrationResponse,
    IntegrationTestResponse,
    WebhookCreateRequest,
    WebhookCreatedResponse,
    WebhookResponse,
)


def _status_for(row: PlatformIntegration, configured: bool) -> str:
    if not configured:
        return "not_configured"
    if row.last_test_status == "failed":
        return "connection_failed"
    return "enabled" if row.enabled else "configured_disabled"


def _to_response(row: PlatformIntegration) -> IntegrationResponse:
    provider = get_provider(row.provider)
    configured = bool(provider and provider.is_configured())
    return IntegrationResponse(
        provider=row.provider,
        label=provider.label if provider else row.provider,
        category=provider.category if provider else "",
        enabled=row.enabled,
        configured=configured,
        status=_status_for(row, configured),
        last_tested_at=row.last_tested_at,
        last_test_status=row.last_test_status,
        last_error=row.last_error,
    )


class IntegrationService:
    """
    SuperAdmin Integrations. Credentials never touch this service or the
    database — see app/core/integration_registry.py. This layer only
    tracks the enabled/disabled toggle and the result of the last
    connection test, both safe to persist and safe to return.
    """

    @staticmethod
    async def list_integrations(db: AsyncSession) -> List[IntegrationResponse]:
        results = []
        for provider in list_providers():
            row = await IntegrationRepository.get_or_create(db, provider.key)
            results.append(_to_response(row))
        await db.commit()
        return results

    @staticmethod
    async def get_integration(db: AsyncSession, provider_key: str) -> IntegrationResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")
        row = await IntegrationRepository.get_or_create(db, provider_key)
        await db.commit()
        return _to_response(row)

    @staticmethod
    async def set_enabled(
        db: AsyncSession, current_user: User, provider_key: str, enabled: bool
    ) -> IntegrationResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")
        if enabled and not provider.is_configured():
            raise ValidationException(
                f"{provider.label} cannot be enabled until its credentials are configured (see .env.example)."
            )

        row = await IntegrationRepository.get_or_create(db, provider_key)
        before = {"enabled": row.enabled}
        row.enabled = enabled
        row.updated_by = current_user.id

        await AuditRepository.create_log(
            db,
            tenant_id=None,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INTEGRATION_ENABLE" if enabled else "INTEGRATION_DISABLE",
            target_entity="platform_integrations",
            target_id=row.id,
            before_state=before,
            after_state={"enabled": enabled},
        )

        await db.commit()
        await db.refresh(row)
        return _to_response(row)

    @staticmethod
    async def test_connection(db: AsyncSession, current_user: User, provider_key: str) -> IntegrationTestResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")

        row = await IntegrationRepository.get_or_create(db, provider_key)
        now = datetime.now(timezone.utc)

        if not provider.is_configured():
            row.last_tested_at = now
            row.last_test_status = None
            row.last_error = None
            await db.commit()
            return IntegrationTestResponse(
                provider=provider_key, status="not_configured",
                message=f"{provider.label} has no credentials configured yet.", tested_at=now,
            )

        status_str, message = await IntegrationService._run_real_test(provider_key)
        row.last_tested_at = now
        row.last_test_status = status_str
        row.last_error = None if status_str == "success" else message

        await AuditRepository.create_log(
            db,
            tenant_id=None,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INTEGRATION_TEST",
            target_entity="platform_integrations",
            target_id=row.id,
            before_state=None,
            after_state={"status": status_str},
        )
        await db.commit()
        return IntegrationTestResponse(provider=provider_key, status=status_str, message=message, tested_at=now)

    @staticmethod
    async def _run_real_test(provider_key: str) -> tuple[str, str]:
        """Only the providers with a genuinely working codepath (currently
        just SMTP, via smtplib) attempt a real connection. The rest have
        credentials-presence checked by `configured` but no concrete HTTP
        client wired up yet — reported honestly, not faked as connected."""
        if provider_key == "email":
            try:
                with smtplib.SMTP(app_settings.SMTP_HOST, app_settings.SMTP_PORT, timeout=8) as server:
                    if app_settings.SMTP_USE_TLS:
                        server.starttls()
                    if app_settings.SMTP_USERNAME:
                        server.login(app_settings.SMTP_USERNAME, app_settings.SMTP_PASSWORD)
                return "success", "SMTP connection succeeded."
            except Exception as exc:
                return "failed", f"SMTP connection failed: {exc}"
        return (
            "failed",
            "Credentials are present but no live connection test is implemented for this provider yet.",
        )

    # ─── Webhook foundation ───

    @staticmethod
    async def create_webhook(db: AsyncSession, current_user: User, req: WebhookCreateRequest) -> WebhookCreatedResponse:
        raw_secret = secrets.token_urlsafe(32)
        webhook = Webhook(
            id=f"whk_{uuid.uuid4().hex[:12]}",
            url=req.url,
            event_type=req.event_type,
            is_active=req.is_active,
            secret_hash=hash_password(raw_secret),
            max_retries=req.max_retries,
            created_by=current_user.id,
        )
        await IntegrationRepository.create_webhook(db, webhook)

        await AuditRepository.create_log(
            db,
            tenant_id=None,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="WEBHOOK_CREATE",
            target_entity="webhooks",
            target_id=webhook.id,
            before_state=None,
            after_state={"url": req.url, "event_type": req.event_type},
        )

        await db.commit()
        await db.refresh(webhook)
        return WebhookCreatedResponse(
            id=webhook.id, url=webhook.url, event_type=webhook.event_type, is_active=webhook.is_active,
            max_retries=webhook.max_retries, last_delivery_at=None, last_delivery_status=None,
            created_at=webhook.created_at, signing_secret=raw_secret,
        )

    @staticmethod
    async def list_webhooks(db: AsyncSession) -> List[WebhookResponse]:
        rows = await IntegrationRepository.list_webhooks(db)
        return [WebhookResponse.model_validate(r) for r in rows]

    @staticmethod
    async def delete_webhook(db: AsyncSession, current_user: User, webhook_id: str) -> None:
        webhook = await IntegrationRepository.get_webhook_by_id(db, webhook_id)
        if not webhook:
            raise ResourceNotFoundException(f"Webhook ID '{webhook_id}' not found")

        await AuditRepository.create_log(
            db,
            tenant_id=None,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="WEBHOOK_DELETE",
            target_entity="webhooks",
            target_id=webhook_id,
            before_state={"url": webhook.url, "event_type": webhook.event_type},
            after_state=None,
        )
        await IntegrationRepository.delete_webhook(db, webhook)
        await db.commit()
