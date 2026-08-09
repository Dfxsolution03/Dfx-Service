import secrets
import smtplib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.crypto import EncryptionNotConfiguredError, decrypt_json, encrypt_json
from app.core.integration_registry import ConfigField, get_provider, list_providers
from app.core.security import hash_password
from app.exceptions.base import ResourceNotFoundException, ValidationException
from app.models.auth import User
from app.models.integration import PlatformIntegration, Webhook
from app.repositories.audit_repository import AuditRepository
from app.repositories.integration_repository import IntegrationRepository
from app.schemas.integration import (
    ConfigFieldSchema,
    IntegrationResponse,
    IntegrationTestResponse,
    WebhookCreateRequest,
    WebhookCreatedResponse,
    WebhookResponse,
)


def _mask(value: Any) -> str:
    s = str(value)
    if len(s) <= 4:
        return "•" * 8
    return "•" * 8 + s[-4:]


def _decrypted_config(row: PlatformIntegration) -> Optional[Dict[str, Any]]:
    if not row.config_encrypted:
        return None
    try:
        return decrypt_json(row.config_encrypted)
    except EncryptionNotConfiguredError:
        return None


def _masked_config(row: PlatformIntegration, fields: List[ConfigField]) -> Dict[str, Any]:
    data = _decrypted_config(row)
    if not data:
        return {}
    field_by_key = {f.key: f for f in fields}
    return {k: (_mask(v) if field_by_key.get(k, ConfigField(k, k)).secret else v) for k, v in data.items() if v not in (None, "")}


def _db_configured(row: PlatformIntegration, fields: List[ConfigField]) -> bool:
    data = _decrypted_config(row)
    if not data:
        return False
    required = [f.key for f in fields if f.required]
    return all(data.get(k) not in (None, "") for k in required)


def _status_for(row: PlatformIntegration, configured: bool) -> str:
    if not configured:
        return "not_configured"
    if row.last_test_status == "failed":
        return "connection_failed"
    return "enabled" if row.enabled else "configured_disabled"


def _to_response(row: PlatformIntegration) -> IntegrationResponse:
    provider = get_provider(row.provider)
    fields = provider.fields if provider else []
    configured = bool((provider and provider.is_configured()) or _db_configured(row, fields))
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
        fields=[ConfigFieldSchema(key=f.key, label=f.label, secret=f.secret, required=f.required, type=f.type) for f in fields],
        masked_config=_masked_config(row, fields),
    )


