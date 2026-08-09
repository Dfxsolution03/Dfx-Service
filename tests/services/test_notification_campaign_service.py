"""
JROS Service Tests — NotificationCampaignService (Admin Notifications).
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User, Tenant
from app.schemas.notification_campaign import (
    NotificationCampaignCreateRequest,
    NotificationCampaignUpdateRequest,
)
from app.services.notification_campaign_service import NotificationCampaignService
from app.exceptions.base import ResourceNotFoundException, ValidationException


class TestCreateAndSendInApp:

    async def test_create_draft_persists(self, db_session: AsyncSession, admin_user: User):
        campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="Diwali Offer", body="20% off gold coins", channel="IN_APP", target_type="ALL"),
        )
        assert campaign.status == "DRAFT"
        assert campaign.channel == "IN_APP"

    async def test_send_all_creates_notification_per_customer(
        self, db_session: AsyncSession, admin_user: User, customer_user: User
    ):
        campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="Hello", body="Body text", channel="IN_APP", target_type="ALL"),
        )
        sent = await NotificationCampaignService.send(db_session, admin_user, campaign.id)
        assert sent.status == "SENT"
        assert sent.recipient_count == 1
        assert sent.sent_at is not None

    async def test_send_with_no_matching_recipients_fails_honestly(
        self, db_session: AsyncSession, admin_user: User
    ):
        campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="Nobody", body="x", channel="IN_APP", target_type="CUSTOMERS", target_ids=["usr_does_not_exist"]),
        )
        sent = await NotificationCampaignService.send(db_session, admin_user, campaign.id)
        assert sent.status == "FAILED"
        assert "recipients" in sent.error.lower()

    async def test_send_unconfigured_external_channel_fails_never_fakes_sent(
        self, db_session: AsyncSession, admin_user: User, customer_user: User
    ):
        campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="WA blast", body="x", channel="WHATSAPP", target_type="ALL"),
        )
        sent = await NotificationCampaignService.send(db_session, admin_user, campaign.id)
        assert sent.status == "FAILED"
        assert "not configured" in sent.error.lower()


class TestDraftEditingRules:

    async def test_cannot_edit_after_send(self, db_session: AsyncSession, admin_user: User, customer_user: User):
        campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="A", body="B", channel="IN_APP", target_type="ALL"),
        )
        await NotificationCampaignService.send(db_session, admin_user, campaign.id)
        with pytest.raises(ValidationException):
            await NotificationCampaignService.update(
                db_session, admin_user, campaign.id, NotificationCampaignUpdateRequest(title="Changed")
            )

    async def test_scheme_target_requires_real_scheme(self, db_session: AsyncSession, admin_user: User):
        with pytest.raises(ValidationException):
            await NotificationCampaignService.create(
                db_session, admin_user,
                NotificationCampaignCreateRequest(title="A", body="B", channel="IN_APP", target_type="SCHEME", target_ids=["sch_fake"]),
            )


class TestTenantIsolation:

    async def test_admin_cannot_access_other_tenant_campaign(
        self, db_session: AsyncSession, admin_user: User
    ):
        other_tenant = Tenant(id="tnt_notif_other", name="Other Co", slug="other-notif-co", status="Active")
        db_session.add(other_tenant)
        await db_session.flush()

        other_campaign = await NotificationCampaignService.create(
            db_session, admin_user,
            NotificationCampaignCreateRequest(title="Mine", body="x", channel="IN_APP", target_type="ALL"),
        )
        # Forge a second admin belonging to a different tenant to prove
        # cross-tenant reads are impossible regardless of a guessed campaign id.
        other_admin = User(
            id="usr_notif_other_admin", tenant_id=other_tenant.id, role_id=admin_user.role_id,
            email="other-admin@jros-test.com", hashed_password=admin_user.hashed_password,
            name="Other Admin", is_active=True,
        )
        db_session.add(other_admin)
        await db_session.flush()
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        stmt = select(User).options(selectinload(User.role)).where(User.id == other_admin.id)
        other_admin = (await db_session.execute(stmt)).scalar_one()

        with pytest.raises(ResourceNotFoundException):
            await NotificationCampaignService.get_detail(db_session, other_admin, other_campaign.id)
