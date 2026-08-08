from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user, require_admin_only
from app.schemas.auth import StandardSuccessResponse
from app.schemas.support import (
    SupportTicketCreateRequest,
    SupportMessageCreateRequest,
    SupportTicketAdminUpdateRequest,
)
from app.services.support_service import SupportService

router = APIRouter()


# 1. Customer Support Endpoints
@router.post(
    "/customer/support/tickets",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Support Ticket (Customer)",
    description="Creates a new support ticket for the authenticated customer.",
)
async def create_ticket(
    req: SupportTicketCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    ticket = await SupportService.create_ticket(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message="Support ticket created successfully",
        data={"ticket": ticket.model_dump(mode="json")},
    )


@router.get(
    "/customer/support/tickets",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List My Support Tickets (Customer)",
    description="Returns only the authenticated customer's own support tickets.",
)
async def list_my_tickets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    tickets = await SupportService.get_my_tickets(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Support tickets retrieved successfully",
        data={"tickets": [t.model_dump(mode="json") for t in tickets]},
    )


@router.get(
    "/customer/support/tickets/{ticket_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Support Ticket Detail (Customer)",
    description="Returns a single support ticket with its message thread. Own-only — returns 404 (not 403) if the ticket isn't the caller's.",
)
async def get_my_ticket_detail(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    ticket = await SupportService.get_my_ticket_detail(db, current_user, ticket_id)
    return StandardSuccessResponse(
        success=True,
        message="Support ticket retrieved successfully",
        data={"ticket": ticket.model_dump(mode="json")},
    )


@router.post(
    "/customer/support/tickets/{ticket_id}/messages",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to Support Ticket (Customer)",
    description="Adds a reply message to the caller's own support ticket. Own-only — returns 404 (not 403) if the ticket isn't the caller's.",
)
async def add_message(
    ticket_id: str,
    req: SupportMessageCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    message = await SupportService.add_message(db, current_user, ticket_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Message added successfully",
        data={"message": message.model_dump(mode="json")},
    )


@router.get(
    "/customer/support/faqs",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Active FAQs (Customer)",
    description="Returns active FAQs for the customer's tenant.",
)
async def list_faqs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    faqs = await SupportService.get_active_faqs(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="FAQs retrieved successfully",
        data={"faqs": [f.model_dump(mode="json") for f in faqs]},
    )


# 2. Admin Support Endpoints
@router.get(
    "/admin/support/tickets",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Support Tickets (Admin)",
    description="Returns all support tickets for the admin's tenant, newest first.",
)
async def list_tickets_admin(
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    tickets = await SupportService.get_tickets_for_admin(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Support tickets retrieved successfully",
        data={"tickets": [t.model_dump(mode="json") for t in tickets]},
    )


@router.put(
    "/admin/support/tickets/{ticket_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Support Ticket (Admin)",
    description="Updates a support ticket's status and/or priority.",
)
async def update_ticket_admin(
    ticket_id: str,
    req: SupportTicketAdminUpdateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    ticket = await SupportService.update_ticket_for_admin(db, current_user, ticket_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Support ticket updated successfully",
        data={"ticket": ticket.model_dump(mode="json")},
    )


@router.get(
    "/admin/support/tickets/{ticket_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Support Ticket Detail (Admin)",
    description="Returns a single ticket with its full message thread. Own-tenant only.",
)
async def get_ticket_detail_admin(
    ticket_id: str,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    ticket = await SupportService.get_ticket_detail_for_admin(db, current_user, ticket_id)
    return StandardSuccessResponse(
        success=True,
        message="Support ticket retrieved successfully",
        data={"ticket": ticket.model_dump(mode="json")},
    )


@router.post(
    "/admin/support/tickets/{ticket_id}/messages",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reply to Support Ticket (Admin)",
    description="Adds an admin reply message to any ticket in the admin's own tenant.",
)
async def add_message_admin(
    ticket_id: str,
    req: SupportMessageCreateRequest,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_async_db),
):
    message = await SupportService.add_message_for_admin(db, current_user, ticket_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Message added successfully",
        data={"message": message.model_dump(mode="json")},
    )
