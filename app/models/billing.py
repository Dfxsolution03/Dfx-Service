from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Float, Date, DateTime, Boolean, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

# Bill draft (unfinished bill) lifecycle statuses. A draft is NEVER a Sale — it
# lives in its own table and is excluded from every financial query.
BILL_DRAFT_OPEN = "OPEN"
BILL_DRAFT_FINALIZED = "FINALIZED"
BILL_DRAFT_DISCARDED = "DISCARDED"
BILL_DRAFT_STATUSES = [BILL_DRAFT_OPEN, BILL_DRAFT_FINALIZED, BILL_DRAFT_DISCARDED]


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
    # Unprefixed, matching CategoryPricingDefault/TenantBillingDefaults and
    # BillingDefaultFields exactly (only default_pricing_mode keeps the
    # prefix, same as those two tables) — a previous prefixed naming here
    # silently broke persistence, since the shared service/schema field
    # names never matched these columns.
    making_charge_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    making_charge_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wastage_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    wastage_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gold_profit_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Deprecated as a DEFAULT-tier field (stone/other charges are item-specific,
    # not a vendor/category/store default) — columns kept for existing data,
    # no longer read/written by BillingDefaultFields/_DEFAULT_FIELD_NAMES.
    stone_charge_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    other_charges_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tax_rate_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
    gold_profit_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
    gold_profit_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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

    # Store margin on the gold-value portion only (never applied to the
    # whole invoice) — percent, resolved the same VENDOR->CATEGORY->STORE
    # way as making/wastage.
    gold_profit_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0)

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

    # Phase 3 — whether this item has been published to the customer catalogue.
    # Set True by the publish workflow (CatalogueService.publish_inventory_item);
    # the authoritative link is Product.inventory_item_id. Default False so all
    # pre-existing inventory stays inventory-only and needs no backfill.
    add_to_catalogue: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

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
    gold_profit_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    gold_profit_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
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
    # payment_method is the method of the FIRST collection only (kept for
    # backward compatibility and single-payment invoices); the authoritative
    # per-collection method lives on each SalePayment row.
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="CASH")
    # DERIVED, never client-supplied — recomputed from the SalePayment ledger
    # inside the same transaction as every payment insert (see
    # SalePaymentService._recompute). Denormalised purely so Sales History can
    # filter/sort by status without aggregating the ledger per row. The ledger
    # is always the source of truth; this column is a cache of it.
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PAID", index=True)
    # Same derived/denormalised contract as payment_status: SUM of this sale's
    # SalePayment rows. Outstanding is always final_amount - amount_paid.
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # Same derived/denormalised contract as amount_paid, for the refund side:
    # SUM of this sale's REFUND ledger rows. Only a return writes it.
    amount_refunded: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # The SALE lifecycle (SALE_STATUSES), strictly separate from payment_status.
    # COMPLETED until a return/cancellation reverses the sale; every other
    # column on this row stays exactly as it was written at sale time — the
    # snapshot is never rewritten to hide a reversed sale.
    sale_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="COMPLETED", index=True
    )

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


# Where the money for a collection came from. COUNTER covers every manual
# Admin-recorded collection (cash/card/UPI/bank/cheque at the counter).
# SCHEME_REDEMPTION and GATEWAY are reserved for later phases — a scheme
# redemption settles an invoice without being fresh cash, and a gateway
# payment originates externally; both must stay distinguishable from counter
# cash so the dashboard can report collections correctly.
PAYMENT_SOURCE_COUNTER = "COUNTER"
PAYMENT_SOURCE_SCHEME_REDEMPTION = "SCHEME_REDEMPTION"
PAYMENT_SOURCE_GATEWAY = "GATEWAY"
# A refund paid back to the customer. Stored on the SAME append-only ledger as
# collections, with a NEGATIVE amount, so the ledger sums to the net cash
# position of the invoice and no collection row is ever mutated or deleted.
PAYMENT_SOURCE_REFUND = "REFUND"


