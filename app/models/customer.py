from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Float, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin


class KYCRecord(Base, TimestampMixin):
    __tablename__ = "kyc_records"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'PAN', 'Aadhaar', 'Passport'
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Pending", nullable=False)  # 'Pending', 'Verified', 'Rejected'
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", backref="kyc_records")


class UserAddress(Base, TimestampMixin):
    __tablename__ = "user_addresses"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    house: Mapped[str] = mapped_column(String(255), nullable=False)
    street: Mapped[str] = mapped_column(String(255), nullable=False)
    area: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    pincode: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(100), default="India", nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="Home", nullable=False)  # 'Home', 'Work', 'Other'
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", backref="addresses")


class KycDocument(Base, TimestampMixin):
    """
    Phase 6A / Module 31 — KYC document metadata storage. Distinct from the
    pre-existing KYCRecord (which tracks a single doc_type/doc_number
    identity-verification submission and its Pending/Verified/Rejected
    review workflow) — this table records *uploaded document files*
    (document_type + a caller-supplied document_url), with no storage
    provider integration wired in this pass (explicitly deferred per spec,
    see POST /customer/kyc/documents). verification_status is independent
    per document, not synced with KYCRecord.status or User.kyc_status.
    """
    __tablename__ = "kyc_documents"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    document_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User")


class CustomerCodeSequence(Base, TimestampMixin):
    """One counter row per tenant, backing the DFX-CUST-NNNNNN customer code.

    Deliberately NOT the "random suffix + unique constraint" convention used by
    Sale.invoice_number and SchemeEnrollment.enrollment_number: the customer
    code is required to be sequential and human-readable, which a random suffix
    cannot provide.

    "SELECT MAX(customer_code) + 1" is unsafe — two concurrent registrations in
    the same tenant read the same maximum and generate the same code. Instead
    the allocator takes a row-level lock on this tenant's counter
    (SELECT ... FOR UPDATE) inside the caller's transaction, so a second
    concurrent allocation for the SAME tenant blocks until the first commits
    and therefore reads the already-incremented value. Different tenants lock
    different rows and never contend. The unique constraint on
    (users.tenant_id, users.customer_code) is the database-level backstop if
    any future code path bypasses this allocator.
    """
    __tablename__ = "customer_code_sequences"

    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    # Highest number already handed out. The next customer gets last_value + 1.
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", backref="branches")
