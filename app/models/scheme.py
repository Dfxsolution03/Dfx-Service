from datetime import datetime
from typing import Optional
from sqlalchemy import String, Float, Integer, Text, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# ─── Phase 2 — Scheme Request lifecycle ───
# A SchemeRequest is the application a customer files to join a scheme. It is
# the gate that must clear (KYC verified + Admin approval) before an actual
# SchemeEnrollment — the authoritative financial record — is ever created.
SCHEME_REQUEST_REQUESTED = "REQUESTED"
SCHEME_REQUEST_APPROVED = "APPROVED"
SCHEME_REQUEST_REJECTED = "REJECTED"
SCHEME_REQUEST_STATUSES = [
    SCHEME_REQUEST_REQUESTED, SCHEME_REQUEST_APPROVED, SCHEME_REQUEST_REJECTED,
]


class Scheme(Base, TimestampMixin):
    __tablename__ = "schemes"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    monthly_amount: Mapped[float] = mapped_column(Float, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_description: Mapped[str] = mapped_column(String(255), nullable=True)
    # Deactivation is soft — no dedicated soft-delete column exists elsewhere in this
    # codebase (Branch uses the same is_active-flag pattern), so DELETE /schemes/{id}
    # sets this False rather than removing the row.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")


class SchemeRequest(Base, TimestampMixin):
    """
    Phase 2 — an immutable-history request to join a scheme.

    Lifecycle: REQUESTED -> APPROVED (creates one SchemeEnrollment) or
    REQUESTED -> REJECTED (with a reason). A request is never reopened or
    rewritten; a customer who wants to try again files a NEW request, so the
    rejected/approved row stays as historical truth.

    This table is a GATE, not a second enrollment engine. It holds no monetary
    or scheme-configuration data of its own — money and enrollment behaviour
    stay owned by SchemeEnrollment and the existing payment/passbook ledgers.
    enrollment_id is set once, at approval, and is UNIQUE so a single request
    can never be tied to two enrollments (defence in depth behind the
    row-locked, status-guarded approval transaction).
    """
    __tablename__ = "scheme_requests"
    __table_args__ = (
        UniqueConstraint("enrollment_id", name="uq_scheme_requests_enrollment"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=SCHEME_REQUEST_REQUESTED, nullable=False, index=True
    )
    # KYC status snapshot at the moment the request was filed — historical
    # truth. The live gate at approval time always re-reads User.kyc_status;
    # this is only a record of what it was when the customer applied.
    kyc_status_at_request: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # The enrollment produced on approval. NULL until (and unless) approved.
    enrollment_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    requested_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Explicit foreign_keys: this table has several FKs into users
    # (customer_id, requested_by, approved_by, rejected_by), so SQLAlchemy
    # cannot infer which one each relationship follows. requested_by/
    # approved_by/rejected_by are audit-only and carry no relationship.
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id])
    scheme: Mapped["Scheme"] = relationship("Scheme")
    enrollment: Mapped[Optional["SchemeEnrollment"]] = relationship(
        "SchemeEnrollment", foreign_keys=[enrollment_id]
    )