class SalePayment(Base, TimestampMixin):
    """
    Billing System — the authoritative payment ledger for jewellery sales.
    One row per collection event against one Sale/invoice.

    APPEND-ONLY. Nothing in the Admin workflow updates or deletes a row here:
    a ₹10,000 collection followed by a ₹5,000 collection is two permanent
    rows, never one mutated row. Sale.amount_paid/payment_status are derived
    caches of this table, recomputed transactionally on every insert.

    Deliberately separate from payment.Payment, which is the scheme-
    contribution ledger (enrollment_id NOT NULL). The two are different
    financial concepts — money paid INTO a savings scheme vs. money collected
    AGAINST an invoice — and are kept as distinct tables rather than one
    polymorphic table.
    """
    __tablename__ = "sale_payments"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Business date of the collection (what the Admin reports on), distinct
    # from created_at (when the row was keyed in). Dashboard collections in
    # the next phase aggregate on this column, never on Sale.sale_timestamp.
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default=PAYMENT_SOURCE_COUNTER)
    # Cheque number, UPI txn id, bank reference — free text, optional.
    reference_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    remarks: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Which scheme enrollment funded this row. Set ONLY on
    # source=SCHEME_REDEMPTION rows, so a redemption can never be mistaken for
    # counter cash and the enrollment's remaining balance stays derivable from
    # this ledger. NULL on every ordinary collection and on refunds.
    enrollment_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("scheme_enrollments.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    # Who collected it — never nullable, this is an audited financial record.
    recorded_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    sale: Mapped["Sale"] = relationship("Sale")


class SaleReturn(Base, TimestampMixin):
    """
    Billing System — the immutable reversal record for one Sale.

    A return NEVER edits the original invoice. The Sale row keeps its invoice
    number, product snapshot, gold rate, gold-rate effective date, making and
    wastage charges, gold profit, GST, customer price, purchase-cost snapshot
    and original margin untouched; only its derived sale_status/payment_status/
    amount_refunded caches move. The financial and inventory consequences of
    the reversal live here, in a separate row, so the original transaction
    stays auditable exactly as it was recorded.

    One sale carries one inventory item in this data model, so at most ONE
    SaleReturn can exist per sale — enforced by a unique constraint on sale_id,
    which is also the hard stop against double-returning the same invoice.

    Money: the refund itself is a negative row on sale_payments (the existing
    collection ledger, source=REFUND). This table records the reversal's
    reasoning and its frozen financial impact — what the invoice was, what had
    actually been collected, what was handed back, and what outstanding
    balance was written off. Nothing here is recomputed later.
    """
    __tablename__ = "sale_returns"
    __table_args__ = (
        UniqueConstraint("sale_id", name="uq_sale_returns_sale_id"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalised from the Sale at return time purely so an audit/report never
    # has to join back to prove which invoice and item were reversed.
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    inventory_item_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)

    return_type: Mapped[str] = mapped_column(String(20), nullable=False, default="RETURN")
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    # Frozen financial impact of THIS reversal.
    original_sale_amount: Mapped[float] = mapped_column(Float, nullable=False)
    amount_collected_at_return: Mapped[float] = mapped_column(Float, nullable=False)
    refund_amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Balance the customer still owed and is no longer liable for. Never
    # refunded — it was never collected.
    outstanding_written_off: Mapped[float] = mapped_column(Float, nullable=False)
    refund_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    refund_reference_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Inspection outcome. PENDING while the item sits in
    # RETURNED_PENDING_INSPECTION; RESALABLE once an Admin puts it back into
    # IN_STOCK; DAMAGED if it is kept permanently out of sellable stock.
    inspection_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    inspection_notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    inspected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    inspected_by: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    returned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
    sale: Mapped["Sale"] = relationship("Sale")


class BillDraft(Base, TimestampMixin):
    """An unfinished bill (draft) held server-side so an Admin/Staff can save
    several in-progress bills, resume them on any device, and finalize later.

    A draft is NOT a Sale and lives in its own table: no dashboard, report,
    sales-history, inventory-SOLD, scheme-balance or collection query ever reads
    it, so a draft can never move a financial figure. Only stored values are the
    Admin's editable INPUTS — never a computed money figure; every amount is
    recomputed by the backend on finalize, so a stale draft can never resurrect
    a stale price or gold rate. Finalization creates exactly one Sale (reusing
    SaleService) and flips this row to FINALIZED with finalized_sale_id set; the
    row is kept for audit and never reopened."""
    __tablename__ = "bill_drafts"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Owner (creator). Admin sees all tenant drafts; Staff only their own.
    created_by: Mapped[str] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BILL_DRAFT_OPEN, index=True)

    # Item reference (never locked/marked SOLD by a draft) — code drives resume.
    product_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Buyer — walk-in (name/phone only) or an existing customer.
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    customer_query: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    # Editable pricing INPUTS only (no computed money is stored).
    customer_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gst_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    making_charge_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wastage_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gold_profit_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    payment_method: Mapped[str] = mapped_column(String(20), nullable=False, default="CASH")
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PAID")
    initial_payment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Admin's chosen scheme amounts: {enrollment_id: amount}. Selection only —
    # never applied to a balance until finalize re-validates it live.
    scheme_amounts: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Set once, at finalize.
    finalized_sale_id: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("sales.id", ondelete="SET NULL"), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship("Tenant")
