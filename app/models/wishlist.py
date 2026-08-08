from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WishlistItem(Base, TimestampMixin):
    """
    Phase 6A / Module 31 — Customer Wishlist. Unique constraint on
    (user_id, product_id) prevents duplicate wishlist entries for the same
    customer, per the spec — enforced at the DB level (a ConflictException
    409 is raised in the service before that constraint would ever fire,
    but the constraint is the real backstop against a race).
    """
    __tablename__ = "wishlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_wishlist_user_product"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product")
