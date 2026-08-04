from datetime import date
from typing import Optional
from sqlalchemy import String, Float, Date, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

STATUS_PENDING = "PENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_CANCELLED = "CANCELLED"
STATUS_REFUNDED = "REFUNDED"

METHOD_CASH = "CASH"
METHOD_BANK_TRANSFER = "BANK_TRANSFER"
METHOD_UPI = "UPI"
METHOD_CARD = "CARD"
METHOD_CHEQUE = "CHEQUE"
METHOD_ONLINE = "ONLINE"


class Payment(Base, TimestampMixin):
    """
    Internal payment record. Infrastructure only — no external payment
    gateway is integrated (see app/services/payment_gateway.py for the
    documented extension points). gateway_name/gateway_transaction_id
    stay null for every payment created in this module (manual entries);
    they exist for a future gateway-originated payment to populate.
    """
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "payment_reference", name="uq_payments_tenant_reference"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: populated once this payment is linked to a passbook entry —
    # not automatic in this module, see PaymentService for the documented
    # (unwired) integration point.
    passbook_entry_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("passbook_entries.id", ondelete="SET NULL"), nullable=True
    )
    payment_reference: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default=STATUS_SUCCESS)
    gateway_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    gateway_transaction_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    enrollment: Mapped["SchemeEnrollment"] = relationship("SchemeEnrollment")
