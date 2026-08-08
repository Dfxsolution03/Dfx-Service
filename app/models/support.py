from typing import Optional
from sqlalchemy import String, Text, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

STATUS_OPEN = "OPEN"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_RESOLVED = "RESOLVED"
STATUS_CLOSED = "CLOSED"

PRIORITY_LOW = "LOW"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_HIGH = "HIGH"
PRIORITY_URGENT = "URGENT"


class SupportTicket(Base, TimestampMixin):
    """
    Phase 6A / Module 31 — Customer Support System. ticket_number is
    server-generated at creation time, same human-readable
    "PREFIX-YYMMDD-HEX6" convention already established by
    SchemeEnrollment.enrollment_number (see enrollment_service.py's
    _generate_enrollment_number) — kept unique per-tenant, not globally.
    """
    __tablename__ = "support_tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_number", name="uq_support_tickets_tenant_number"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_number: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=PRIORITY_MEDIUM)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_OPEN, index=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    messages: Mapped[list["SupportMessage"]] = relationship(
        "SupportMessage", back_populates="ticket", cascade="all, delete-orphan",
        order_by="SupportMessage.created_at",
    )


class SupportMessage(Base, TimestampMixin):
    """One row per reply in a ticket thread (customer or admin sender)."""
    __tablename__ = "support_messages"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    ticket: Mapped["SupportTicket"] = relationship("SupportTicket", back_populates="messages")
    sender: Mapped["User"] = relationship("User")


class FAQ(Base, TimestampMixin):
    __tablename__ = "faqs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Soft-visibility flag, same is_active convention as Scheme/Product/Branch.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
