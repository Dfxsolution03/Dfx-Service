from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

TicketStatus = Literal["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]
TicketPriority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]


class SupportTicketCreateRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=3, max_length=5000)
    category: str = Field(..., min_length=2, max_length=50)
    priority: TicketPriority = "MEDIUM"


class SupportMessageCreateRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class SupportTicketAdminUpdateRequest(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None


class SupportMessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_id: str
    sender_name: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class SupportTicketResponse(BaseModel):
    """Customer-facing — lean, no tenant_id, no other-user internal ids."""
    id: str
    ticket_number: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupportTicketDetailResponse(SupportTicketResponse):
    messages: List[SupportMessageResponse] = Field(default_factory=list)


class AdminSupportTicketResponse(BaseModel):
    """Admin-facing — includes tenant/user ids plus derived customer name."""
    id: str
    tenant_id: str
    user_id: str
    customer_name: str
    customer_email: Optional[str]
    ticket_number: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdminSupportTicketDetailResponse(AdminSupportTicketResponse):
    messages: List[SupportMessageResponse] = Field(default_factory=list)


class FAQResponse(BaseModel):
    id: str
    question: str
    answer: str
    category: Optional[str] = None

    class Config:
        from_attributes = True
