from datetime import date, datetime
from typing import Optional, List, Literal, Dict
from pydantic import BaseModel, Field, model_validator

Purity = Literal["9K", "14K", "18K", "20K", "22K", "24K"]
ChargeType = Literal["FIXED", "PER_GRAM", "PERCENTAGE"]
StockStatus = Literal["IN_STOCK", "SOLD", "INACTIVE", "RETURNED_PENDING_INSPECTION", "DAMAGED"]
PaymentMethod = Literal["CASH", "CARD", "UPI", "BANK_TRANSFER", "OTHER"]
PaymentStatus = Literal["PAID", "PENDING", "PARTIAL"]
# The full stored vocabulary of Sale.payment_status: the three collection
# states above plus the two a return can produce. PaymentStatus stays as-is
# because sale CREATION can still only ask for one of the original three.
SalePaymentStatus = Literal["PAID", "PENDING", "PARTIAL", "REFUNDED", "PARTIALLY_REFUNDED"]
SaleStatus = Literal["COMPLETED", "RETURNED", "CANCELLED"]
ReturnType = Literal["RETURN", "CANCELLATION"]
InspectionOutcome = Literal["RESALABLE", "DAMAGED"]
PricingMode = Literal["AUTO", "HYBRID", "MANUAL"]
DefaultSource = Literal["VENDOR", "CATEGORY", "STORE", "NONE"]


class BillingDefaultFields(BaseModel):
    """Shared shape for the pre-fill-only default rules — Vendor, Category,
    and Store defaults all carry exactly this set of nullable fields.
    Unset (None) means "this tier has no opinion," letting the resolver fall
    through to the next tier. Never linked from a saved InventoryItem/Sale;
    only the resolved value is ever persisted there. Stone/other charges are
    deliberately NOT here — those are item-specific (e.g. a diamond's stone
    cost), not a store-wide/vendor-wide/category-wide default, so they're set
    per item/sale only (see InventoryItemCreateRequest/SaleCreateRequest)."""
    making_charge_type: Optional[ChargeType] = None
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_type: Optional[ChargeType] = None
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    tax_rate_percent: Optional[float] = Field(None, ge=0, le=100)
    default_pricing_mode: Optional[PricingMode] = None


# =============================================================================
# Vendor
# =============================================================================

class VendorCreateRequest(BillingDefaultFields):
    name: str = Field(..., min_length=2, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=150)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    gst_number: Optional[str] = Field(None, max_length=20)


class VendorUpdateRequest(BillingDefaultFields):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=150)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    gst_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class VendorResponse(BillingDefaultFields):
    id: str
    tenant_id: str
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    gst_number: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Category Pricing Default
# =============================================================================

class CategoryDefaultUpsertRequest(BillingDefaultFields):
    category: str = Field(..., min_length=1, max_length=100)


class CategoryDefaultResponse(BillingDefaultFields):
    id: str
    category: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Store (Tenant) Billing Defaults — bottom of the resolution chain
# =============================================================================

class StoreDefaultsUpdateRequest(BillingDefaultFields):
    pass


class StoreDefaultsResponse(BillingDefaultFields):
    class Config:
        from_attributes = True


# =============================================================================
# Default Resolution — read-only, used to pre-fill Inventory/Bulk forms
# =============================================================================

class ResolvedInventoryDefaults(BaseModel):
    """Field-by-field resolution result: each field's value comes from
    whichever tier (Vendor -> Category -> Store) set it first, independent
    of the others — never one tier winning wholesale. `sources` maps each
    field name to where its value came from, for UI badges only."""
    making_charge_type: Optional[ChargeType] = None
    making_charge_value: Optional[float] = None
    wastage_type: Optional[ChargeType] = None
    wastage_value: Optional[float] = None
    gold_profit_percent: Optional[float] = None
    tax_rate_percent: Optional[float] = None
    pricing_mode: Optional[PricingMode] = None
    sources: dict[str, DefaultSource] = Field(default_factory=dict)


# =============================================================================
# Inventory / Product Master
# =============================================================================

