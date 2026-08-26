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
    """One reminder per (enrollment, due_date, week_index).

    Phase 9 — weekly recurrence. week_index is the 7-day bucket the reminder
    belongs to, derived from how many days the installment is overdue:
    (overdue_days - 1) // 7 → 0 for days 1-7, 1 for days 8-14, and so on. The
    unique constraint dedups WITHIN a weekly bucket (two scheduler runs in the
    same week can't double-notify) while ALLOWING one reminder per new 7-day
    bucket, so an unpaid due is re-reminded every 7 days.

    When a successful contribution advances the enrollment's next_due_date
    (Phase 3), the old due_date stops being overdue, so no further bucket is ever
    reached — payment stops reminders with no extra hook. Historical rows created
    before Phase 9 carry week_index=0 (server default) and stay valid."""
    __tablename__ = "collection_reminders"
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", "due_date", "week_index",
            name="uq_collection_reminder_period_week",
        ),
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
    # Phase 9 — the 7-day overdue bucket this reminder belongs to
    # ((overdue_days - 1) // 7). Part of the unique key so each new week yields
    # exactly one reminder. Defaults to 0 for pre-Phase-9 rows.
    week_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default=REMINDER_CHANNEL_IN_APP)
