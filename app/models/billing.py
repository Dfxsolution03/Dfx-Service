from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Float, Date, DateTime, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Vendor(Base, TimestampMixin):
    """A jewellery business's gold/finished-goods supplier. Purchases and
    inventory link here so purchase history stays queryable/filterable by
    vendor; deactivating a vendor (is_active=False) never touches past
    InventoryItem rows — they keep their own vendor_id/vendor_name snapshot."""
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    gst_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Billing defaults — pre-fill sources only (see BillingDefaultsService's
    # field-by-field resolver). All nullable: an unset field here simply
    # means "this vendor has no opinion," falling through to Category then
    # Store defaults. Never referenced from a saved InventoryItem/Sale —
    # those always snapshot the resolved value, never a link back here.
    default_making_charge_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_making_charge_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_wastage_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_wastage_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_stone_charge_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_other_charges_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_tax_rate_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_pricing_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")


class CategoryPricingDefault(Base, TimestampMixin):
    """One row per (tenant, category) — category stays the same free-text
    value already used on InventoryItem.category (no enum introduced, so
    existing data is unaffected). Same pre-fill-only, nullable-field
    convention as Vendor's default_* columns above."""
    __tablename__ = "category_pricing_defaults"
    __table_args__ = (
        UniqueConstraint("tenant_id", "category", name="uq_category_pricing_defaults_tenant_category"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)

    making_charge_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    making_charge_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wastage_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    wastage_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stone_charge_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    other_charges_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tax_rate_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_pricing_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")


class TenantBillingDefaults(Base, TimestampMixin):
    """Store-level fallback — one row per tenant (same one-row-per-tenant
    shape as TenantPricingConfig, but that table is exclusively about
    gold-rate markup mode; this is the bottom of the making/wastage/GST
    resolution chain, kept separate rather than overloading it)."""
    __tablename__ = "tenant_billing_defaults"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    making_charge_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    making_charge_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wastage_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    wastage_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stone_charge_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    other_charges_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tax_rate_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_pricing_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")


class InventoryItem(Base, TimestampMixin):
    """
    Billing System — Inventory / Product Master. One row per finished
    jewellery piece bought from a vendor (this business buys finished goods,
    it does not manufacture from raw gold — see Selling's own docstring).
    product_code is the key used later to pull this exact item up during a
    sale (scan/enter code -> load product -> calculate -> sell).

    Purchase fields (vendor/date/invoice/cost) are historical record-keeping
    only — Selling never reads purchase_cost to price a sale; it exists so a
    Sale row can later snapshot it for an internal margin estimate (see
    Sale.estimated_gross_margin).

    purity is a closed Literal (see app/core/constants.py PURITY_CHOICES,
    validated at the schema layer) — unlike catalogue.Product.purity's free
    text, Billing's calculation engine must look purity up in the karat/24K
    conversion table, so it can't be an arbitrary string here.
    """
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_code", name="uq_inventory_items_tenant_product_code"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    huid: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    purity: Mapped[str] = mapped_column(String(10), nullable=False)
    gross_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)
    net_gold_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)

    # Nullable FK so pre-existing rows (created before Vendor existed) and
    # free-text-only entries keep working — vendor_name is always the
    # display snapshot (copied from Vendor.name at purchase time), vendor_id
    # is the queryable/filterable link.
    vendor_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vendor_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purchase_invoice_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Historical cost only — never used as, or confused with, a selling
    # price. See this model's own docstring.
    purchase_rate_per_gram: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    purchase_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    image_storage_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # IN_STOCK -> SOLD (permanent, set only by SaleService on a completed
    # sale) or -> INACTIVE (manual admin retire, e.g. data-entry mistake /
    # returned-to-vendor — never used for a sold item).
    stock_status: Mapped[str] = mapped_column(
        String(20), default="IN_STOCK", nullable=False, index=True
    )

    # Making Charge / Wastage — configurable rule stored on the product, per
    # the explicit "do not hard-code one business rule" requirement. type is
    # one of CHARGE_CALCULATION_TYPES; value's unit depends on type (rupees
    # for FIXED, rupees/gram for PER_GRAM, percent for PERCENTAGE).
    making_charge_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PERCENTAGE")
    making_charge_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    wastage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PERCENTAGE")
    wastage_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # Stone Charge / Other Charges — flat rupee amounts (spec gives no
    # calculation-type variants for these two, unlike Making/Wastage).
    stone_charge_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    other_charges_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # GST/tax — required, no default, so a rate is never silently assumed
    # for a real sale (see schemas/billing.py's InventoryItemCreateRequest).
    tax_rate_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # AUTO/HYBRID/MANUAL — a label carried onto the item so Selling knows
    # whether to expect a customer_price override. NULL on pre-existing rows
    # is treated as AUTO everywhere (see schemas/billing.py), so old
    # inventory needs no backfill.
    pricing_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")