class InventoryItemCreateRequest(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=50)
    product_name: str = Field(..., min_length=2, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    huid: Optional[str] = Field(None, max_length=20)
    purity: Purity
    gross_weight_grams: float = Field(..., gt=0)
    net_gold_weight_grams: float = Field(..., gt=0)
    vendor_id: Optional[str] = Field(None, max_length=50)
    vendor_name: Optional[str] = Field(None, max_length=200)
    purchase_date: Optional[date] = None
    purchase_invoice_ref: Optional[str] = Field(None, max_length=100)
    purchase_rate_per_gram: Optional[float] = Field(None, ge=0)
    purchase_cost: Optional[float] = Field(None, ge=0)

    # None = not supplied → inherit from the Vendor -> Category -> Store
    # hierarchy at create time (see BillingService.create_item). An explicit 0
    # is a configured value and is kept as-is. type is paired with its value:
    # when the value is inherited, the resolved type comes with it.
    making_charge_type: Optional[ChargeType] = None
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_type: Optional[ChargeType] = None
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    # Absolute per-item charges (model columns NOT NULL default 0). Read
    # directly by BillingService.create_item, so they must exist on the request.
    stone_charge_amount: float = Field(0, ge=0)
    other_charges_amount: float = Field(0, ge=0)
    # Required, no default — a GST/tax rate must be a conscious choice per
    # item, never silently assumed (see app/models/billing.py).
    tax_rate_percent: float = Field(..., ge=0, le=100)
    pricing_mode: Optional[PricingMode] = None

    @model_validator(mode="after")
    def _net_not_more_than_gross(self) -> "InventoryItemCreateRequest":
        if self.net_gold_weight_grams > self.gross_weight_grams:
            raise ValueError("net_gold_weight_grams cannot exceed gross_weight_grams")
        return self


class InventoryItemUpdateRequest(BaseModel):
    """All fields optional — only present fields are changed. Rejected
    entirely by the service once the item's stock_status is SOLD, to keep a
    sold item's record exactly as it was at sale time (see BillingService)."""
    product_name: Optional[str] = Field(None, min_length=2, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    huid: Optional[str] = Field(None, max_length=20)
    purity: Optional[Purity] = None
    gross_weight_grams: Optional[float] = Field(None, gt=0)
    net_gold_weight_grams: Optional[float] = Field(None, gt=0)
    vendor_id: Optional[str] = Field(None, max_length=50)
    vendor_name: Optional[str] = Field(None, max_length=200)
    purchase_date: Optional[date] = None
    purchase_invoice_ref: Optional[str] = Field(None, max_length=100)
    purchase_rate_per_gram: Optional[float] = Field(None, ge=0)
    purchase_cost: Optional[float] = Field(None, ge=0)

    making_charge_type: Optional[ChargeType] = None
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_type: Optional[ChargeType] = None
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    stone_charge_amount: Optional[float] = Field(None, ge=0)
    other_charges_amount: Optional[float] = Field(None, ge=0)
    tax_rate_percent: Optional[float] = Field(None, ge=0, le=100)
    pricing_mode: Optional[PricingMode] = None

    stock_status: Optional[Literal["IN_STOCK", "INACTIVE"]] = None


class InventoryItemResponse(BaseModel):
    id: str
    tenant_id: str
    product_code: str
    product_name: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    huid: Optional[str] = None
    purity: str
    gross_weight_grams: float
    net_gold_weight_grams: float
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_invoice_ref: Optional[str] = None
    # Omitted entirely for Staff-role callers (see BillingService's response
    # builder) — purchase cost is commercially sensitive, same reasoning as
    # estimated_gross_margin on SaleResponse.
    purchase_rate_per_gram: Optional[float] = None
    purchase_cost: Optional[float] = None
    image_url: Optional[str] = None
    stock_status: str
    making_charge_type: str
    making_charge_value: float
    wastage_type: str
    wastage_value: float
    # Internal store margin — masked (None) for Staff-role callers, same
    # reasoning as purchase_cost above (Staff Financial Visibility baseline).
    gold_profit_percent: Optional[float] = None
    stone_charge_amount: float
    other_charges_amount: float
    tax_rate_percent: float
    pricing_mode: Optional[PricingMode] = None
    # Phase 3 — whether this item has been published to the catalogue.
    add_to_catalogue: bool = False
    # Phase 11 — the catalogue Product this physical piece is linked to (many
    # pieces -> one listing). NULL when unpublished. Lets Inventory link to the
    # listing without equating catalogue status to stock status.
    catalogue_product_id: Optional[str] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryItemListResponse(BaseModel):
    items: List[InventoryItemResponse]
    total: int
    total_gold_weight_grams: float = 0.0


# =============================================================================
# Bulk Purchase Entry — one vendor/date/invoice header, many products
# =============================================================================

class BulkPurchaseLineItem(BaseModel):
    """Same shape as InventoryItemCreateRequest minus the header fields
    (vendor/date/invoice), which are entered once for the whole purchase."""
    product_code: str = Field(..., min_length=1, max_length=50)
    product_name: str = Field(..., min_length=2, max_length=200)
    category: Optional[str] = Field(None, max_length=100)
    subcategory: Optional[str] = Field(None, max_length=100)
    huid: Optional[str] = Field(None, max_length=20)
    purity: Purity
    gross_weight_grams: float = Field(..., gt=0)
    net_gold_weight_grams: float = Field(..., gt=0)
    purchase_rate_per_gram: Optional[float] = Field(None, ge=0)
    purchase_cost: Optional[float] = Field(None, ge=0)
    making_charge_type: ChargeType = "PERCENTAGE"
    making_charge_value: float = Field(0, ge=0)
    wastage_type: ChargeType = "PERCENTAGE"
    wastage_value: float = Field(0, ge=0)
    gold_profit_percent: float = Field(0, ge=0, le=100)
    stone_charge_amount: float = Field(0, ge=0)
    other_charges_amount: float = Field(0, ge=0)
    tax_rate_percent: float = Field(..., ge=0, le=100)
    pricing_mode: Optional[PricingMode] = None

    @model_validator(mode="after")
    def _net_not_more_than_gross(self) -> "BulkPurchaseLineItem":
        if self.net_gold_weight_grams > self.gross_weight_grams:
            raise ValueError("net_gold_weight_grams cannot exceed gross_weight_grams")
        return self


class BulkPurchaseRequest(BaseModel):
    vendor_id: str = Field(..., min_length=1, max_length=50)
    purchase_date: date
    purchase_invoice_ref: Optional[str] = Field(None, max_length=100)
    items: List[BulkPurchaseLineItem] = Field(..., min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_codes(self) -> "BulkPurchaseRequest":
        codes = [i.product_code for i in self.items]
        if len(codes) != len(set(codes)):
            raise ValueError("product_code must be unique within a single purchase entry")
        return self


class BulkPurchaseResponse(BaseModel):
    items: List[InventoryItemResponse]


# =============================================================================
# Selling / Calculation
# =============================================================================

class PriceBreakdown(BaseModel):
    """The transparent, backend-computed price breakdown shown to staff
    before a sale is confirmed, and persisted verbatim onto the Sale row
    once confirmed. Never trusted from the client — always recomputed fresh
    server-side at both quote time and commit time."""
    purity: str
    net_gold_weight_grams: float
    gold_rate_24k: float
    gold_rate_purity_factor: float
    gold_rate_applied: float
    gold_rate_source: str
    gold_rate_effective_date: date
    gold_value_amount: float

    making_charge_type: str
    making_charge_value: float
    making_charge_amount: float
    wastage_type: str
    wastage_value: float
    wastage_amount: float
    # Internal store margin — masked (None) for Staff-role callers at the
    # response boundary; the engine always computes real values.
    gold_profit_percent: Optional[float] = None
    gold_profit_amount: Optional[float] = None
    stone_charge_amount: float
    other_charges_amount: float

    subtotal_before_tax: float
    gst_applied: bool
    tax_rate_percent: float
    tax_amount: float
    discount_amount: float
    final_amount: float


class SaleQuoteResponse(BaseModel):
    """Ephemeral — nothing is persisted. Backs the Selling screen's
    scan-and-preview step. profit_or_loss is backend-computed (subtotal
    before tax minus the item's historical purchase cost) so the frontend
    never re-derives it client-side; null for Staff callers, same as
    purchase_cost on inventory_item."""
    inventory_item: InventoryItemResponse
    breakdown: PriceBreakdown
    # profit_or_loss is the historical-cost view, kept for backward
    # compatibility; historical_profit_or_loss is the same figure under the
    # explicit name. Both null for Staff callers.
    profit_or_loss: Optional[float] = None
    # Two authoritative profit/loss views, both off net-of-GST selling value.
    # Historical: vs frozen purchase cost. Current gold value: vs today's gold
    # value (breakdown.gold_value_amount). Signed — negative is a loss.
    historical_profit_or_loss: Optional[float] = None
    historical_profit_margin_percent: Optional[float] = None
    current_gold_value_profit_or_loss: Optional[float] = None
    current_gold_value_margin_percent: Optional[float] = None
    # Phase 4 — direction only ("PROFIT"/"LOSS"/"BREAK_EVEN"), no rupee figure.
    # This is what a Staff caller sees (they get the word, never the number);
    # Admins get both this label and the numeric views above.
    profit_or_loss_label: Optional[str] = None


class SaleCreateRequest(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=50)
    customer_id: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = Field(None, max_length=150)
    customer_phone: Optional[str] = Field(None, max_length=20)
    discount_amount: float = Field(0, ge=0)
    # If provided, this becomes the actual final_amount charged (the
    # Admin's negotiated selling price) — discount_amount is then derived
    # as the gap below the backend-computed reference total, purely for
    # record-keeping. The reference total itself is never client-supplied.
    customer_price: Optional[float] = Field(None, ge=0)
    # Per-bill overrides — let the Admin adjust the bill in the Selling
    # screen before confirming. Omitted means "use the item's own value";
    # the InventoryItem row itself is never mutated by a sale.
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    gst_applied: bool = True
    # Informational only — if omitted, inferred as MANUAL when customer_price
    # is given, AUTO otherwise (see SaleService.create_sale). Never changes
    # how the amount is actually computed.
    pricing_mode: Optional[PricingMode] = None
    payment_method: PaymentMethod = "CASH"
    # The Admin's INTENT for this bill, not the stored status. The stored
    # Sale.payment_status is always derived from the ledger the backend writes
    # (see SaleService.create_sale):
    #   PAID    -> one ledger row for the full invoice amount
    #   PARTIAL -> one ledger row for initial_payment_amount (required)
    #   PENDING -> no ledger row at all
    payment_status: PaymentStatus = "PAID"
    # Required for PARTIAL, forbidden otherwise — a PARTIAL bill must record
    # the amount actually collected at the counter, never just wear the label.
    initial_payment_amount: Optional[float] = Field(None, gt=0)
    payment_reference_no: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _customer_identified(self) -> "SaleCreateRequest":
        if not self.customer_id and not self.customer_name:
            raise ValueError("Provide either customer_id or customer_name to identify the buyer")
        return self

    @model_validator(mode="after")
    def _initial_payment_matches_status(self) -> "SaleCreateRequest":
        if self.payment_status == "PARTIAL" and self.initial_payment_amount is None:
            raise ValueError(
                "initial_payment_amount is required for a PARTIAL sale — record the amount actually collected"
            )
        if self.payment_status != "PARTIAL" and self.initial_payment_amount is not None:
            raise ValueError(
                "initial_payment_amount applies only to a PARTIAL sale "
                "(PAID collects the full amount, PENDING collects nothing)"
            )
        return self


class SaleResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_number: str
    inventory_item_id: str
    customer_id: Optional[str] = None
    # Read from the customer record at response time, not stored on the sale —
    # the sale keeps its own customer_name/phone snapshot, this is the live
    # identity of the linked customer. NULL for a walk-in with no account.
    customer_code: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None

    product_code: str
    product_name: str
    # Read live from the linked inventory item (retained after sale), not stored
    # on the sale row. NULL for a sale whose item predates category capture.
    category: Optional[str] = None
    subcategory: Optional[str] = None
    vendor_name: Optional[str] = None
    huid: Optional[str] = None
    purity: str
    gross_weight_grams: float
    net_gold_weight_grams: float

    gold_rate_24k: float
    gold_rate_purity_factor: float
    gold_rate_applied: float
    gold_rate_source: str
    gold_rate_effective_date: date
    gold_value_amount: float

    making_charge_type: str
    making_charge_value: float
    making_charge_amount: float
    wastage_type: str
    wastage_value: float
    wastage_amount: float
    # Internal store margin — masked (None) for Staff-role callers at the
    # response boundary; the engine always computes real values.
    gold_profit_percent: Optional[float] = None
    gold_profit_amount: Optional[float] = None
    stone_charge_amount: float
    other_charges_amount: float

    subtotal_before_tax: float
    gst_applied: bool
    tax_rate_percent: float
    tax_amount: float
    discount_amount: float
    final_amount: float
    payment_method: str
    # Derived from the sale_payments ledger, never client-set — see
    # models/billing.py Sale.payment_status / SalePayment.
    payment_status: str
    amount_paid: float = 0
    amount_outstanding: float = 0
    pricing_mode: Optional[PricingMode] = None

    # Internal-only fields — see this module's own note on InventoryItemResponse.purchase_cost.
    # Omitted for Staff-role callers.
    purchase_cost_snapshot: Optional[float] = None
    estimated_gross_margin: Optional[float] = None
    # Phase 4 — direction-only label ("PROFIT"/"LOSS"/"BREAK_EVEN") of the gross
    # margin, shown to Staff (who never see the numeric estimated_gross_margin).
    profit_or_loss_label: Optional[str] = None

    sale_status: str = "COMPLETED"
    amount_refunded: float = 0.0
    # Present only when this sale has been reversed; None on a normal sale.
    sale_return: Optional["SaleReturnResponse"] = None

    sale_timestamp: datetime
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class SaleListResponse(BaseModel):
    sales: List[SaleResponse]
    total: int
    total_gold_weight_grams: float = 0.0
    # Sum of (final_amount - amount_paid) across the whole filtered set.
    total_outstanding: float = 0.0


# ─── Phase 4 — Quotation ("sample bill" that does not sell) ───

class QuotationCreateRequest(BaseModel):
    """Generate a quotation. Same pricing inputs as a real sale (so the printed
    figures match a future finalize), plus an OPTIONAL read-only scheme preview.
    Nothing is sold and no scheme balance is spent."""
    product_code: str = Field(..., min_length=1, max_length=50)
    customer_id: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = Field(None, max_length=150)
    customer_phone: Optional[str] = Field(None, max_length=20)
    discount_amount: float = Field(0, ge=0)
    customer_price: Optional[float] = Field(None, ge=0)
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    gst_applied: bool = True
    # Optional {enrollment_id: amount} the customer intends to apply from their
    # scheme balances. Previewed read-only (capped by available balance and by
    # the invoice); requires customer_id.
    scheme_amounts: Optional[Dict[str, float]] = None
    note: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def _customer_identified(self) -> "QuotationCreateRequest":
        if not self.customer_id and not self.customer_name:
            raise ValueError("Provide either customer_id or customer_name to identify the buyer")
        if self.scheme_amounts and not self.customer_id:
            raise ValueError("scheme_amounts requires an existing customer_id")
        return self


class QuotationSchemePreviewItem(BaseModel):
    enrollment_id: str
    enrollment_number: str
    requested_amount: float
    available_balance: float
    applied_amount: float


class QuotationResponse(BaseModel):
    id: str
    tenant_id: str
    quotation_number: str
    inventory_item_id: Optional[str] = None
    product_code: str
    product_name: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    breakdown: PriceBreakdown
    gst_applied: bool
    # invoice cost = breakdown.final_amount; scheme_amount_total previewed;
    # outstanding = final_amount - scheme_amount_total.
    final_amount: float
    scheme_amount_total: float = 0.0
    outstanding_amount: float
    scheme_preview: List[QuotationSchemePreviewItem] = Field(default_factory=list)
    # Profit/loss, gated exactly like a sale: number for Admin only, label for all.
    estimated_gross_margin: Optional[float] = None
    profit_or_loss_label: Optional[str] = None
    note: Optional[str] = None
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class QuotationListResponse(BaseModel):
    quotations: List[QuotationResponse]
    total: int


# =============================================================================
# Sale Payment Ledger
# =============================================================================

PaymentSource = Literal["COUNTER", "SCHEME_REDEMPTION", "GATEWAY", "REFUND"]


class SalePaymentCreateRequest(BaseModel):
    """One collection event against an existing invoice. There is no update or
    delete counterpart — the ledger is append-only."""
    amount: float = Field(..., gt=0, description="Must be > 0 and must not exceed the outstanding amount")
    payment_date: date
    payment_method: PaymentMethod
    reference_no: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = Field(None, max_length=500)


class SalePaymentResponse(BaseModel):
    id: str
    sale_id: str
    amount: float
    payment_date: date
    payment_method: str
    source: str
    reference_no: Optional[str] = None
    remarks: Optional[str] = None
    recorded_by: str
    recorded_by_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SalePaymentHistoryResponse(BaseModel):
    """Invoice payment position plus its full, permanent collection history."""
    sale_id: str
    invoice_number: str
    final_amount: float
    amount_paid: float
    amount_outstanding: float
    payment_status: str
    payments: List[SalePaymentResponse]


# =============================================================================
# Sale Return / Cancellation
# =============================================================================

class SaleReturnPreviewResponse(BaseModel):
    """Read-only financial impact of reversing one sale, so the Admin confirms
    against real backend figures instead of a number the browser computed.
    Every value here is derived from the immutable sale snapshot and its
    ledger; nothing is stored by asking for a preview."""
    sale_id: str
    invoice_number: str
    product_code: str
    product_name: str
    sale_status: str
    payment_status: str
    original_sale_amount: float
    amount_collected: float
    outstanding: float
    # What would be handed back if the Admin refunds in full: exactly what was
    # collected, never more. The outstanding balance is written off, not
    # refunded, because it was never collected.
    max_refundable: float
    outstanding_to_write_off: float
    current_stock_status: str
    resulting_stock_status: str
    can_return: bool
    blocked_reason: Optional[str] = None


class SaleReturnCreateRequest(BaseModel):
    """Reverse one sale. The refund amount is optional: omitted means refund
    everything that was actually collected (the normal case). A smaller value
    is allowed for a negotiated partial refund; a larger one is rejected
    backend-side, since the store cannot hand back money it never took."""
    return_type: ReturnType = "RETURN"
    reason: str = Field(..., min_length=3, max_length=500)
    refund_amount: Optional[float] = Field(
        None, ge=0, description="Omit to refund the full collected amount. Never exceeds it."
    )
    refund_method: Optional[PaymentMethod] = None
    refund_reference_no: Optional[str] = Field(None, max_length=100)
    refund_date: Optional[date] = Field(None, description="Business date of the refund; defaults to today (IST)")


class SaleReturnInspectionRequest(BaseModel):
    """The explicit second step: an item does NOT become sellable just because
    it came back. RESALABLE returns it to IN_STOCK; DAMAGED keeps it
    permanently out of sellable stock."""
    outcome: InspectionOutcome
    notes: Optional[str] = Field(None, max_length=500)


class SaleReturnResponse(BaseModel):
    id: str
    sale_id: str
    invoice_number: str
    inventory_item_id: str
    product_code: str
    return_type: str
    reason: str
    original_sale_amount: float
    amount_collected_at_return: float
    refund_amount: float
    outstanding_written_off: float
    # Scheme credit restored to the customer's enrollment by this return (0 for
    # a cash-only sale). Derived from the signed scheme_redemptions reversal
    # rows for this sale — never a fresh calculation.
    scheme_restored: float = 0.0
    refund_method: Optional[str] = None
    refund_reference_no: Optional[str] = None
    inspection_status: str
    inspection_notes: Optional[str] = None
    inspected_at: Optional[datetime] = None
    inspected_by: Optional[str] = None
    inspected_by_name: Optional[str] = None
    returned_at: datetime
    processed_by: str
    processed_by_name: Optional[str] = None
    current_stock_status: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Dashboard Billing Summary
# =============================================================================

class ReceivablesSummaryResponse(BaseModel):
    """Read-only receivables position over a period. Derived from the
    ledger-synced Sale columns; reversed sales are excluded (their balance was
    written off). total_invoiced == total_paid + total_outstanding within
    rounding tolerance."""
    period: str
    date_from: date
    date_to: date
    total_invoiced: float
    total_paid: float
    total_outstanding: float
    paid_count: int
    partial_count: int
    pending_count: int
    sale_count: int


class BusinessSummaryResponse(BaseModel):
    """Backs the Dashboard's Business History block — one real backend
    aggregation per selected period/custom range, never a client-side
    filter of a today-scoped payload."""
    period: str
    date_from: date
    date_to: date
    total_sales: float
    total_profit: Optional[float] = None
    total_loss: Optional[float] = None
    bill_count: int
    items_sold: int
    total_tax: float
    average_bill_value: float
    # Reversal-aware reporting. total_sales above is NET (reversed sales
    # excluded); these expose the reconciliation:
    # gross_sales - sales_returns == total_sales.
    gross_sales: float = 0.0
    sales_returns: float = 0.0
    return_count: int = 0
    total_refunded: float = 0.0
    current_gold_value_profit_or_loss: Optional[float] = None
    # Money-movement over the SAME period but on the payment-ledger date axis
    # (collection date, not sale date). Three distinct concepts, never merged:
    # cash actually collected, scheme-credit settlements, and refunds paid out.
    # Scheme redemption settles invoices but is never cash.
    cash_collected: float = 0.0
    scheme_redemption: float = 0.0
    refunds_paid: float = 0.0


class BillingPeriodSummary(BaseModel):
    """total_sales/total_profit/total_loss come straight from finalized Sale
    snapshots (final_amount / estimated_gross_margin) — never recomputed
    against today's gold rate. bill_count and items_sold are currently
    identical (one item per sale in this data model) but reported
    separately since that's a data-model detail, not a guarantee."""
    total_sales: float
    total_profit: Optional[float] = None
    total_loss: Optional[float] = None
    bill_count: int
    items_sold: int
    total_tax: float = 0.0
    avg_bill_value: float = 0.0
    gross_sales: float = 0.0
    sales_returns: float = 0.0
    return_count: int = 0
    total_refunded: float = 0.0
    # Phase A current-gold-value profit (net selling value minus frozen gold
    # value), signed aggregate over intact sales. Historical-cost profit stays
    # in total_profit/total_loss.
    current_gold_value_profit_or_loss: Optional[float] = None
    # Money movement (payment-ledger date axis) — same three distinct concepts
    # as business-summary: cash in, scheme settlement (never cash), refunds out.
    cash_collected: float = 0.0
    scheme_redemption: float = 0.0
    refunds_paid: float = 0.0
    # Payment-method split of cash_collected ONLY (e.g. {"CASH": 5000, "UPI":
    # 2000}). Scheme settlements and refunds are excluded upstream, so these
    # parts sum to cash_collected and scheme credit is never counted as money in.
    collected_by_method: Dict[str, float] = Field(default_factory=dict)
    # Receivables position over the period (active COMPLETED sales only).
    total_paid: float = 0.0
    total_outstanding: float = 0.0
    paid_count: int = 0
    partial_count: int = 0
    pending_count: int = 0
    sale_count: int = 0


class RecentSaleSummary(BaseModel):
    id: str
    invoice_number: str
    customer_name: Optional[str] = None
    product_code: str
    product_name: str
    final_amount: float
    profit_or_loss: Optional[float] = None
    sale_timestamp: datetime


class BillingDashboardSummaryResponse(BaseModel):
    today: BillingPeriodSummary
    this_month: BillingPeriodSummary
    today_gold_rate_24k: Optional[float] = None
    recent_sales: List[RecentSaleSummary]
    # Business History — the caller-selected period (via `period` or
    # date_from/date_to query params). Defaults to today (same as `today`
    # above) when no period is requested, so the field is always populated.
    selected_period: BillingPeriodSummary
    selected_period_label: str
    selected_date_from: date
    selected_date_to: date


# =============================================================================
# Bulk Inventory — live price preview (purchase-time, not a sale)
# =============================================================================

class PriceLinePreviewRequest(BaseModel):
    """Reuses BillingCalculationEngine.calculate() against a not-yet-saved
    row's current field values, so Bulk Inventory can show a live Suggested
    Price / Profit preview without duplicating any financial math in the
    frontend. purchase_cost is optional purely for the profit figure."""
    purity: Purity
    net_gold_weight_grams: float = Field(..., gt=0)
    making_charge_type: ChargeType = "PERCENTAGE"
    making_charge_value: float = Field(0, ge=0)
    wastage_type: ChargeType = "PERCENTAGE"
    wastage_value: float = Field(0, ge=0)
    gold_profit_percent: float = Field(0, ge=0, le=100)
    stone_charge_amount: float = Field(0, ge=0)
    other_charges_amount: float = Field(0, ge=0)
    tax_rate_percent: float = Field(0, ge=0, le=100)
    gst_applied: bool = True
    customer_price: Optional[float] = Field(None, ge=0)
    purchase_cost: Optional[float] = Field(None, ge=0)


class PriceLinePreviewResponse(BaseModel):
    breakdown: PriceBreakdown
    purchase_cost: Optional[float] = None
    profit_or_loss: Optional[float] = None


# SaleResponse.sale_return forward-references SaleReturnResponse, which is
# declared after it; resolve it once at import time so the first request never
# pays for (or trips over) a lazy rebuild.
SaleResponse.model_rebuild()


# =============================================================================
# Bill Drafts (unfinished bills) — server-side, multiple per user
# =============================================================================

class BillDraftCreateRequest(BaseModel):
    """Editable INPUTS of an unfinished bill. No computed money is accepted —
    every amount is recomputed by the backend on finalize."""
    product_code: str = Field(..., min_length=1, max_length=50)
    customer_id: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = Field(None, max_length=150)
    customer_phone: Optional[str] = Field(None, max_length=20)
    customer_query: Optional[str] = Field(None, max_length=150)
    customer_price: Optional[float] = Field(None, ge=0)
    gst_applied: bool = True
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    discount_amount: float = Field(0, ge=0)
    payment_method: PaymentMethod = "CASH"
    payment_status: PaymentStatus = "PAID"
    initial_payment: Optional[float] = Field(None, ge=0)
    # {enrollment_id: amount} — selection only, never applied until finalize.
    scheme_amounts: Optional[Dict[str, float]] = None
    note: Optional[str] = Field(None, max_length=255)


class BillDraftUpdateRequest(BaseModel):
    """All optional — partial update of an OPEN draft."""
    product_code: Optional[str] = Field(None, min_length=1, max_length=50)
    customer_id: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = Field(None, max_length=150)
    customer_phone: Optional[str] = Field(None, max_length=20)
    customer_query: Optional[str] = Field(None, max_length=150)
    customer_price: Optional[float] = Field(None, ge=0)
    gst_applied: Optional[bool] = None
    making_charge_value: Optional[float] = Field(None, ge=0)
    wastage_value: Optional[float] = Field(None, ge=0)
    gold_profit_percent: Optional[float] = Field(None, ge=0, le=100)
    discount_amount: Optional[float] = Field(None, ge=0)
    payment_method: Optional[PaymentMethod] = None
    payment_status: Optional[PaymentStatus] = None
    initial_payment: Optional[float] = Field(None, ge=0)
    scheme_amounts: Optional[Dict[str, float]] = None
    note: Optional[str] = Field(None, max_length=255)


class BillDraftFinalizeRequest(BaseModel):
    """Finalize an OPEN draft into exactly one Sale. otp_code is required only
    when the draft carries scheme_amounts (scheme redemption is OTP-gated, same
    as the live sell screen)."""
    otp_code: Optional[str] = Field(None, min_length=4, max_length=10)


class BillDraftResponse(BaseModel):
    id: str
    tenant_id: str
    created_by: str
    status: str
    product_code: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_query: Optional[str] = None
    customer_price: Optional[float] = None
    gst_applied: bool
    making_charge_value: Optional[float] = None
    wastage_value: Optional[float] = None
    gold_profit_percent: Optional[float] = None
    discount_amount: float
    payment_method: str
    payment_status: str
    initial_payment: Optional[float] = None
    scheme_amounts: Optional[Dict[str, float]] = None
    note: Optional[str] = None
    finalized_sale_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BillDraftListItem(BaseModel):
    """Lean row for the Unfinished Bills list."""
    id: str
    status: str
    product_code: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    created_by: str
    note: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True
