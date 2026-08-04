from typing import Optional, List
from sqlalchemy import String, Text, Boolean, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Product Studio redesign — real jewellery commercial fields, added
    # additively (nullable, no backfill required) alongside the existing
    # Module 20 fields, per an explicit confirmed decision to extend rather
    # than fake these in the frontend. Purity kept as free text (e.g. "22K",
    # "916", "18K") — same "plain string, no closed enum" convention as
    # category/sku, since jewellery purity marks vary by region/product type
    # and inventing a fixed list would be guessing at a business rule.
    purity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Money field: plain Float, matching this codebase's existing convention
    # (see Payment.amount) — not Decimal.
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_grams: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Comma-separated, same "one plain string column, no new structure"
    # preference this codebase already applies elsewhere — split/joined into
    # a List[str] at the schema/service boundary (see CatalogueService).
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Soft delete, same is_active-flag convention as Scheme/Branch — no
    # dedicated deleted_at column exists anywhere else in this codebase.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    images: Mapped[List["ProductImage"]] = relationship(
        "ProductImage", back_populates="product", cascade="all, delete-orphan",
        order_by="ProductImage.display_order",
    )


class ProductImage(Base, TimestampMixin):
    """
    One row per stored image *variant*. Uploading an image creates exactly one
    ORIGINAL row; every enhancement/template/export path (once AI providers
    are wired in a future module) creates a brand-new row of a different
    variant_type pointing back at its source via source_image_id — the
    original row is never updated or overwritten, per Module 20's explicit
    requirement. This table only records *metadata* (where the file lives);
    the actual bytes live wherever StorageProvider put them (see
    app/services/storage_service.py).
    """
    __tablename__ = "product_images"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ORIGINAL | ENHANCED | BACKGROUND_REMOVED | TEMPLATE | INSTAGRAM |
    # WHATSAPP | PDF | THUMBNAIL — kept as a plain indexed string (not a DB
    # enum) so a future module can add new variant types without a migration,
    # matching this codebase's existing preference for Literal-validated
    # strings over DB-level enums (see payment_status/payment_method).
    variant_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # Which image this variant was derived from. NULL for ORIGINAL rows
    # (they have no source — they *are* the source). Self-referential so a
    # product with multiple original photos keeps each one's derived
    # variants correctly attributed.
    source_image_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("product_images.id", ondelete="CASCADE"), nullable=True, index=True
    )
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Gallery ordering, scoped per (product_id, variant_type) by convention —
    # only ORIGINAL rows are user-orderable today (drag-to-reorder in the
    # gallery); derived variants keep whatever order they were created in.
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Product Studio redesign — which real-world shot angle this ORIGINAL is
    # (Front/Back/Side/Top/45°/Lifestyle/Macro), set at upload time. Same
    # "plain indexed string, not a DB enum" convention as variant_type —
    # optional and only meaningful for ORIGINAL rows; derived variants
    # inherit no particular meaning from it.
    shot_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    # Only ever true for at most one ORIGINAL row per product — enforced in
    # CatalogueService, not at the DB level (same approach as every other
    # "only one active X" business rule in this codebase, e.g. default
    # address).
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    product: Mapped["Product"] = relationship("Product", back_populates="images")


class CatalogueDesign(Base, TimestampMixin):
    """
    Jewellery Catalogue & Marketing Studio — Phase B. One row per SAVED
    version of a product's Design Studio canvas. Every save inserts a new
    row — there is no update path, matching this table to the exact
    "never overwrite, always insert a new version" convention ProductImage
    already established (see that model's own docstring). Listing every row
    for a product, newest first, *is* its version history; "Restore" and
    "Duplicate" both just insert another new row cloned from an existing
    one's canvas_json (see CatalogueService) rather than mutating anything.

    canvas_json is stored as plain Text with manual (de)serialization at the
    repository/service boundary — the same pattern this codebase already
    uses for AuditLog.before_state/after_state — rather than introducing
    SQLAlchemy's native JSON/JSONB column type as a first for this codebase.
    """
    __tablename__ = "catalogue_designs"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Self-referential, same lineage pattern as ProductImage.source_image_id —
    # NULL for an originally-authored version; set when this row was created
    # via Restore or Duplicate, pointing at the version it was cloned from.
    source_design_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("catalogue_designs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    # 1, 2, 3... per product, assigned at save time (CatalogueService) —
    # a plain human-readable ordinal over this product's own rows, not a
    # global counter.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    canvas_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Which of the 10 preset templates (if any) this version started from —
    # informational only, purely for the UI to show "based on: Luxury White".
    template_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    product: Mapped["Product"] = relationship("Product")
