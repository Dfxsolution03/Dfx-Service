from sqlalchemy import String, Float, Integer, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


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
