from datetime import date
from sqlalchemy import String, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"
STATUS_CANCELLED = "CANCELLED"


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

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
    customer: Mapped["User"] = relationship("User")
    scheme: Mapped["Scheme"] = relationship("Scheme")
