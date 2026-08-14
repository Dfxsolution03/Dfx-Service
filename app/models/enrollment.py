from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Date, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

STATUS_ACTIVE = "ACTIVE"
# Reached at maturity. Unchanged meaning — never repurposed to mean "stopped".
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"
# Customer stopped contributing. No future contributions accepted, but the
# balance already paid in stays redeemable customer credit — a CLOSED
# enrollment is not a dead one.
STATUS_CLOSED = "CLOSED"
# Every rupee of eligible balance has been consumed by redemptions.
STATUS_REDEEMED = "REDEEMED"

ENROLLMENT_STATUSES = [
    STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED, STATUS_CLOSED, STATUS_REDEEMED,
]
# Statuses that still accept new scheme contributions.
CONTRIBUTABLE_STATUSES = [STATUS_ACTIVE]
# Statuses whose remaining balance may still be applied to a jewellery sale.
REDEEMABLE_STATUSES = [STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CLOSED]


class SchemeEnrollment(Base, TimestampMixin):
    __tablename__ = "scheme_enrollments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "enrollment_number", name="uq_enrollments_tenant_number"),
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
    enrollment_number: Mapped[str] = mapped_column(String(30), nullable=False)
    joined_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_ACTIVE, nullable=False, index=True)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Closure audit. Set only when an Admin explicitly closes the scheme; a
    # closure is recorded, never inferred from the status alone. No monetary
    # cache here — the eligible balance is always derived from the successful
    # payment ledger minus the redemption ledger.
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
    # Explicit foreign_keys: this table now has TWO foreign keys into users
    # (customer_id and closed_by), so SQLAlchemy cannot infer which one the
    # customer relationship follows. closed_by is audit-only and deliberately
    # has no relationship of its own.
    customer: Mapped["User"] = relationship("User", foreign_keys=[customer_id])
    scheme: Mapped["Scheme"] = relationship("Scheme")


class SchemeRedemption(Base, TimestampMixin):
    """
    Scheme Module — one immutable record per application of a customer's
    accumulated scheme balance to a jewellery sale.

    APPEND-ONLY. A redemption is never edited or deleted; correcting one means
    reversing the sale through the existing return lifecycle, not rewriting
    history here.

    Deliberately NOT a monetary cache on the enrollment. The available balance
    is always derived: SUM(successful scheme payments) - SUM(redemptions). That
    keeps one source of truth and makes partial redemption across several sales
    (₹1,20,000 spent as ₹50,000 + ₹40,000 + ₹30,000) safe without a running
    total that could drift.

    Money movement itself still goes through the existing sale_payments ledger
    as a source=SCHEME_REDEMPTION row carrying this enrollment_id — no second
    payment system. This table is the scheme-side half of the audit chain:
    enrollment -> successful payments -> redemption -> sale -> invoice.
    """
    __tablename__ = "scheme_redemptions"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrollment_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Denormalised so an audit never has to join back through the enrollment to
    # prove whose balance was spent.
    customer_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    enrollment: Mapped["SchemeEnrollment"] = relationship("SchemeEnrollment")
