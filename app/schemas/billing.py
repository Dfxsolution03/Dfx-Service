from datetime import date, datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, model_validator

Purity = Literal["9K", "14K", "18K", "20K", "22K", "24K"]
ChargeType = Literal["FIXED", "PER_GRAM", "PERCENTAGE"]
StockStatus = Literal["IN_STOCK", "SOLD", "INACTIVE"]
PaymentMethod = Literal["CASH", "CARD", "UPI", "BANK_TRANSFER", "OTHER"]
PaymentStatus = Literal["PAID", "PENDING", "PARTIAL"]


# =============================================================================
# Vendor
# =============================================================================

class VendorCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=150)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    gst_number: Optional[str] = Field(None, max_length=20)


class VendorUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=150)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    gst_number: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class VendorResponse(BaseModel):
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

    making_charge_type: ChargeType = "PERCENTAGE"
    making_charge_value: float = Field(0, ge=0)
    wastage_type: ChargeType = "PERCENTAGE"
    wastage_value: float = Field(0, ge=0)
    stone_charge_amount: float = Field(0, ge=0)
    other_charges_amount: float = Field(0, ge=0)
    # Required, no default — a GST/tax rate must be a conscious choice per
    # item, never silently assumed (see app/models/billing.py).
    tax_rate_percent: float = Field(..., ge=0, le=100)

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
    stone_charge_amount: Optional[float] = Field(None, ge=0)
    other_charges_amount: Optional[float] = Field(None, ge=0)
    tax_rate_percent: Optional[float] = Field(None, ge=0, le=100)

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
    stone_charge_amount: float
    other_charges_amount: float
    tax_rate_percent: float
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryItemListResponse(BaseModel):
    items: List[InventoryItemResponse]
    total: int


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
    stone_charge_amount: float = Field(0, ge=0)
    other_charges_amount: float = Field(0, ge=0)
    tax_rate_percent: float = Field(..., ge=0, le=100)

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
    stone_charge_amount: float
    other_charges_amount: float

    subtotal_before_tax: float
    tax_rate_percent: float
    tax_amount: float
    discount_amount: float
    final_amount: float


class SaleQuoteResponse(BaseModel):
    """Ephemeral — nothing is persisted. Backs the Selling screen's
    scan-and-preview step."""
    inventory_item: InventoryItemResponse
    breakdown: PriceBreakdown


class SaleCreateRequest(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=50)
    customer_id: Optional[str] = Field(None, max_length=50)
    customer_name: Optional[str] = Field(None, max_length=150)
    customer_phone: Optional[str] = Field(None, max_length=20)
    discount_amount: float = Field(0, ge=0)
    payment_method: PaymentMethod = "CASH"
    payment_status: PaymentStatus = "PAID"

    @model_validator(mode="after")
    def _customer_identified(self) -> "SaleCreateRequest":
        if not self.customer_id and not self.customer_name:
            raise ValueError("Provide either customer_id or customer_name to identify the buyer")
        return self


class SaleResponse(BaseModel):
    id: str
    tenant_id: str
    invoice_number: str
    inventory_item_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None

    product_code: str
    product_name: str
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
    stone_charge_amount: float
    other_charges_amount: float

    subtotal_before_tax: float
    tax_rate_percent: float
    tax_amount: float
    discount_amount: float
    final_amount: float
    payment_method: str
    payment_status: str

    # Internal-only fields — see this module's own note on InventoryItemResponse.purchase_cost.
    # Omitted for Staff-role callers.
    purchase_cost_snapshot: Optional[float] = None
    estimated_gross_margin: Optional[float] = None

    sale_timestamp: datetime
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class SaleListResponse(BaseModel):
    sales: List[SaleResponse]
    total: int
