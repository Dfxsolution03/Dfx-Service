from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    actor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_entity: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    before_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
