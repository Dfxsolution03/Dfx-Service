from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """Customer notifications. type is one of SCHEME, PAYMENT, SUPPORT, KYC,
    ANNOUNCEMENT, GENERAL (validated at the service layer, not the DB)."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set only for rows created by an Admin-authored campaign send (IN_APP
    # channel) — nullable because most rows are system-raised (scheme/
    # payment/support/KYC events) and never belonged to a campaign.
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("notification_campaigns.id", ondelete="CASCADE"), nullable=True, index=True
    )


class NotificationCampaign(Base, TimestampMixin):
    """
    Admin-authored notification (Admin Notifications / Notification
    Authoring). A campaign is a draft until sent; sending resolves the
    target into recipients and, for IN_APP, creates one Notification row
    per recipient (see NotificationCampaignService). For external channels
    (EMAIL/WHATSAPP/SMS/PUSH) delivery only happens if the corresponding
    provider is actually configured (app/core/integration_registry.py) —
    otherwise status becomes FAILED with an honest error, never SENT.
    """
    __tablename__ = "notification_campaigns"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # IN_APP|EMAIL|WHATSAPP|SMS|PUSH
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # ALL|CUSTOMERS|SCHEME
    # Comma-separated: CUSTOMERS -> user ids, SCHEME -> single scheme id, ALL -> null.
    target_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")  # DRAFT|SENT|FAILED|CANCELLED
    recipient_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
