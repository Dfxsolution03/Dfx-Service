from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from app.models.support import SupportTicket, SupportMessage, FAQ


class SupportRepository:
    # -- Tickets --------------------------------------------------------
    @staticmethod
    async def get_tickets_by_user(
        db: AsyncSession, user_id: str, tenant_id: str
    ) -> List[SupportTicket]:
        stmt = (
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id, SupportTicket.tenant_id == tenant_id)
            .order_by(SupportTicket.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_ticket_by_id_for_user(
        db: AsyncSession, ticket_id: str, user_id: str, tenant_id: str
    ) -> Optional[SupportTicket]:
        """Own-only lookup — used by every customer endpoint so a 404 (not
        403) is returned for tickets that exist but aren't the caller's."""
        stmt = (
            select(SupportTicket)
            .options(selectinload(SupportTicket.messages).joinedload(SupportMessage.sender))
            .where(
                SupportTicket.id == ticket_id,
                SupportTicket.user_id == user_id,
                SupportTicket.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_tickets_by_tenant(db: AsyncSession, tenant_id: str) -> List[SupportTicket]:
        """Admin: every ticket for the tenant, newest first, with the
        customer eager-loaded for the derived customer_name/email."""
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.user))
            .where(SupportTicket.tenant_id == tenant_id)
            .order_by(SupportTicket.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_ticket_by_id_for_tenant(
        db: AsyncSession, ticket_id: str, tenant_id: str
    ) -> Optional[SupportTicket]:
        """Admin: fetch any ticket in the tenant (not own-only)."""
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.user))
            .where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_ticket(db: AsyncSession, ticket: SupportTicket) -> SupportTicket:
        db.add(ticket)
        return ticket

    @staticmethod
    async def count_tickets_by_tenant(db: AsyncSession, tenant_id: str) -> int:
        """Backs ticket_number uniqueness — a cheap per-tenant sequence
        source, same idea as CatalogueRepository.get_next_version."""
        from sqlalchemy import func
        stmt = select(func.count(SupportTicket.id)).where(SupportTicket.tenant_id == tenant_id)
        return int((await db.execute(stmt)).scalar_one())

    # -- Messages ---------------------------------------------------------
    @staticmethod
    async def create_message(db: AsyncSession, message: SupportMessage) -> SupportMessage:
        db.add(message)
        return message

    # -- FAQs ---------------------------------------------------------------
    @staticmethod
    async def get_active_faqs_by_tenant(db: AsyncSession, tenant_id: str) -> List[FAQ]:
        stmt = (
            select(FAQ)
            .where(FAQ.tenant_id == tenant_id, FAQ.is_active == True)  # noqa: E712
            .order_by(FAQ.category, FAQ.created_at)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
