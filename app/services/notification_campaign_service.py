import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.integration_registry import is_channel_configured
from app.core.logging import logger
from app.exceptions.base import ForbiddenException, ResourceNotFoundException, ValidationException
from app.models.auth import User
from app.models.notification import Notification, NotificationCampaign
from app.repositories.audit_repository import AuditRepository
from app.repositories.notification_campaign_repository import NotificationCampaignRepository
from app.repositories.scheme_repository import SchemeRepository
from app.schemas.notification_campaign import (
    NotificationCampaignCreateRequest,
    NotificationCampaignResponse,
    NotificationCampaignUpdateRequest,
)
from app.services.email_service import get_email_provider


def _parse_ids(target_ids: Optional[str]) -> List[str]:
    if not target_ids:
        return []
    return [t.strip() for t in target_ids.split(",") if t.strip()]


def _serialize_ids(ids: List[str]) -> Optional[str]:
    return ",".join(ids) if ids else None


def _to_response(campaign: NotificationCampaign) -> NotificationCampaignResponse:
    return NotificationCampaignResponse(
        id=campaign.id,
        title=campaign.title,
        body=campaign.body,
        channel=campaign.channel,
        target_type=campaign.target_type,
        target_ids=_parse_ids(campaign.target_ids),
        status=campaign.status,
        recipient_count=campaign.recipient_count,
        sent_at=campaign.sent_at,
        error=campaign.error,
        created_by=campaign.created_by,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


class NotificationCampaignService:
    """
    Admin Notifications / Notification Authoring. Every method derives
    tenant scope from the authenticated user — target_ids/tenant are never
    trusted from the request body beyond the campaign's own declared
    audience, and that audience is always re-resolved against
    current_user.tenant_id at send time (see _resolve_recipients), so an
    Admin can never target another tenant's customers no matter what a
    client sends.
    """

    @staticmethod
    async def create(
        db: AsyncSession, current_user: User, req: NotificationCampaignCreateRequest
    ) -> NotificationCampaignResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        if req.target_type == "SCHEME":
            scheme = await SchemeRepository.get_scheme_by_id(db, req.target_ids[0], current_user.tenant_id)
            if not scheme:
                raise ValidationException("Scheme not found for this tenant", field="target_ids")

        campaign = NotificationCampaign(
            id=f"cmp_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            title=req.title,
            body=req.body,
            channel=req.channel,
            target_type=req.target_type,
            target_ids=_serialize_ids(req.target_ids),
            status="DRAFT",
        )
        await NotificationCampaignRepository.create(db, campaign)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="NOTIFICATION_CAMPAIGN_CREATE",
            target_entity="notification_campaigns",
            target_id=campaign.id,
            before_state=None,
            after_state={"title": req.title, "channel": req.channel, "target_type": req.target_type},
        )

        await db.commit()
        await db.refresh(campaign)
        return _to_response(campaign)

    @staticmethod
    async def list_campaigns(
        db: AsyncSession, current_user: User, status: Optional[str], page: int, page_size: int
    ) -> Tuple[List[NotificationCampaignResponse], int]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rows, total = await NotificationCampaignRepository.list_for_tenant(
            db, current_user.tenant_id, status, page, page_size
        )
        return [_to_response(r) for r in rows], total

    @staticmethod
    async def get_detail(db: AsyncSession, current_user: User, campaign_id: str) -> NotificationCampaignResponse:
        campaign = await NotificationCampaignService._get_owned(db, current_user, campaign_id)
        return _to_response(campaign)

    @staticmethod
    async def update(
        db: AsyncSession, current_user: User, campaign_id: str, req: NotificationCampaignUpdateRequest
    ) -> NotificationCampaignResponse:
        campaign = await NotificationCampaignService._get_owned(db, current_user, campaign_id)
        if campaign.status != "DRAFT":
            raise ValidationException("Only draft notifications can be edited")

        before = {"title": campaign.title, "body": campaign.body, "channel": campaign.channel}
        if req.title is not None:
            campaign.title = req.title
        if req.body is not None:
            campaign.body = req.body
        if req.channel is not None:
            campaign.channel = req.channel
        if req.target_type is not None:
            campaign.target_type = req.target_type
        if req.target_ids is not None:
            campaign.target_ids = _serialize_ids(req.target_ids)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="NOTIFICATION_CAMPAIGN_UPDATE",
            target_entity="notification_campaigns",
            target_id=campaign.id,
            before_state=before,
            after_state={"title": campaign.title, "body": campaign.body, "channel": campaign.channel},
        )

        await db.commit()
        await db.refresh(campaign)
        return _to_response(campaign)

    @staticmethod
    async def cancel(db: AsyncSession, current_user: User, campaign_id: str) -> NotificationCampaignResponse:
        campaign = await NotificationCampaignService._get_owned(db, current_user, campaign_id)
        if campaign.status not in ("DRAFT", "FAILED"):
            raise ValidationException("Only draft or failed notifications can be cancelled")
        campaign.status = "CANCELLED"

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="NOTIFICATION_CAMPAIGN_CANCEL",
            target_entity="notification_campaigns",
            target_id=campaign.id,
            before_state=None,
            after_state={"status": "CANCELLED"},
        )
        await db.commit()
        await db.refresh(campaign)
        return _to_response(campaign)

    @staticmethod
    async def send(db: AsyncSession, current_user: User, campaign_id: str) -> NotificationCampaignResponse:
        campaign = await NotificationCampaignService._get_owned(db, current_user, campaign_id)
        if campaign.status not in ("DRAFT", "FAILED"):
            raise ValidationException(f"Notification is already {campaign.status.lower()}")

        recipients = await NotificationCampaignService._resolve_recipients(db, current_user.tenant_id, campaign)
        if not recipients:
            campaign.status = "FAILED"
            campaign.error = "No matching recipients found for the selected audience."
            await db.commit()
            await db.refresh(campaign)
            return _to_response(campaign)

        if not is_channel_configured(campaign.channel):
            campaign.status = "FAILED"
            campaign.error = (
                f"{campaign.channel} delivery is not configured. "
                "Configure the provider in SuperAdmin > Integrations first."
            )
            await db.commit()
            await db.refresh(campaign)
            return _to_response(campaign)

        if campaign.channel == "IN_APP":
            notifications = [
                Notification(
                    id=f"ntf_{uuid.uuid4().hex[:12]}",
                    tenant_id=current_user.tenant_id,
                    user_id=recipient.id,
                    title=campaign.title,
                    message=campaign.body,
                    type="ANNOUNCEMENT",
                    campaign_id=campaign.id,
                )
                for recipient in recipients
            ]
            await NotificationCampaignRepository.bulk_create_notifications(db, notifications)
            campaign.status = "SENT"
            campaign.sent_at = datetime.now(timezone.utc)
            campaign.recipient_count = len(recipients)
            campaign.error = None
        elif campaign.channel == "EMAIL":
            provider = get_email_provider()
            sent_count = 0
            last_error: Optional[str] = None
            for recipient in recipients:
                if not recipient.email:
                    continue
                try:
                    await provider.send_email(to=recipient.email, subject=campaign.title, body_text=campaign.body)
                    sent_count += 1
                except Exception as exc:  # pragma: no cover - real SMTP failure path
                    last_error = str(exc)
                    logger.error("Notification campaign %s: email send failed for %s: %s", campaign.id, recipient.id, exc)
            if sent_count == 0:
                campaign.status = "FAILED"
                campaign.error = last_error or "No recipients had a usable email address."
            else:
                campaign.status = "SENT"
                campaign.sent_at = datetime.now(timezone.utc)
                campaign.recipient_count = sent_count
                campaign.error = f"Delivery failed for {len(recipients) - sent_count} recipient(s)." if last_error else None
        else:
            # WHATSAPP / SMS / PUSH: no real provider integration exists yet
            # even when is_channel_configured() were somehow true — this
            # branch is unreachable today since those channels always report
            # not-configured, but stays honest rather than silently no-op-ing.
            campaign.status = "FAILED"
            campaign.error = f"{campaign.channel} delivery is not implemented yet."

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="NOTIFICATION_CAMPAIGN_SEND",
            target_entity="notification_campaigns",
            target_id=campaign.id,
            before_state=None,
            after_state={"status": campaign.status, "recipient_count": campaign.recipient_count},
        )

        await db.commit()
        await db.refresh(campaign)
        return _to_response(campaign)

    @staticmethod
    async def _resolve_recipients(db: AsyncSession, tenant_id: str, campaign: NotificationCampaign) -> List[User]:
        if campaign.target_type == "ALL":
            return await NotificationCampaignRepository.list_all_customers(db, tenant_id)
        if campaign.target_type == "CUSTOMERS":
            return await NotificationCampaignRepository.list_customers_by_ids(
                db, tenant_id, _parse_ids(campaign.target_ids)
            )
        if campaign.target_type == "SCHEME":
            scheme_ids = _parse_ids(campaign.target_ids)
            if not scheme_ids:
                return []
            return await NotificationCampaignRepository.list_customers_by_scheme(db, tenant_id, scheme_ids[0])
        return []

    @staticmethod
    async def _get_owned(db: AsyncSession, current_user: User, campaign_id: str) -> NotificationCampaign:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        campaign = await NotificationCampaignRepository.get_by_id_for_tenant(db, campaign_id, current_user.tenant_id)
        if not campaign:
            raise ResourceNotFoundException(f"Notification ID '{campaign_id}' not found")
        return campaign
