from datetime import date
from sqlalchemy import String, Float, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class GoldRate(Base, TimestampMixin):
    __tablename__ = "gold_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "effective_date", name="uq_gold_rates_tenant_effective_date"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rate_24k: Mapped[float] = mapped_column(Float, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant")