class Sale(Base, TimestampMixin):
    """
    Billing System — one row per completed sale/invoice. Every pricing input
    (gold rate, purity factor, making/wastage/stone/other charges, tax) is
    snapshotted here at the moment of sale, exactly as SaleService computed
    it — so this row never changes when tomorrow's live gold rate changes,
    when the source InventoryItem is edited, or when tax rules change later.
    This table is the permanent historical record; InventoryItem only ever
    reflects current stock state.
    """
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_sales_tenant_invoice_number"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    inventory_item_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("inventory_items.id"), nullable=False, index=True
    )

    # Customer — an existing tenant User (Customer role) when picked from
    # the system, or a plain walk-in name/phone when not. Never required to
    # be a registered account (counter sales must stay fast).
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Product snapshot — copied from InventoryItem at sale time, independent
    # of any later edit to that row.
    product_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    vendor_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    huid: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    purity: Mapped[str] = mapped_column(String(10), nullable=False)
    gross_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)
    net_gold_weight_grams: Mapped[float] = mapped_column(Float, nullable=False)

    # Gold rate snapshot — the exact rate this sale was priced at, and where
    # it came from (see GoldRateService.get_customer_today_rate's fallback
    # chain), so a historical invoice is fully explainable after the fact.
    gold_rate_24k: Mapped[float] = mapped_column(Float, nullable=False)
    gold_rate_purity_factor: Mapped[float] = mapped_column(Float, nullable=False)
    gold_rate_applied: Mapped[float] = mapped_column(Float, nullable=False)
    gold_rate_source: Mapped[str] = mapped_column(String(50), nullable=False)
    gold_rate_effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    gold_value_amount: Mapped[float] = mapped_column(Float, nullable=False)

    making_charge_type: Mapped[str] = mapped_column(String(20), nullable=False)
    making_charge_value: Mapped[float] = mapped_column(Float, nullable=False)
    making_charge_amount: Mapped[float] = mapped_column(Float, nullable=False)
    wastage_type: Mapped[str] = mapped_column(String(20), nullable=False)
    wastage_value: Mapped[float] = mapped_column(Float, nullable=False)
    wastage_amount: Mapped[float] = mapped_column(Float, nullable=False)
    stone_charge_amount: Mapped[float] = mapped_column(Float, nullable=False)
    other_charges_amount: Mapped[float] = mapped_column(Float, nullable=False)

    subtotal_before_tax: Mapped[float] = mapped_column(Float, nullable=False)
    # Whether GST was applied to this sale — stored per-sale so a historical
    # invoice's mode never changes even if the item's configured tax rate is
    # edited later. When False, tax_rate_percent/tax_amount are both 0 for
    # this row (no invented rate — GST is simply skipped, not recalculated).
    gst_applied: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tax_rate_percent: Mapped[float] = mapped_column(Float, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    final_amount: Mapped[float] = mapped_column(Float, nullable=False)

    # Editable commercial fields — recorded on the finalized bill, never
    # feed back into the deterministic price calculation itself.
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="CASH")
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PAID")

    # Snapshot of which pricing mode produced this sale's final_amount — see
    # InventoryItem.pricing_mode's docstring for what the label means.
    pricing_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Internal only (see schemas/billing.py — never labeled "net profit",
    # never returned to a Staff-role caller). NULL when the source item had
    # no purchase_cost on record.
    purchase_cost_snapshot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_gross_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    sale_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    inventory_item: Mapped["InventoryItem"] = relationship("InventoryItem")