class IntegrationService:
    """
    SuperAdmin Integrations. Provider credentials entered through the
    Configure form are encrypted at rest (app/core/crypto.py) and only ever
    decrypted server-side, inside this service, for a real connection test
    or to build the exact payload a real provider client would need later —
    never returned to any API response, never logged, never audited in
    plaintext (see save_config's audit call, which only logs field names).
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
    async def save_config(
        db: AsyncSession, current_user: User, provider_key: str, values: Dict[str, Any]
    ) -> IntegrationResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")
        if not provider.fields:
            raise ValidationException(
                f"{provider.label} has no selected vendor/API contract yet — nothing to configure here. "
                "Set the corresponding environment variables once a provider is chosen, or extend the field list first."
            )

        known_keys = {f.key for f in provider.fields}
        unknown = set(values.keys()) - known_keys
        if unknown:
            raise ValidationException(f"Unknown configuration field(s): {', '.join(sorted(unknown))}")
        missing = [f.label for f in provider.fields if f.required and not values.get(f.key)]
        if missing:
            raise ValidationException(f"Missing required field(s): {', '.join(missing)}")

        row = await IntegrationRepository.get_or_create(db, provider_key)

        # Merge onto existing config so a partial "replace just the API key"
        # save doesn't blow away other already-configured fields.
        existing = _decrypted_config(row) or {}
        merged = {**existing, **values}

        try:
            row.config_encrypted = encrypt_json(merged)
        except EncryptionNotConfiguredError as exc:
            raise ValidationException(str(exc))

        # Config changed — any prior test result is no longer trustworthy,
        # and an already-enabled integration must re-prove itself.
        row.last_test_status = None
        row.last_error = None
        row.enabled = False
        row.updated_by = current_user.id

        await AuditRepository.create_log(
            db, tenant_id=None, actor_user_id=current_user.id, actor_name=current_user.name,
            actor_role=current_user.role.name, action="INTEGRATION_CONFIGURE",
            target_entity="platform_integrations", target_id=row.id,
            before_state=None,
            # Field NAMES only, never values — this is the one place a bug
            # here could otherwise leak a secret into the audit trail.
            after_state={"configured_fields": sorted(values.keys())},
        )

        await db.commit()
        await db.refresh(row)
        return _to_response(row)

    @staticmethod
    async def clear_config(db: AsyncSession, current_user: User, provider_key: str) -> IntegrationResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")

        row = await IntegrationRepository.get_or_create(db, provider_key)
        row.config_encrypted = None
        row.enabled = False
        row.last_test_status = None
        row.last_error = None
        row.updated_by = current_user.id

        await AuditRepository.create_log(
            db, tenant_id=None, actor_user_id=current_user.id, actor_name=current_user.name,
            actor_role=current_user.role.name, action="INTEGRATION_CONFIG_REMOVE",
            target_entity="platform_integrations", target_id=row.id,
            before_state=None, after_state={"configured": False},
        )
        await db.commit()
        await db.refresh(row)
        return _to_response(row)

    @staticmethod
    async def set_enabled(
        db: AsyncSession, current_user: User, provider_key: str, enabled: bool
    ) -> IntegrationResponse:
        provider = get_provider(provider_key)
        if not provider:
            raise ResourceNotFoundException(f"Unknown integration provider '{provider_key}'")

        row = await IntegrationRepository.get_or_create(db, provider_key)
        configured = bool(provider.is_configured() or _db_configured(row, provider.fields))

        if enabled:
            if not configured:
                raise ValidationException(f"{provider.label} cannot be enabled until it is configured.")
            if row.last_test_status != "success":
                raise ValidationException(f"{provider.label} must pass Test Connection before it can be enabled.")

        before = {"enabled": row.enabled}
        row.enabled = enabled
        row.updated_by = current_user.id

        await AuditRepository.create_log(
            db, tenant_id=None, actor_user_id=current_user.id, actor_name=current_user.name,
            actor_role=current_user.role.name, action="INTEGRATION_ENABLE" if enabled else "INTEGRATION_DISABLE",
            target_entity="platform_integrations", target_id=row.id,
            before_state=before, after_state={"enabled": enabled},
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
        db_config = _decrypted_config(row)
        configured = bool(provider.is_configured() or _db_configured(row, provider.fields))

        if not configured:
            row.last_tested_at = now
            row.last_test_status = None
            row.last_error = None
            await db.commit()
            return IntegrationTestResponse(
                provider=provider_key, status="not_configured",
                message=f"{provider.label} has no credentials configured yet.", tested_at=now,
            )

        status_str, message = await IntegrationService._run_real_test(provider_key, db_config)
        row.last_tested_at = now
        row.last_test_status = status_str
        row.last_error = None if status_str == "success" else message

        await AuditRepository.create_log(
            db, tenant_id=None, actor_user_id=current_user.id, actor_name=current_user.name,
            actor_role=current_user.role.name, action="INTEGRATION_TEST",
            target_entity="platform_integrations", target_id=row.id,
            before_state=None, after_state={"status": status_str},
        )
        await db.commit()
        return IntegrationTestResponse(provider=provider_key, status=status_str, message=message, tested_at=now)

    @staticmethod
    async def _run_real_test(provider_key: str, db_config: Optional[Dict[str, Any]]) -> tuple[str, str]:
        """Only the providers with a genuinely working codepath (currently
        just SMTP, via smtplib) attempt a real connection — using
        UI-configured values if present, falling back to env vars. The rest
        have credentials-presence checked by `configured` but no concrete
        HTTP client wired up yet, since no specific vendor has been chosen —
        reported honestly, never faked as connected."""
        if provider_key == "email":
            cfg = db_config or {}
            host = cfg.get("host") or app_settings.SMTP_HOST
            port = int(cfg.get("port") or app_settings.SMTP_PORT)
            username = cfg.get("username") or app_settings.SMTP_USERNAME
            password = cfg.get("password") or app_settings.SMTP_PASSWORD
            use_tls = cfg.get("use_tls", app_settings.SMTP_USE_TLS)
            try:
                with smtplib.SMTP(host, port, timeout=8) as server:
                    if use_tls:
                        server.starttls()
                    if username:
                        server.login(username, password)
                return "success", "SMTP connection succeeded."
            except Exception as exc:
                return "failed", f"SMTP connection failed: {exc}"
        return (
            "failed",
            f"Credentials are stored but no vendor has been selected yet for {provider_key} — "
            "no live connection test is implemented. Provider credentials/API contract required for live connection testing.",
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
