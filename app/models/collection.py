from datetime import date
from typing import Optional
from sqlalchemy import String, Integer, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Phase 7 — internal record that ONE overdue reminder was raised for a specific
# enrollment + due period. Not a payment, not a passbook entry — the payment
# ledger stays authoritative. Delivery is IN_APP via the existing Notification
# infrastructure; WhatsApp/voice stay adapter placeholders and are never faked.
REMINDER_CHANNEL_IN_APP = "IN_APP"


class CollectionReminder(Base, TimestampMixin):
    """One reminder per (enrollment, due_date). The unique constraint is the
    dedup + concurrency backstop: two scheduler runs (repeated or parallel) that
    both try to remind the same overdue period — one insert wins, the other hits
    the constraint and is skipped, so a customer is never spammed twice for the
    same due date. When a successful contribution advances the enrollment's
    next_due_date (Phase 3), the old due_date is no longer overdue, so no new
    reminder is ever raised — payment stops reminders with no extra hook."""
    __tablename__ = "collection_reminders"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "due_date", name="uq_collection_reminder_period"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The enrollment's next_due_date this reminder was raised for.
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    overdue_days: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default=REMINDER_CHANNEL_IN_APP)
