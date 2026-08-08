import uuid
from datetime import date
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.support import SupportTicket, SupportMessage
from app.repositories.support_repository import SupportRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ForbiddenException
from app.schemas.support import (
    SupportTicketCreateRequest,
    SupportMessageCreateRequest,
    SupportTicketAdminUpdateRequest,
    SupportTicketResponse,
    SupportTicketDetailResponse,
    SupportMessageResponse,
    AdminSupportTicketResponse,
    FAQResponse,
)


def _generate_ticket_number() -> str:
    """Same human-readable PREFIX-YYMMDD-HEX6 convention already established
    by SchemeEnrollment.enrollment_number (see enrollment_service.py)."""
    return f"TCK-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _to_message_response(msg: SupportMessage) -> SupportMessageResponse:
    return SupportMessageResponse(
        id=msg.id,
        ticket_id=msg.ticket_id,
        sender_id=msg.sender_id,
        sender_name=msg.sender.name if msg.sender else "Unknown",
        message=msg.message,
        created_at=msg.created_at,
    )


def _to_admin_response(ticket: SupportTicket) -> AdminSupportTicketResponse:
    return AdminSupportTicketResponse(
        id=ticket.id,
        tenant_id=ticket.tenant_id,
        user_id=ticket.user_id,
        customer_name=ticket.user.name,
        customer_email=ticket.user.email,
        ticket_number=ticket.ticket_number,
        subject=ticket.subject,
        description=ticket.description,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


class SupportService:
    # ─── Customer ───

    @staticmethod
    async def create_ticket(
        db: AsyncSession, current_user: User, req: SupportTicketCreateRequest
    ) -> SupportTicketResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        ticket_id = f"tck_{uuid.uuid4().hex[:12]}"
        ticket = SupportTicket(
            id=ticket_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            ticket_number=_generate_ticket_number(),
            subject=req.subject,
            description=req.description,
            category=req.category,
            priority=req.priority,
            status="OPEN",
        )
        await SupportRepository.create_ticket(db, ticket)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SUPPORT_TICKET_CREATE",
            target_entity="support_tickets",
            target_id=ticket_id,
            before_state=None,
            after_state={"subject": req.subject, "category": req.category, "priority": req.priority},
        )

        await db.commit()
        await db.refresh(ticket)
        return SupportTicketResponse.model_validate(ticket)

    @staticmethod
    async def get_my_tickets(db: AsyncSession, current_user: User) -> List[SupportTicketResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tickets = await SupportRepository.get_tickets_by_user(db, current_user.id, current_user.tenant_id)
        return [SupportTicketResponse.model_validate(t) for t in tickets]

    @staticmethod
    async def get_my_ticket_detail(
        db: AsyncSession, current_user: User, ticket_id: str
    ) -> SupportTicketDetailResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        ticket = await SupportRepository.get_ticket_by_id_for_user(
            db, ticket_id, current_user.id, current_user.tenant_id
        )
        if not ticket:
            raise ResourceNotFoundException(f"Support ticket ID '{ticket_id}' not found")

        return SupportTicketDetailResponse(
            id=ticket.id,
            ticket_number=ticket.ticket_number,
            subject=ticket.subject,
            description=ticket.description,
            category=ticket.category,
            priority=ticket.priority,
            status=ticket.status,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            messages=[_to_message_response(m) for m in ticket.messages],
        )

    @staticmethod
    async def add_message(
        db: AsyncSession, current_user: User, ticket_id: str, req: SupportMessageCreateRequest
    ) -> SupportMessageResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        ticket = await SupportRepository.get_ticket_by_id_for_user(
            db, ticket_id, current_user.id, current_user.tenant_id
        )
        if not ticket:
            raise ResourceNotFoundException(f"Support ticket ID '{ticket_id}' not found")

        message_id = f"tcm_{uuid.uuid4().hex[:12]}"
        message = SupportMessage(
            id=message_id,
            ticket_id=ticket.id,
            sender_id=current_user.id,
            message=req.message,
        )
        await SupportRepository.create_message(db, message)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SUPPORT_MESSAGE_CREATE",
            target_entity="support_messages",
            target_id=message_id,
            before_state=None,
            after_state={"ticket_id": ticket.id},
        )

        await db.commit()
        await db.refresh(message)
        return SupportMessageResponse(
            id=message.id,
            ticket_id=message.ticket_id,
            sender_id=message.sender_id,
            sender_name=current_user.name,
            message=message.message,
            created_at=message.created_at,
        )

    @staticmethod
    async def get_active_faqs(db: AsyncSession, current_user: User) -> List[FAQResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        faqs = await SupportRepository.get_active_faqs_by_tenant(db, current_user.tenant_id)
        return [FAQResponse.model_validate(f) for f in faqs]

    # ─── Admin ───

    @staticmethod
    async def get_tickets_for_admin(
        db: AsyncSession, current_user: User
    ) -> List[AdminSupportTicketResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        tickets = await SupportRepository.get_tickets_by_tenant(db, current_user.tenant_id)
        return [_to_admin_response(t) for t in tickets]

    @staticmethod
    async def update_ticket_for_admin(
        db: AsyncSession, current_user: User, ticket_id: str, req: SupportTicketAdminUpdateRequest
    ) -> AdminSupportTicketResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        ticket = await SupportRepository.get_ticket_by_id_for_tenant(db, ticket_id, current_user.tenant_id)
        if not ticket:
            raise ResourceNotFoundException(f"Support ticket ID '{ticket_id}' not found")

        before_state = {"status": ticket.status, "priority": ticket.priority}

        if req.status is not None:
            ticket.status = req.status
        if req.priority is not None:
            ticket.priority = req.priority

        after_state = {"status": ticket.status, "priority": ticket.priority}

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SUPPORT_TICKET_UPDATE",
            target_entity="support_tickets",
            target_id=ticket_id,
            before_state=before_state,
            after_state=after_state,
        )

        await db.commit()
        await db.refresh(ticket)
        return _to_admin_response(ticket)
