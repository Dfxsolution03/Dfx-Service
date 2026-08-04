from datetime import date
from typing import Optional
from sqlalchemy import String, Float, Integer, Text, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PassbookEntry(Base, TimestampMixin):
    __tablename__ = "passbook_entries"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "entry_number", name="uq_passbook_enrollment_entry_number"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_number: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    gold_rate: Mapped[float] = mapped_column(Float, nullable=False)
    gold_weight: Mapped[float] = mapped_column(Float, nullable=False)
    running_installment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    enrollment: Mapped["SchemeEnrollment"] = relationship("SchemeEnrollment")
