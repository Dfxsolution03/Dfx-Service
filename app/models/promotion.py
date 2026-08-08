from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Promotion(Base, TimestampMixin):
    """
    Tenant-scoped promotion/offer banner shown on the customer Home screen.
    Replaces the previously hardcoded "Festival Offer" card — the customer
    endpoint resolves the single highest-priority active banner (within its
    date window, if set), respecting tenant isolation; no active banner
    returns None rather than fabricating one.
    """
    __tablename__ = "promotions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    button_text: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    button_link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    background_color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    text_color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
