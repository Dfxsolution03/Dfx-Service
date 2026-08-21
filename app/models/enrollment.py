from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Date, DateTime, Float, Integer, ForeignKey, UniqueConstraint
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

    # ─── Phase 3 — contribution coverage ───
    # Total monthly installments successfully covered so far (sum of
    # Payment.months_covered across SUCCESSFUL contributions). A derived
    # cache advanced only inside the row-locked contribution transaction, so
    # concurrent contributions serialise and can never both advance from the
    # same stale value. Balance in rupees stays derived from the payment
    # ledger — this counts installments, not money.
    months_paid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Date the next installment falls due = joined_date + months_paid months.
    # NULL once the scheme is fully covered (months_paid >= duration_months).
    next_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # ─── Scheme Tier Plans ───
    # The tier the customer selected at enrollment. SET NULL on tier delete so a
    # later tier change can never rewrite this enrollment; the snapshot below is
    # the authoritative source of this enrollment's terms.
    scheme_tier_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("scheme_tiers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Terms frozen at enrollment time. Both NULL for legacy enrollments that
    # predate tiers or were created without a tier selection — those fall back to
    # scheme.monthly_amount / scheme.duration_months (see resolve_enrollment_terms).
    selected_monthly_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    selected_duration_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Phase 8 — free-text operational note on the enrollment (preset or custom,
    # chosen on the frontend). Pure metadata: editable at any time and never a
    # financial field, so editing it never touches the payment/redemption ledgers.
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

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
