"""
JROS Service Tests — SupportService (Phase 7 admin ticket detail/reply)
=======================================================================

Covers only the new Admin-facing detail/reply methods added in this phase —
the customer-facing create/list/reply/FAQ paths are exercised indirectly
via the API test suite already and are not duplicated here.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.schemas.support import SupportTicketCreateRequest, SupportMessageCreateRequest
from app.services.support_service import SupportService
from app.exceptions.base import ResourceNotFoundException


async def _create_ticket(db_session, customer_user) -> str:
    ticket = await SupportService.create_ticket(
        db_session, customer_user,
        SupportTicketCreateRequest(subject="Test issue", description="Something is wrong", category="general"),
    )
    return ticket.id


class TestGetTicketDetailForAdmin:

    async def test_returns_ticket_with_messages(
        self, db_session: AsyncSession, admin_user: User, customer_user: User
    ):
        ticket_id = await _create_ticket(db_session, customer_user)
        await SupportService.add_message(
            db_session, customer_user, ticket_id, SupportMessageCreateRequest(message="Follow-up from customer")
        )

        result = await SupportService.get_ticket_detail_for_admin(db_session, admin_user, ticket_id)
        assert result.id == ticket_id
        assert result.customer_name == customer_user.name
        assert len(result.messages) == 1
        assert result.messages[0].message == "Follow-up from customer"

    async def test_nonexistent_ticket_raises_not_found(
        self, db_session: AsyncSession, admin_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await SupportService.get_ticket_detail_for_admin(db_session, admin_user, "tck_does_not_exist_xyz")


class TestAddMessageForAdmin:

    async def test_admin_reply_appears_in_thread(
        self, db_session: AsyncSession, admin_user: User, customer_user: User
    ):
        ticket_id = await _create_ticket(db_session, customer_user)

        message = await SupportService.add_message_for_admin(
            db_session, admin_user, ticket_id, SupportMessageCreateRequest(message="We're looking into it")
        )
        assert message.sender_id == admin_user.id

        detail = await SupportService.get_ticket_detail_for_admin(db_session, admin_user, ticket_id)
        assert any(m.message == "We're looking into it" for m in detail.messages)

    async def test_nonexistent_ticket_raises_not_found(
        self, db_session: AsyncSession, admin_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await SupportService.add_message_for_admin(
                db_session, admin_user, "tck_does_not_exist_xyz", SupportMessageCreateRequest(message="Hi")
            )
