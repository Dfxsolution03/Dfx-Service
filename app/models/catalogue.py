from datetime import date
from typing import Optional, List
from sqlalchemy import String, Text, Boolean, Integer, Float, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        # A single inventory item publishes to at most ONE catalogue product per
        # tenant — this makes publishing idempotent and blocks duplicate products
        # for the same source item. NULLs are distinct in Postgres, so standalone
        # manual products (inventory_item_id IS NULL) are unaffected.
        UniqueConstraint("tenant_id", "inventory_item_id", name="uq_products_tenant_inventory_item"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Phase 3 — catalogue sub-category (product header + admin filter). Free
    # text, same "plain string, no closed enum" convention as category/purity.
    sub_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
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
    # Making-charge discount shown on the customer catalogue card (mobile reads
    # making_charge_discount_label). Both nullable/additive — no existing row
    # is affected.
    making_charge_discount_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    making_charge_discount_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Per-tag display colour overrides for the Admin catalogue UI, stored as a
    # JSON object string ({"BESTSELLER": "#C9A227", ...}) — same "plain string
    # column, (de)serialised at the service boundary" convention `tags` and
    # CatalogueDesign.canvas_json already follow. Added to production by
    # emergency SQL and brought under Alembic control by revision 00ec5a9151da.
    tag_colors: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # Soft delete, same is_active-flag convention as Scheme/Branch — no
    # dedicated deleted_at column exists anywhere else in this codebase.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # ─── Phase 3 — Inventory → Catalogue link + pricing snapshot ───
    # The inventory item this product was published from. NULL for standalone
    # manual products. ON DELETE SET NULL: deleting the inventory item never
    # deletes or breaks the catalogue product (catalogue status is independent
    # of inventory status). Unique per tenant (see __table_args__).
    inventory_item_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # SELLING_COST  -> price is the server-calculated (BillingCalculationEngine)
    #                  snapshot; never client-editable.
    # CATALOGUE_COST-> price is an admin-entered manual value.
    # NULL          -> legacy/standalone manual product (treated as manual).
    pricing_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # The server-calculated selling cost captured at publish time (SELLING_COST
    # mode only). Kept alongside `price` so the computed figure is auditable even
    # if `price` is later hand-edited. Never auto-refreshed on gold-rate change.
    computed_selling_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # The date the price snapshot was taken (gold-rate effective date for
    # SELLING_COST) — shown in the admin list as product price history.
    price_effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

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
