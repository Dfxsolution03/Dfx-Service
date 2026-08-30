import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    PURITY_KARATS,
    ROLE_ADMIN,
    ROLE_SUPERADMIN,
    ROLE_CUSTOMER,
    SALE_STATUS_COMPLETED,
    SALE_STATUS_RETURNED,
    SALE_STATUS_CANCELLED,
    PAYMENT_STATUS_REFUNDED,
    PAYMENT_STATUS_PARTIALLY_REFUNDED,
    RETURN_TYPE_CANCELLATION,
    STOCK_STATUS_IN_STOCK,
    STOCK_STATUS_SOLD,
    STOCK_STATUS_DAMAGED,
    STOCK_STATUS_RETURNED_PENDING_INSPECTION,
    INSPECTION_PENDING,
    INSPECTION_RESALABLE,
    INSPECTION_DAMAGED,
)
from app.models.auth import User, Role
from app.core.security import hash_password
from app.models.billing import (
    Vendor,
    CategoryPricingDefault,
    TenantBillingDefaults,
    InventoryItem,
    Sale,
    SalePayment,
    SaleReturn,
    PAYMENT_SOURCE_COUNTER,
    PAYMENT_SOURCE_REFUND,
    PAYMENT_SOURCE_SCHEME_REDEMPTION,
    BillDraft,
    BILL_DRAFT_OPEN,
    BILL_DRAFT_FINALIZED,
    BILL_DRAFT_DISCARDED,
    Quotation,
)
from app.repositories.billing_repository import (
    VendorRepository,
    CategoryDefaultRepository,
    TenantBillingDefaultsRepository,
    InventoryRepository,
    SaleRepository,
    SalePaymentRepository,
    SaleReturnRepository,
    BillDraftRepository,
    QuotationRepository,
)
from app.repositories.enrollment_repository import EnrollmentRepository, SchemeRedemptionRepository
from app.models.enrollment import (
    SchemeRedemption,
    REDEEMABLE_STATUSES,
    STATUS_ACTIVE as ENR_ACTIVE,
    STATUS_CLOSED as ENR_CLOSED,
    STATUS_REDEEMED as ENR_REDEEMED,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.customer_repository import CustomerRepository
from app.services.storage_service import get_storage_provider
from app.services.goldrate_service import GoldRateService, IST
from app.exceptions.base import (
    ResourceNotFoundException,
    ForbiddenException,
    ValidationException,
    ConflictException,
)
from app.schemas.billing import (
    VendorCreateRequest,
    VendorUpdateRequest,
    VendorResponse,
    CategoryDefaultUpsertRequest,
    CategoryDefaultResponse,
    StoreDefaultsUpdateRequest,
    StoreDefaultsResponse,
    ResolvedInventoryDefaults,
    InventoryItemCreateRequest,
    InventoryItemUpdateRequest,
    InventoryItemResponse,
    InventoryItemListResponse,
    BillDraftCreateRequest,
    BillDraftUpdateRequest,
    BillDraftFinalizeRequest,
    BillDraftResponse,
    BillDraftListItem,
    BulkPurchaseRequest,
    BulkPurchaseResponse,
    PriceBreakdown,
    PriceLinePreviewRequest,
    PriceLinePreviewResponse,
    SaleQuoteResponse,
    SafePriceGuidance,
    SafePriceReduction,
    SaleCreateRequest,
    SaleResponse,
    SaleListResponse,
    SalePaymentCreateRequest,
    SalePaymentResponse,
    SalePaymentHistoryResponse,
    SaleReturnCreateRequest,
    SaleReturnInspectionRequest,
    SaleReturnPreviewResponse,
    SaleReturnResponse,
    BillingPeriodSummary,
    RecentSaleSummary,
    BillingDashboardSummaryResponse,
    BusinessSummaryResponse,
    ReceivablesSummaryResponse,
    QuotationCreateRequest,
    QuotationResponse,
    QuotationListResponse,
    QuotationSchemePreviewItem,
)

_DEFAULT_FIELD_NAMES = [
    "making_charge_type", "making_charge_value", "wastage_type", "wastage_value",
    "gold_profit_percent", "tax_rate_percent", "default_pricing_mode",
]


def _is_privileged(current_user: User) -> bool:
    """Admin/SuperAdmin see commercially sensitive fields (purchase cost,
    estimated gross margin); Staff do not."""
    return current_user.role.name in (ROLE_ADMIN, ROLE_SUPERADMIN)


def _charge_amount(charge_type: str, value: float, net_gold_weight_grams: float, gold_value_amount: float) -> float:
    if charge_type == "FIXED":
        return value
    if charge_type == "PER_GRAM":
        return value * net_gold_weight_grams
    if charge_type == "PERCENTAGE":
        return gold_value_amount * (value / 100)
    raise ValidationException(f"Unknown charge calculation type '{charge_type}'")


def _round2(value: float) -> float:
    return round(value, 2)


def _pl_label(value):
    """Direction-only label for a profit/loss figure — the WORD a Staff user
    sees instead of the rupee number (Phase 4). None when there is no figure."""
    if value is None:
        return None
    if value > _MONEY_EPSILON:
        return "PROFIT"
    if value < -_MONEY_EPSILON:
        return "LOSS"
    return "BREAK_EVEN"


# Money tolerance for float comparisons. Amounts are stored as Float and
# rounded to paise, so an invoice settled by several collections can land a
# fraction of a paise away from its total; treating anything within half a
# paise as equal keeps a genuinely settled invoice from being stuck PARTIAL.
_MONEY_EPSILON = 0.005


def _derive_payment_status(final_amount: float, amount_paid: float) -> str:
    """The ONLY place a sale's payment status is decided. Driven purely by the
    ledger total vs. the invoice total — a client-supplied status is never
    trusted (see SalePaymentService.record_payment / SaleService.create_sale).

    paid == 0            -> PENDING
    0 < paid < total     -> PARTIAL
    paid >= total        -> PAID
    """
    if amount_paid <= _MONEY_EPSILON:
        return "PENDING"
    if amount_paid >= final_amount - _MONEY_EPSILON:
        return "PAID"
    return "PARTIAL"


def _outstanding_of(sale: Sale) -> float:
    """Never negative — overpayment is rejected at the point of collection, so
    a negative figure here would mean corrupt data, not a refund owed.

    A reversed sale outstands nothing: on a return the unpaid balance is
    written off (recorded on the SaleReturn row), so the customer is no longer
    liable for it. The sale's own final_amount/amount_paid columns are left
    untouched — only this derivation knows the balance is closed."""
    if (sale.sale_status or SALE_STATUS_COMPLETED) != SALE_STATUS_COMPLETED:
        return 0.0
    return _round2(max(0.0, (sale.final_amount or 0) - (sale.amount_paid or 0)))


class BillingCalculationEngine:
    """The one place a sale's price is computed — used identically by the
    ephemeral quote (SaleService.get_quote) and the persisted sale
    (SaleService.create_sale), so a confirmed sale is always priced by
    exactly the same math the staff member previewed. Deterministic: same
    item + same gold rate + same discount always produces the same
    breakdown."""

    @staticmethod
    def realized_profit_or_loss(
        final_amount: float,
        tax_rate_percent: float,
        gst_applied: bool,
        purchase_cost: Optional[float],
    ) -> Optional[float]:
        """The ONE definition of profit/loss, used by the quote preview, the
        line preview, and the persisted Sale alike.

        Profit = what the business actually keeps (the realized customer
        price with GST backed out, since GST is collected for the government
        and was never revenue) MINUS the item's frozen historical
        acquisition cost. Deliberately NOT `subtotal_before_tax - cost`:
        that reference subtotal ignores a negotiated customer_price, so a
        deeply discounted bill still looked profitable.

        The historical cost is whatever was snapshotted at purchase time and
        is never re-derived from today's gold rate.
        """
        if purchase_cost is None:
            return None
        return _round2(
            BillingCalculationEngine._net_selling_value(final_amount, tax_rate_percent, gst_applied)
            - purchase_cost
        )

    @staticmethod
    def _net_selling_value(final_amount: float, tax_rate_percent: float, gst_applied: bool) -> float:
        """Customer selling value with GST backed out — the ONE basis both
        profit views compare against. GST is collected for the government and
        was never revenue, so both historical-cost and today's-gold-value
        profit use this figure, never the GST-inclusive final_amount."""
        if gst_applied and tax_rate_percent:
            return final_amount / (1 + tax_rate_percent / 100)
        return final_amount

    @staticmethod
    def profit_views(breakdown: "PriceBreakdown", purchase_cost: Optional[float]) -> dict:
        """The two business profit/loss views, both off the same net selling
        value (see _net_selling_value):

          historical:      net selling value - frozen historical purchase cost
          current-gold:    net selling value - today's gold value

        "Today's gold value" is breakdown.gold_value_amount (net gold weight x
        the applied rate) — the same current-gold figure the calculator already
        produces, never re-derived. Margins are signed: negative is a loss.
        Historical view is None when no cost snapshot exists.
        """
        net = BillingCalculationEngine._net_selling_value(
            breakdown.final_amount, breakdown.tax_rate_percent, breakdown.gst_applied
        )
        gold_value = breakdown.gold_value_amount
        current_pl = _round2(net - gold_value)
        current_margin = _round2(current_pl / gold_value * 100) if gold_value else None

        hist_pl = None
        hist_margin = None
        if purchase_cost is not None:
            hist_pl = _round2(net - purchase_cost)
            hist_margin = _round2(hist_pl / purchase_cost * 100) if purchase_cost else None

        return {
            "historical_profit_or_loss": hist_pl,
            "historical_profit_margin_percent": hist_margin,
            "current_gold_value_profit_or_loss": current_pl,
            "current_gold_value_margin_percent": current_margin,
        }

    @staticmethod
    def _component_native_to(charge_type, amount_after, net_gold_weight, gold_value):
        """Given a target rupee amount for a making/wastage line, return the
        native value in that line's own unit (₹ FIXED, ₹/g PER_GRAM, % of gold
        value PERCENTAGE)."""
        if charge_type == "FIXED":
            return _round2(amount_after)
        if charge_type == "PER_GRAM":
            return _round2(amount_after / net_gold_weight) if net_gold_weight else 0.0
        if charge_type == "PERCENTAGE":
            return _round2(amount_after / gold_value * 100) if gold_value else 0.0
        return None

    @staticmethod
    def safe_price_guidance(full: "PriceBreakdown", purchase_cost: Optional[float], requested_price: Optional[float]) -> Optional[dict]:
        """Historical-cost safe-price guidance for a customer-requested price.

        Safety boundary is HISTORICAL COST P/L >= 0 (break-even) per item:
        net selling value (GST backed out) must cover the frozen purchase cost.
        `full` is the breakdown at the item's full charges with NO discount and
        NO customer_price override — i.e. the natural asking price.

        Returns None when there is no purchase cost to judge against (guidance
        cannot be computed without it). The rupee break-even / min-safe figures
        it returns are Admin-only; the response layer masks them for Staff.

        Reductions to reach a lower requested price are allocated across the
        adjustable lines in a fixed order — Gold Profit, then Wastage, then
        Making (trim pure store margin before customer-facing craftsmanship
        charges). Any allocation that reaches the price without crossing
        break-even is equally valid; this order is a deterministic UX choice,
        not a profit rule. No line is ever cut below 0.
        """
        if purchase_cost is None:
            # No fake fallback: without a vendor cost there is no honest
            # break-even to judge against. Return an explicit blocking state so
            # the UI shows a clear "Purchase Cost Required" message and the sale
            # cannot be safely finalized (create_sale rejects it too).
            return {
                "status": "PURCHASE_COST_REQUIRED",
                "is_loss": False,
                "requested_price": _round2(requested_price) if requested_price is not None else None,
                "minimum_safe_price": None,
                "achievable_price": None,
                "reductions": [],
                "message": "Purchase Cost must be entered on this item before it can be sold.",
            }
        factor = (1 + full.tax_rate_percent / 100) if full.gst_applied else 1.0
        break_even_final = _round2(purchase_cost * factor)
        p_full = full.final_amount  # natural asking price (no discount)

        if requested_price is None:
            return {
                "status": "SAFE",
                "is_loss": False,
                "requested_price": None,
                "minimum_safe_price": break_even_final,
                "achievable_price": None,
                "reductions": [],
                "message": "No customer price entered.",
            }

        eps = _MONEY_EPSILON
        # LOSS: requested is below break-even — impossible without losing money.
        if requested_price < break_even_final - eps:
            return {
                "status": "NOT_ACHIEVABLE",
                "is_loss": True,
                "requested_price": _round2(requested_price),
                "minimum_safe_price": break_even_final,
                "achievable_price": break_even_final,
                "reductions": [],
                "message": "Requested price cannot be offered without a loss.",
            }
        # At or above the natural asking price — already safe, no cut needed.
        if requested_price >= p_full - eps:
            return {
                "status": "SAFE",
                "is_loss": False,
                "requested_price": _round2(requested_price),
                "minimum_safe_price": break_even_final,
                "achievable_price": _round2(requested_price),
                "reductions": [],
                "message": "Requested price is profitable.",
            }

        # ADJUSTABLE: trim charges to bring the asking price down to requested,
        # never below break-even.
        drop_final = p_full - requested_price
        drop_pretax = drop_final / factor
        gold_value = full.gold_value_amount
        net_w = full.net_gold_weight_grams
        remaining = drop_pretax
        reductions = []
        # (component, current pre-tax amount, type, current native value)
        lines = [
            ("GOLD_PROFIT", full.gold_profit_amount, "PERCENTAGE", full.gold_profit_percent),
            ("WASTAGE", full.wastage_amount, full.wastage_type, full.wastage_value),
            ("MAKING", full.making_charge_amount, full.making_charge_type, full.making_charge_value),
        ]
        for name, amount, ctype, cvalue in lines:
            if remaining <= eps:
                break
            if amount <= eps:
                continue
            cut = min(remaining, amount)
            remaining = _round2(remaining - cut)
            amount_after = _round2(amount - cut)
            if name == "GOLD_PROFIT":
                to_value = _round2(amount_after / gold_value * 100) if gold_value else 0.0
            else:
                to_value = BillingCalculationEngine._component_native_to(ctype, amount_after, net_w, gold_value)
            reductions.append({
                "component": name,
                "charge_type": ctype,
                "reduce_amount": _round2(cut),           # ₹ off the pre-tax line
                "from_value": _round2(cvalue) if cvalue is not None else None,
                "to_value": to_value,
            })
        # If charge cuts alone cannot cover the drop (requested is below the
        # all-charges-zero floor) the balance is an explicit discount — the sale
        # is still >= break-even so it is safe, just not fully expressible as
        # charge trims.
        residual_discount = _round2(remaining * factor) if remaining > eps else 0.0
        return {
            "status": "ADJUSTABLE",
            "is_loss": False,
            "requested_price": _round2(requested_price),
            "minimum_safe_price": break_even_final,
            "achievable_price": _round2(requested_price),
            "reductions": reductions,
            "residual_discount": residual_discount,
            "message": "Reduce the charges below to reach the requested price.",
        }

    @staticmethod
    def calculate(
        item: InventoryItem,
        rate_24k: float,
        rate_source: str,
        rate_effective_date: date,
        discount_amount: float,
        gst_applied: bool = True,
        customer_price: Optional[float] = None,
        making_charge_value: Optional[float] = None,
        wastage_value: Optional[float] = None,
        gold_profit_percent: Optional[float] = None,
        making_charge_type: Optional[str] = None,
        wastage_type: Optional[str] = None,
    ) -> PriceBreakdown:
        """The *_value/percent overrides let the Admin adjust the bill in the
        Selling screen before confirming it, without mutating the
        InventoryItem. Omitted (None) means "use the item's own value".

        A value override MUST travel with its own charge type: when a
        making/wastage value is overridden, its type is taken from the paired
        *_type override (falling back to the item's type only when the caller
        omitted the type). This prevents a ₹500 FIXED override from being
        applied as 500% against an item whose stored type is PERCENTAGE."""
        karat = PURITY_KARATS.get(item.purity)
        if karat is None:
            raise ValidationException(f"Unsupported purity '{item.purity}'")
        purity_factor = karat / 24.0
        gold_rate_applied = rate_24k * purity_factor
        gold_value_amount = item.net_gold_weight_grams * gold_rate_applied

        eff_making_value = item.making_charge_value if making_charge_value is None else making_charge_value
        eff_wastage_value = item.wastage_value if wastage_value is None else wastage_value
        eff_gold_profit_percent = (
            item.gold_profit_percent if gold_profit_percent is None else gold_profit_percent
        )
        eff_making_type = making_charge_type if making_charge_type is not None else item.making_charge_type
        eff_wastage_type = wastage_type if wastage_type is not None else item.wastage_type

        making_charge_amount = _charge_amount(
            eff_making_type, eff_making_value, item.net_gold_weight_grams, gold_value_amount
        )
        wastage_amount = _charge_amount(
            eff_wastage_type, eff_wastage_value, item.net_gold_weight_grams, gold_value_amount
        )
        # Store margin on the GOLD VALUE portion only — never applied to
        # making/wastage/stone/other or the whole invoice.
        gold_profit_amount = gold_value_amount * (eff_gold_profit_percent / 100)

        subtotal_before_tax = (
            gold_value_amount
            + gold_profit_amount
            + making_charge_amount
            + wastage_amount
            + item.stone_charge_amount
            + item.other_charges_amount
        )
        effective_tax_rate = item.tax_rate_percent if gst_applied else 0.0
        tax_amount = subtotal_before_tax * (effective_tax_rate / 100)
        payable_before_discount = subtotal_before_tax + tax_amount

        if discount_amount < 0:
            raise ValidationException("discount_amount cannot be negative")

        if customer_price is not None:
            # The Admin's negotiated price IS the final amount — discount is
            # derived from it (for record-keeping) rather than the other way
            # round. A price above the reference total is honored as-is
            # (no discount, no invented "premium" field).
            final_amount = customer_price
            discount_amount = max(0.0, _round2(payable_before_discount - customer_price))
        else:
            if discount_amount > payable_before_discount:
                raise ValidationException("discount_amount cannot exceed the payable amount")
            final_amount = payable_before_discount - discount_amount

        return PriceBreakdown(
            purity=item.purity,
            net_gold_weight_grams=item.net_gold_weight_grams,
            gold_rate_24k=_round2(rate_24k),
            gold_rate_purity_factor=purity_factor,
            gold_rate_applied=_round2(gold_rate_applied),
            gold_rate_source=rate_source,
            gold_rate_effective_date=rate_effective_date,
            gold_value_amount=_round2(gold_value_amount),
            making_charge_type=eff_making_type,
            making_charge_value=eff_making_value,
            making_charge_amount=_round2(making_charge_amount),
            wastage_type=eff_wastage_type,
            wastage_value=eff_wastage_value,
            wastage_amount=_round2(wastage_amount),
            gold_profit_percent=eff_gold_profit_percent,
            gold_profit_amount=_round2(gold_profit_amount),
            stone_charge_amount=_round2(item.stone_charge_amount),
            other_charges_amount=_round2(item.other_charges_amount),
            subtotal_before_tax=_round2(subtotal_before_tax),
            gst_applied=gst_applied,
            tax_rate_percent=effective_tax_rate,
            tax_amount=_round2(tax_amount),
            discount_amount=_round2(discount_amount),
            final_amount=_round2(final_amount),
        )


class VendorService:
    @staticmethod
    async def list_vendors(db: AsyncSession, current_user: User, search: Optional[str] = None) -> list:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        vendors = await VendorRepository.list_by_tenant(db, current_user.tenant_id, search)
        return [VendorResponse.model_validate(v) for v in vendors]

    @staticmethod
    async def create_vendor(db: AsyncSession, current_user: User, req: VendorCreateRequest) -> VendorResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        vendor = Vendor(
            id=f"vnd_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            name=req.name,
            contact_person=req.contact_person,
            phone=req.phone,
            email=req.email,
            address=req.address,
            gst_number=req.gst_number,
            is_active=True,
            created_by=current_user.id,
            **{f: getattr(req, f) for f in _DEFAULT_FIELD_NAMES},
        )
        await VendorRepository.create(db, vendor)
        await db.commit()
        await db.refresh(vendor)
        return VendorResponse.model_validate(vendor)

    @staticmethod
    async def update_vendor(
        db: AsyncSession, current_user: User, vendor_id: str, req: VendorUpdateRequest
    ) -> VendorResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        vendor = await VendorRepository.get_by_id(db, vendor_id, current_user.tenant_id)
        if not vendor:
            raise ResourceNotFoundException(f"Vendor '{vendor_id}' not found")
        fields = ["name", "contact_person", "phone", "email", "address", "gst_number", "is_active"]
        fields += _DEFAULT_FIELD_NAMES
        for field in fields:
            val = getattr(req, field, None)
            if val is not None:
                setattr(vendor, field, val)
        await db.commit()
        await db.refresh(vendor)
        return VendorResponse.model_validate(vendor)

    @staticmethod
    async def _get_owned_vendor(db: AsyncSession, current_user: User, vendor_id: str) -> Vendor:
        vendor = await VendorRepository.get_by_id(db, vendor_id, current_user.tenant_id)
        if not vendor:
            raise ResourceNotFoundException(f"Vendor '{vendor_id}' not found")
        return vendor


class BillingDefaultsService:
    """Store/Category/Vendor default management + the single field-by-field
    resolver every inventory-entry path (single create, bulk create) uses to
    pre-fill a form. Resolution is display-time only — nothing here is ever
    referenced from a saved InventoryItem/Sale, which always snapshot the
    resolved value, never a link back to a default row."""

    @staticmethod
    async def get_store_defaults(db: AsyncSession, current_user: User) -> StoreDefaultsResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        row = await TenantBillingDefaultsRepository.get_by_tenant(db, current_user.tenant_id)
        return StoreDefaultsResponse.model_validate(row) if row else StoreDefaultsResponse()

    @staticmethod
    async def update_store_defaults(
        db: AsyncSession, current_user: User, req: StoreDefaultsUpdateRequest
    ) -> StoreDefaultsResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        row = await TenantBillingDefaultsRepository.get_by_tenant(db, current_user.tenant_id)
        if not row:
            row = TenantBillingDefaults(
                id=f"tbd_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                created_by=current_user.id,
                **{f: getattr(req, f) for f in _DEFAULT_FIELD_NAMES},
            )
            await TenantBillingDefaultsRepository.create(db, row)
        else:
            for field in _DEFAULT_FIELD_NAMES:
                val = getattr(req, field, None)
                if val is not None:
                    setattr(row, field, val)
        await db.commit()
        await db.refresh(row)
        return StoreDefaultsResponse.model_validate(row)

    @staticmethod
    async def list_category_defaults(db: AsyncSession, current_user: User) -> list:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rows = await CategoryDefaultRepository.list_by_tenant(db, current_user.tenant_id)
        return [CategoryDefaultResponse.model_validate(r) for r in rows]

    @staticmethod
    async def upsert_category_default(
        db: AsyncSession, current_user: User, req: CategoryDefaultUpsertRequest
    ) -> CategoryDefaultResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        row = await CategoryDefaultRepository.get_by_category(db, current_user.tenant_id, req.category)
        if not row:
            row = CategoryPricingDefault(
                id=f"cpd_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                category=req.category,
                created_by=current_user.id,
                **{f: getattr(req, f) for f in _DEFAULT_FIELD_NAMES},
            )
            await CategoryDefaultRepository.create(db, row)
        else:
            for field in _DEFAULT_FIELD_NAMES:
                val = getattr(req, field, None)
                if val is not None:
                    setattr(row, field, val)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException(f"A pricing default for category '{req.category}' already exists")
        await db.refresh(row)
        return CategoryDefaultResponse.model_validate(row)

    @staticmethod
    async def resolve_defaults(
        db: AsyncSession, current_user: User, vendor_id: Optional[str], category: Optional[str]
    ) -> ResolvedInventoryDefaults:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        # STORE defaults are the ONLY active pricing-default source. The Vendor
        # and Category tiers are retired: their tables/data are kept for
        # compatibility, but pricing resolution never falls through to them.
        # vendor_id/category are accepted (callers still pass them) but ignored.
        store_default = await TenantBillingDefaultsRepository.get_by_tenant(db, current_user.tenant_id)

        tiers = [("STORE", store_default)]

        def resolve_pair(type_attr: str, value_attr: str):
            for source, tier in tiers:
                if tier is None:
                    continue
                t, v = getattr(tier, type_attr, None), getattr(tier, value_attr, None)
                if t is not None and v is not None:
                    return t, v, source
            return None, None, "NONE"

        def resolve_single(attr: str):
            for source, tier in tiers:
                if tier is None:
                    continue
                v = getattr(tier, attr, None)
                if v is not None:
                    return v, source
            return None, "NONE"

        making_type, making_value, making_src = resolve_pair("making_charge_type", "making_charge_value")
        wastage_type, wastage_value, wastage_src = resolve_pair("wastage_type", "wastage_value")
        gold_profit, gold_profit_src = resolve_single("gold_profit_percent")
        tax, tax_src = resolve_single("tax_rate_percent")
        mode, mode_src = resolve_single("default_pricing_mode")

        return ResolvedInventoryDefaults(
            making_charge_type=making_type,
            making_charge_value=making_value,
            wastage_type=wastage_type,
            wastage_value=wastage_value,
            gold_profit_percent=gold_profit,
            tax_rate_percent=tax,
            pricing_mode=mode,
            sources={
                "making_charge": making_src,
                "wastage": wastage_src,
                "gold_profit_percent": gold_profit_src,
                "tax_rate_percent": tax_src,
                "pricing_mode": mode_src,
            },
        )


class InventoryService:
    @staticmethod
    def _build_response(item: InventoryItem, current_user: User) -> InventoryItemResponse:
        provider = get_storage_provider()
        privileged = _is_privileged(current_user)
        return InventoryItemResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            product_code=item.product_code,
            product_name=item.product_name,
            category=item.category,
            subcategory=item.subcategory,
            huid=item.huid,
            purity=item.purity,
            gross_weight_grams=item.gross_weight_grams,
            net_gold_weight_grams=item.net_gold_weight_grams,
            vendor_id=item.vendor_id,
            vendor_name=item.vendor_name,
            purchase_date=item.purchase_date,
            purchase_invoice_ref=item.purchase_invoice_ref,
            purchase_rate_per_gram=item.purchase_rate_per_gram if privileged else None,
            purchase_cost=item.purchase_cost if privileged else None,
            image_url=provider.get_public_url(item.image_storage_path) if item.image_storage_path else None,
            stock_status=item.stock_status,
            making_charge_type=item.making_charge_type,
            making_charge_value=item.making_charge_value,
            wastage_type=item.wastage_type,
            wastage_value=item.wastage_value,
            gold_profit_percent=item.gold_profit_percent if privileged else None,
            stone_charge_amount=item.stone_charge_amount,
            other_charges_amount=item.other_charges_amount,
            tax_rate_percent=item.tax_rate_percent,
            pricing_mode=item.pricing_mode,
            add_to_catalogue=item.add_to_catalogue,
            catalogue_product_id=item.catalogue_product.id if item.catalogue_product else None,
            created_by=item.created_by,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    async def list_items(
        db: AsyncSession,
        current_user: User,
        page: int,
        limit: int,
        search: Optional[str],
        stock_status: Optional[str],
        category: Optional[str],
        vendor_id: Optional[str] = None,
        subcategory: Optional[str] = None,
        purity: Optional[str] = None,
    ) -> InventoryItemListResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        items, total, total_gold_weight_grams = await InventoryRepository.list_by_tenant(
            db, current_user.tenant_id, page, limit, search, stock_status, category, vendor_id,
            subcategory, purity,
        )
        return InventoryItemListResponse(
            items=[InventoryService._build_response(i, current_user) for i in items],
            total=total,
            total_gold_weight_grams=total_gold_weight_grams,
        )

    @staticmethod
    async def get_item(db: AsyncSession, current_user: User, item_id: str) -> InventoryItemResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        if not item:
            raise ResourceNotFoundException(f"Inventory item '{item_id}' not found")
        return InventoryService._build_response(item, current_user)

    @staticmethod
    async def _resolve_vendor_snapshot(db: AsyncSession, current_user: User, vendor_id, vendor_name):
        """If a real Vendor is linked, its current name is the snapshot
        (kept in sync at purchase time); otherwise fall back to whatever
        free-text vendor_name was supplied (pre-Vendor-model convention)."""
        if not vendor_id:
            return None, vendor_name
        vendor = await VendorRepository.get_by_id(db, vendor_id, current_user.tenant_id)
        if not vendor:
            raise ResourceNotFoundException(f"Vendor '{vendor_id}' not found")
        return vendor.id, vendor.name

    @staticmethod
    async def create_item(
        db: AsyncSession, current_user: User, req: InventoryItemCreateRequest
    ) -> InventoryItemResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        # Data-boundary enforcement: an item can never be created without a
        # product image (schema requires it; guard again in case of a
        # non-schema caller). Existing imageless items are untouched.
        if not (req.image_storage_path or "").strip():
            raise ValidationException("A product image is required to create an inventory item.")

        existing = await InventoryRepository.get_by_product_code(
            db, req.product_code, current_user.tenant_id
        )
        if existing:
            raise ConflictException(f"Product code '{req.product_code}' is already in use")

        vendor_id, vendor_name = await InventoryService._resolve_vendor_snapshot(
            db, current_user, req.vendor_id, req.vendor_name
        )

        # Resolve inherited pricing fields server-side (Vendor -> Category ->
        # Store, field-by-field) so the item is snapshotted with the ACTUAL
        # applicable values, never a form-default 0. A value supplied on the
        # request (including an explicit 0) is kept; only None inherits.
        resolved = await BillingDefaultsService.resolve_defaults(
            db, current_user, vendor_id, req.category
        )
        if req.making_charge_value is not None:
            making_type, making_value = req.making_charge_type, req.making_charge_value
        else:
            making_type, making_value = resolved.making_charge_type, resolved.making_charge_value
        if req.wastage_value is not None:
            wastage_type, wastage_value = req.wastage_type, req.wastage_value
        else:
            wastage_type, wastage_value = resolved.wastage_type, resolved.wastage_value
        gold_profit = (
            req.gold_profit_percent if req.gold_profit_percent is not None
            else resolved.gold_profit_percent
        )
        # Nothing configured at any level — refuse rather than store a
        # misleading 0. The columns are NOT NULL, so an unresolved field has no
        # honest value to persist.
        missing = [
            name for name, val in (
                ("making charge", making_value), ("making charge type", making_type),
                ("wastage", wastage_value), ("wastage type", wastage_type),
                ("gold profit", gold_profit),
            ) if val is None
        ]
        if missing:
            raise ValidationException(
                "No value supplied and no Vendor/Category/Store default configured for: "
                + ", ".join(missing)
                + ". Configure a default or provide the value."
            )

        item_id = f"iv_{uuid.uuid4().hex[:12]}"
        item = InventoryItem(
            id=item_id,
            tenant_id=current_user.tenant_id,
            product_code=req.product_code,
            product_name=req.product_name,
            category=req.category,
            subcategory=req.subcategory,
            huid=req.huid,
            purity=req.purity,
            gross_weight_grams=req.gross_weight_grams,
            net_gold_weight_grams=req.net_gold_weight_grams,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            purchase_date=req.purchase_date,
            purchase_invoice_ref=req.purchase_invoice_ref,
            purchase_rate_per_gram=req.purchase_rate_per_gram,
            purchase_cost=req.purchase_cost,
            image_storage_path=req.image_storage_path,
            stock_status="IN_STOCK",
            making_charge_type=making_type,
            making_charge_value=making_value,
            wastage_type=wastage_type,
            wastage_value=wastage_value,
            gold_profit_percent=gold_profit,
            stone_charge_amount=req.stone_charge_amount,
            other_charges_amount=req.other_charges_amount,
            tax_rate_percent=req.tax_rate_percent,
            pricing_mode=req.pricing_mode,
            created_by=current_user.id,
        )
        await InventoryRepository.create(db, item)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INVENTORY_ITEM_CREATE",
            target_entity="inventory_items",
            target_id=item_id,
            before_state=None,
            after_state={"product_code": req.product_code, "purity": req.purity},
        )

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException(f"Product code '{req.product_code}' is already in use")

        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        return InventoryService._build_response(item, current_user)

    @staticmethod
    async def update_item(
        db: AsyncSession, current_user: User, item_id: str, req: InventoryItemUpdateRequest
    ) -> InventoryItemResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        if not item:
            raise ResourceNotFoundException(f"Inventory item '{item_id}' not found")
        if item.stock_status == "SOLD":
            raise ConflictException("A sold inventory item's record cannot be edited")

        before_state = {"stock_status": item.stock_status}
        fields = [
            "product_name", "category", "subcategory", "huid", "purity",
            "gross_weight_grams", "net_gold_weight_grams",
            "purchase_date", "purchase_invoice_ref", "purchase_rate_per_gram", "purchase_cost",
            "making_charge_type", "making_charge_value", "wastage_type", "wastage_value",
            "gold_profit_percent", "stone_charge_amount", "other_charges_amount", "tax_rate_percent",
            "stock_status", "pricing_mode",
        ]
        for field in fields:
            val = getattr(req, field, None)
            if val is not None:
                setattr(item, field, val)

        if req.vendor_id is not None:
            item.vendor_id, item.vendor_name = await InventoryService._resolve_vendor_snapshot(
                db, current_user, req.vendor_id, req.vendor_name
            )
        elif req.vendor_name is not None:
            item.vendor_name = req.vendor_name

        if item.net_gold_weight_grams > item.gross_weight_grams:
            raise ValidationException("net_gold_weight_grams cannot exceed gross_weight_grams")

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INVENTORY_ITEM_UPDATE",
            target_entity="inventory_items",
            target_id=item_id,
            before_state=before_state,
            after_state={"stock_status": item.stock_status},
        )

        await db.commit()
        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        return InventoryService._build_response(item, current_user)

    @staticmethod
    async def bulk_create_items(
        db: AsyncSession, current_user: User, req: BulkPurchaseRequest
    ) -> BulkPurchaseResponse:
        """One purchase header (vendor/date/invoice) entered once, many
        InventoryItem rows created together in a single transaction — either
        all of them are created or none are (a bad product_code partway
        through must not leave a half-recorded purchase)."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        vendor = await VendorService._get_owned_vendor(db, current_user, req.vendor_id)

        # Cheap existing-codes check per item (small batches — bulk entry is
        # a manual counter-entry workflow, not a mass import job).
        for line in req.items:
            if await InventoryRepository.get_by_product_code(db, line.product_code, current_user.tenant_id):
                raise ConflictException(f"Product code '{line.product_code}' is already in use")

        created_items = []
        for line in req.items:
            item = InventoryItem(
                id=f"iv_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                product_code=line.product_code,
                product_name=line.product_name,
                category=line.category,
                subcategory=line.subcategory,
                huid=line.huid,
                purity=line.purity,
                gross_weight_grams=line.gross_weight_grams,
                net_gold_weight_grams=line.net_gold_weight_grams,
                vendor_id=vendor.id,
                vendor_name=vendor.name,
                purchase_date=req.purchase_date,
                purchase_invoice_ref=req.purchase_invoice_ref,
                purchase_rate_per_gram=line.purchase_rate_per_gram,
                purchase_cost=line.purchase_cost,
                stock_status="IN_STOCK",
                making_charge_type=line.making_charge_type,
                making_charge_value=line.making_charge_value,
                wastage_type=line.wastage_type,
                wastage_value=line.wastage_value,
                gold_profit_percent=line.gold_profit_percent,
                stone_charge_amount=line.stone_charge_amount,
                other_charges_amount=line.other_charges_amount,
                tax_rate_percent=line.tax_rate_percent,
                pricing_mode=line.pricing_mode,
                created_by=current_user.id,
            )
            await InventoryRepository.create(db, item)
            created_items.append(item)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INVENTORY_BULK_PURCHASE",
            target_entity="inventory_items",
            target_id=None,
            before_state=None,
            after_state={"vendor_id": vendor.id, "invoice_ref": req.purchase_invoice_ref, "item_count": len(created_items)},
        )

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException("One or more product codes in this purchase are already in use")

        responses = []
        for item in created_items:
            fresh = await InventoryRepository.get_by_id(db, item.id, current_user.tenant_id)
            responses.append(InventoryService._build_response(fresh, current_user))
        return BulkPurchaseResponse(items=responses)

    @staticmethod
    async def preview_price(
        db: AsyncSession, current_user: User, req: PriceLinePreviewRequest
    ) -> PriceLinePreviewResponse:
        """Bulk Inventory's live Suggested Price / Profit preview — reuses
        BillingCalculationEngine.calculate() against a transient, unsaved
        InventoryItem built purely to carry the row's current field values
        (never added to the session). Same engine Selling uses; no financial
        math is duplicated in the frontend."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rate = await GoldRateService.get_customer_today_rate(db, current_user)
        if not rate:
            raise ResourceNotFoundException(
                "No live gold rate is available for today. Set today's gold rate first."
            )
        transient = InventoryItem(
            purity=req.purity,
            net_gold_weight_grams=req.net_gold_weight_grams,
            making_charge_type=req.making_charge_type,
            making_charge_value=req.making_charge_value,
            wastage_type=req.wastage_type,
            wastage_value=req.wastage_value,
            gold_profit_percent=req.gold_profit_percent,
            stone_charge_amount=req.stone_charge_amount,
            other_charges_amount=req.other_charges_amount,
            tax_rate_percent=req.tax_rate_percent,
        )
        breakdown = BillingCalculationEngine.calculate(
            transient, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            0, req.gst_applied, req.customer_price,
        )
        profit_or_loss = BillingCalculationEngine.realized_profit_or_loss(
            breakdown.final_amount, breakdown.tax_rate_percent, breakdown.gst_applied, req.purchase_cost
        )
        return PriceLinePreviewResponse(
            breakdown=breakdown, purchase_cost=req.purchase_cost, profit_or_loss=profit_or_loss
        )

    @staticmethod
    async def upload_staging_image(
        current_user: User, file_bytes: bytes, file_name: str, content_type: str
    ) -> str:
        """Upload a product image BEFORE the item exists (mandatory-image
        create flow). Same storage provider and same type allow-list as the
        per-item upload — not a second upload system — returning the storage
        path the caller then passes to create_item. Nothing is persisted to the
        database here."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        if content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValidationException(f"Unsupported image type '{content_type}'. Allowed: JPEG, PNG, WebP.")
        provider = get_storage_provider()
        return await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )

    @staticmethod
    async def upload_image(
        db: AsyncSession, current_user: User, item_id: str, file_bytes: bytes, file_name: str, content_type: str
    ) -> InventoryItemResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        if not item:
            raise ResourceNotFoundException(f"Inventory item '{item_id}' not found")
        if content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValidationException(f"Unsupported image type '{content_type}'. Allowed: JPEG, PNG, WebP.")

        provider = get_storage_provider()
        storage_path = await provider.upload(
            tenant_id=current_user.tenant_id,
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )
        item.image_storage_path = storage_path

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="INVENTORY_ITEM_IMAGE_UPLOAD",
            target_entity="inventory_items",
            target_id=item_id,
            before_state=None,
            after_state={"image_storage_path": storage_path},
        )

        await db.commit()
        item = await InventoryRepository.get_by_id(db, item_id, current_user.tenant_id)
        return InventoryService._build_response(item, current_user)


class SaleService:
    @staticmethod
    def _build_response(sale: Sale, current_user: User) -> SaleResponse:
        privileged = _is_privileged(current_user)
        return SaleResponse(
            id=sale.id,
            tenant_id=sale.tenant_id,
            invoice_number=sale.invoice_number,
            inventory_item_id=sale.inventory_item_id,
            customer_id=sale.customer_id,
            customer_name=sale.customer_name,
            customer_phone=sale.customer_phone,
            product_code=sale.product_code,
            product_name=sale.product_name,
            category=sale.inventory_item.category if sale.inventory_item else None,
            subcategory=sale.inventory_item.subcategory if sale.inventory_item else None,
            vendor_name=sale.vendor_name,
            huid=sale.huid,
            purity=sale.purity,
            gross_weight_grams=sale.gross_weight_grams,
            net_gold_weight_grams=sale.net_gold_weight_grams,
            gold_rate_24k=sale.gold_rate_24k,
            gold_rate_purity_factor=sale.gold_rate_purity_factor,
            gold_rate_applied=sale.gold_rate_applied,
            gold_rate_source=sale.gold_rate_source,
            gold_rate_effective_date=sale.gold_rate_effective_date,
            gold_value_amount=sale.gold_value_amount,
            making_charge_type=sale.making_charge_type,
            making_charge_value=sale.making_charge_value,
            making_charge_amount=sale.making_charge_amount,
            wastage_type=sale.wastage_type,
            wastage_value=sale.wastage_value,
            wastage_amount=sale.wastage_amount,
            gold_profit_percent=sale.gold_profit_percent if privileged else None,
            gold_profit_amount=sale.gold_profit_amount if privileged else None,
            stone_charge_amount=sale.stone_charge_amount,
            other_charges_amount=sale.other_charges_amount,
            subtotal_before_tax=sale.subtotal_before_tax,
            gst_applied=sale.gst_applied,
            tax_rate_percent=sale.tax_rate_percent,
            tax_amount=sale.tax_amount,
            discount_amount=sale.discount_amount,
            final_amount=sale.final_amount,
            payment_method=sale.payment_method,
            payment_status=sale.payment_status,
            amount_paid=_round2(sale.amount_paid or 0),
            amount_outstanding=_outstanding_of(sale),
            sale_status=sale.sale_status or SALE_STATUS_COMPLETED,
            amount_refunded=_round2(sale.amount_refunded or 0),
            pricing_mode=sale.pricing_mode,
            purchase_cost_snapshot=sale.purchase_cost_snapshot if privileged else None,
            estimated_gross_margin=sale.estimated_gross_margin if privileged else None,
            # Privileged-only. The direction label plus a variable customer_price
            # is a profit/cost oracle for Staff, so it is withheld entirely
            # (Staff Financial Visibility baseline). Staff safe-price guidance
            # is a separate, later, purpose-built response.
            profit_or_loss_label=_pl_label(sale.estimated_gross_margin) if privileged else None,
            sale_timestamp=sale.sale_timestamp,
            created_by=sale.created_by,
            created_at=sale.created_at,
        )

    @staticmethod
    async def _get_sellable_item_and_rate(db: AsyncSession, current_user: User, product_code: str):
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        item = await InventoryRepository.get_by_product_code(db, product_code, current_user.tenant_id)
        if not item:
            raise ResourceNotFoundException(f"No inventory item found for product code '{product_code}'")
        if item.stock_status != "IN_STOCK":
            raise ConflictException(
                f"Product '{product_code}' is not available for sale (status: {item.stock_status})"
            )

        rate = await GoldRateService.get_customer_today_rate(db, current_user)
        if not rate:
            raise ResourceNotFoundException(
                "No live gold rate is available for today. Set today's gold rate before completing a sale."
            )
        return item, rate

    @staticmethod
    async def get_quote(
        db: AsyncSession,
        current_user: User,
        product_code: str,
        discount_amount: float = 0,
        gst_applied: bool = True,
        customer_price: Optional[float] = None,
        making_charge_value: Optional[float] = None,
        wastage_value: Optional[float] = None,
        gold_profit_percent: Optional[float] = None,
        making_charge_type: Optional[str] = None,
        wastage_type: Optional[str] = None,
    ) -> SaleQuoteResponse:
        item, rate = await SaleService._get_sellable_item_and_rate(db, current_user, product_code)
        breakdown = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            discount_amount, gst_applied, customer_price,
            making_charge_value, wastage_value, gold_profit_percent,
            making_charge_type, wastage_type,
        )
        privileged = _is_privileged(current_user)
        # Compute both views once. The direction label is derived here and shown
        # to everyone (Staff see the WORD); the numeric views stay commercially
        # sensitive and are gated to privileged callers only.
        all_views = BillingCalculationEngine.profit_views(breakdown, item.purchase_cost)
        hp = all_views.get("historical_profit_or_loss")
        cp = all_views.get("current_gold_value_profit_or_loss")
        label = _pl_label(hp if hp is not None else cp)
        views = all_views if privileged else {}
        # Mask internal store margin from the breakdown for Staff. Direct fields
        # only — the granular component/subtotal breakdown can still be
        # arithmetically reconciled; a fully Staff-safe quote projection is a
        # later, purpose-built response.
        breakdown_out = (
            breakdown if privileged
            else breakdown.model_copy(update={"gold_profit_percent": None, "gold_profit_amount": None})
        )
        # Safe-price / discount guidance (Historical Cost P/L >= 0 boundary).
        # Judged against the natural asking price = the same charges with NO
        # discount and NO customer_price override.
        full = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            0, gst_applied, None,
            making_charge_value, wastage_value, gold_profit_percent,
            making_charge_type, wastage_type,
        )
        raw_guidance = BillingCalculationEngine.safe_price_guidance(full, item.purchase_cost, customer_price)
        safe_price = SaleService._project_safe_price(raw_guidance, privileged)
        return SaleQuoteResponse(
            inventory_item=InventoryService._build_response(item, current_user),
            breakdown=breakdown_out,
            profit_or_loss=views.get("historical_profit_or_loss"),
            historical_profit_or_loss=views.get("historical_profit_or_loss"),
            historical_profit_margin_percent=views.get("historical_profit_margin_percent"),
            current_gold_value_profit_or_loss=views.get("current_gold_value_profit_or_loss"),
            current_gold_value_margin_percent=views.get("current_gold_value_margin_percent"),
            profit_or_loss_label=label if privileged else None,
            safe_price=safe_price,
        )

    @staticmethod
    def _project_safe_price(raw: Optional[dict], privileged: bool) -> Optional["SafePriceGuidance"]:
        """Build the SafePriceGuidance response, masking for Staff: drop the
        rupee break-even/min-safe figure and any GOLD_PROFIT reduction line
        (internal margin), keeping only the SAFE/LOSS decision and the
        customer-facing Making/Wastage trims."""
        if raw is None:
            return None
        reductions = raw.get("reductions", [])
        if not privileged:
            reductions = [r for r in reductions if r.get("component") != "GOLD_PROFIT"]
        return SafePriceGuidance(
            status=raw["status"],
            is_loss=raw["is_loss"],
            requested_price=raw.get("requested_price"),
            minimum_safe_price=raw.get("minimum_safe_price") if privileged else None,
            achievable_price=raw.get("achievable_price"),
            residual_discount=raw.get("residual_discount") if privileged else None,
            reductions=[SafePriceReduction(**r) for r in reductions],
            message=raw.get("message", ""),
        )

    @staticmethod
    def _generate_invoice_number() -> str:
        # Same PREFIX-YYMMDD-<6 hex> convention as Payment.payment_reference
        # (see app/services/payment_service.py) — random suffix + a unique
        # constraint on (tenant_id, invoice_number), not a DB sequence.
        return f"INV-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"

    @staticmethod
    async def _validate_customer_id(db: AsyncSession, current_user: User, customer_id: Optional[str]) -> None:
        """A client-supplied customer_id must never be trusted blindly — without
        this check, a Sale row could end up pointing at a user from another
        tenant entirely (the users table has no tenant-partitioned FK, so the
        database itself won't catch that)."""
        if not customer_id:
            return
        stmt = select(User.id).where(User.id == customer_id, User.tenant_id == current_user.tenant_id)
        found = (await db.execute(stmt)).scalar_one_or_none()
        if not found:
            raise ResourceNotFoundException(f"Customer '{customer_id}' not found in your tenant")

    @staticmethod
    async def _resolve_or_create_customer(
        db: AsyncSession,
        current_user: User,
        customer_id: Optional[str],
        customer_name: Optional[str],
        customer_phone: Optional[str],
    ) -> Optional[str]:
        """Return the authoritative customer_id a sale must be linked to, so a
        purchase always attaches to ONE real Customer record and the buyer shows
        up in the Customer Directory (classified WALK-IN, or HYBRID if they also
        hold a scheme).

        - An explicit customer_id (existing customer picked in New Sale) is used
          as-is; it was already tenant-validated by the caller.
        - Otherwise, when a mobile number is given, an existing own-tenant
          customer with that number is REUSED — the same person keeps one
          Customer ID across repeat purchases and later scheme enrollment; no
          duplicate is ever created.
        - Only when no existing customer matches is a new minimal walk-in
          Customer created (passwordless, like a Google account: a random,
          discarded secret keeps the NOT NULL column honest). This is the single
          place New Sale mints a customer identity."""
        if customer_id:
            return customer_id
        if customer_phone:
            existing = (await db.execute(
                select(User.id).where(
                    User.phone == customer_phone,
                    User.tenant_id == current_user.tenant_id,
                )
            )).scalar_one_or_none()
            if existing:
                return existing
        # No customer_id and no matching phone: this is a brand-new buyer. Only
        # create a record when we at least have a name to identify them by.
        if not customer_name:
            return None

        role = (await db.execute(select(Role).where(Role.name == ROLE_CUSTOMER))).scalar_one_or_none()
        if not role:
            raise ResourceNotFoundException("Customer role configuration missing in database")
        customer_code = await CustomerRepository.allocate_customer_code(db, current_user.tenant_id)
        user = User(
            id=f"usr_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            role_id=role.id,
            phone=customer_phone,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            name=customer_name,
            kyc_status="Pending",
            customer_code=customer_code,
            member_since=datetime.now(timezone.utc).strftime("%B %Y"),
            is_active=True,
        )
        db.add(user)
        await db.flush()  # assign user.id before the Sale row references it
        return user.id

    @staticmethod
    async def create_sale(db: AsyncSession, current_user: User, req: SaleCreateRequest) -> SaleResponse:
        await SaleService._validate_customer_id(db, current_user, req.customer_id)
        item, rate = await SaleService._get_sellable_item_and_rate(db, current_user, req.product_code)
        # Vendor cost is compulsory to sell: without it there is no break-even
        # to protect against a loss. New items always carry one; a legacy
        # null-cost item is blocked here (never backfilled or guessed) until an
        # Admin edits it and enters the real Purchase Cost. Checked before any
        # state change so a rejected sale mutates nothing.
        if item.purchase_cost is None:
            raise ValidationException(
                "Purchase Cost must be entered on this item before it can be sold. "
                "Edit the inventory item and set its vendor Purchase Cost."
            )
        breakdown = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            req.discount_amount, req.gst_applied, req.customer_price,
            req.making_charge_value, req.wastage_value, req.gold_profit_percent,
            req.making_charge_type, req.wastage_type,
        )

        sold = await InventoryRepository.mark_sold_if_in_stock(db, item.id, current_user.tenant_id)
        if not sold:
            await db.rollback()
            raise ConflictException(
                f"Product '{req.product_code}' was just sold in another transaction. Please rescan."
            )

        # Resolve the opening collection from the Admin's selected intent.
        # PAID collects the whole invoice, PARTIAL collects exactly what was
        # handed over, PENDING collects nothing — and a PENDING/PAID sale never
        # gets a fabricated ₹0 ledger row.
        if req.payment_status == "PAID":
            initial_payment = breakdown.final_amount
        elif req.payment_status == "PARTIAL":
            initial_payment = _round2(req.initial_payment_amount)
            if initial_payment >= breakdown.final_amount - _MONEY_EPSILON:
                await db.rollback()
                raise ValidationException(
                    f"A partial payment must be less than the invoice total of {breakdown.final_amount}. "
                    "Mark the sale as PAID to collect the full amount."
                )
        else:
            initial_payment = 0.0

        purchase_cost_snapshot = item.purchase_cost
        estimated_gross_margin = BillingCalculationEngine.realized_profit_or_loss(
            breakdown.final_amount, breakdown.tax_rate_percent, breakdown.gst_applied, purchase_cost_snapshot
        )

        # Attach this purchase to ONE authoritative Customer. A walk-in typed
        # straight into New Sale (name + mobile, no picked customer) is created
        # or matched here, so the buyer appears in the Customer Directory and is
        # classified WALK-IN. Runs only after the item is confirmed SOLD, so a
        # failed sale never mints a stray customer.
        resolved_customer_id = await SaleService._resolve_or_create_customer(
            db, current_user, req.customer_id, req.customer_name, req.customer_phone
        )

        sale_id = f"sl_{uuid.uuid4().hex[:12]}"
        sale = Sale(
            id=sale_id,
            tenant_id=current_user.tenant_id,
            invoice_number=SaleService._generate_invoice_number(),
            inventory_item_id=item.id,
            customer_id=resolved_customer_id,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            product_code=item.product_code,
            product_name=item.product_name,
            vendor_name=item.vendor_name,
            huid=item.huid,
            purity=item.purity,
            gross_weight_grams=item.gross_weight_grams,
            net_gold_weight_grams=item.net_gold_weight_grams,
            gold_rate_24k=breakdown.gold_rate_24k,
            gold_rate_purity_factor=breakdown.gold_rate_purity_factor,
            gold_rate_applied=breakdown.gold_rate_applied,
            gold_rate_source=breakdown.gold_rate_source,
            gold_rate_effective_date=breakdown.gold_rate_effective_date,
            gold_value_amount=breakdown.gold_value_amount,
            making_charge_type=breakdown.making_charge_type,
            making_charge_value=breakdown.making_charge_value,
            making_charge_amount=breakdown.making_charge_amount,
            wastage_type=breakdown.wastage_type,
            wastage_value=breakdown.wastage_value,
            wastage_amount=breakdown.wastage_amount,
            gold_profit_percent=breakdown.gold_profit_percent,
            gold_profit_amount=breakdown.gold_profit_amount,
            stone_charge_amount=breakdown.stone_charge_amount,
            other_charges_amount=breakdown.other_charges_amount,
            subtotal_before_tax=breakdown.subtotal_before_tax,
            gst_applied=breakdown.gst_applied,
            tax_rate_percent=breakdown.tax_rate_percent,
            tax_amount=breakdown.tax_amount,
            discount_amount=breakdown.discount_amount,
            final_amount=breakdown.final_amount,
            payment_method=req.payment_method,
            # Both set from the ledger seeded just below, never from the
            # request — req.payment_status is only the Admin's intent.
            payment_status=_derive_payment_status(breakdown.final_amount, initial_payment),
            amount_paid=initial_payment,
            pricing_mode=req.pricing_mode or ("MANUAL" if req.customer_price is not None else "AUTO"),
            purchase_cost_snapshot=purchase_cost_snapshot,
            estimated_gross_margin=estimated_gross_margin,
            sale_timestamp=datetime.now(timezone.utc),
            created_by=current_user.id,
        )
        await SaleRepository.create(db, sale)

        # Opening ledger row — same transaction as the Sale itself, so a
        # finalized invoice and its first collection are never out of step.
        if initial_payment > 0:
            await SalePaymentRepository.create(
                db,
                SalePayment(
                    id=f"sp_{uuid.uuid4().hex[:12]}",
                    tenant_id=current_user.tenant_id,
                    sale_id=sale_id,
                    amount=initial_payment,
                    payment_date=datetime.now(IST).date(),
                    payment_method=req.payment_method,
                    source=PAYMENT_SOURCE_COUNTER,
                    reference_no=req.payment_reference_no,
                    remarks="Collected at sale",
                    recorded_by=current_user.id,
                ),
            )

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SALE_CREATE",
            target_entity="sales",
            target_id=sale_id,
            before_state=None,
            after_state={
                "product_code": item.product_code,
                "invoice_number": sale.invoice_number,
                "final_amount": breakdown.final_amount,
                "amount_paid": initial_payment,
                "payment_status": sale.payment_status,
            },
        )

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException("Could not generate a unique invoice number. Please try again.")

        sale = await SaleRepository.get_by_id(db, sale_id, current_user.tenant_id)
        return SaleService._build_response(sale, current_user)

    @staticmethod
    async def list_sales(
        db: AsyncSession,
        current_user: User,
        page: int,
        limit: int,
        search: Optional[str],
        date_from: Optional[date],
        date_to: Optional[date],
        payment_status: Optional[str] = None,
        sale_status: Optional[str] = None,
        customer_id: Optional[str] = None,
        product_code: Optional[str] = None,
        category: Optional[str] = None,
        purity: Optional[str] = None,
        subcategory: Optional[str] = None,
    ) -> SaleListResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sales, total, total_gold_weight_grams, total_outstanding = await SaleRepository.list_by_tenant(
            db, current_user.tenant_id, page, limit, search, date_from, date_to,
            payment_status, sale_status, customer_id, product_code, category,
            purity, subcategory,
        )
        rows = [SaleService._build_response(s, current_user) for s in sales]

        # Attach the customer code for the rows that are billed to a registered
        # customer. One batched lookup for the whole page — never one query per
        # sale, and never stored on the Sale row (the code belongs to the
        # customer record, the sale keeps its own name/phone snapshot).
        codes = await CustomerRepository.codes_for_customer_ids(
            db, [s.customer_id for s in sales if s.customer_id], current_user.tenant_id
        )
        for row, sale in zip(rows, sales):
            row.customer_code = codes.get(sale.customer_id) if sale.customer_id else None

        return SaleListResponse(
            sales=rows, total=total, total_gold_weight_grams=total_gold_weight_grams,
            total_outstanding=round(total_outstanding, 2),
        )

    @staticmethod
    def _resolve_period_range(
        today: date, period: Optional[str], date_from: Optional[date], date_to: Optional[date]
    ) -> tuple[date, date, str]:
        """Business History date-range resolution — real calendar ranges,
        not a frontend-side filter of already-fetched data. Custom
        date_from/date_to (if both given) win over `period`."""
        if date_from and date_to:
            return date_from, date_to, f"{date_from.isoformat()} to {date_to.isoformat()}"
        p = (period or "today").lower()
        if p == "today":
            return today, today, "Today"
        if p == "yesterday":
            d = today - timedelta(days=1)
            return d, d, "Yesterday"
        if p == "this_week":
            return today - timedelta(days=today.weekday()), today, "This Week"
        if p == "last_week":
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=6), "Last Week"
        if p == "this_month":
            return today.replace(day=1), today, "This Month"
        if p == "last_month":
            last_day_prev = today.replace(day=1) - timedelta(days=1)
            return last_day_prev.replace(day=1), last_day_prev, "Last Month"
        if p == "last_3_months":
            return today - timedelta(days=90), today, "Last 3 Months"
        if p == "last_6_months":
            return today - timedelta(days=182), today, "Last 6 Months"
        if p == "last_12_months":
            return today - timedelta(days=365), today, "Last 12 Months"
        return today, today, "Today"

    @staticmethod
    async def get_business_summary(
        db: AsyncSession, current_user: User,
        period: Optional[str] = None, date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> BusinessSummaryResponse:
        """Business History — same frozen-snapshot aggregation as the
        dashboard, scoped to one caller-selected period or custom range."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        now_ist = datetime.now(IST)
        sel_from, sel_to, sel_label = SaleService._resolve_period_range(
            now_ist.date(), period, date_from, date_to
        )
        period_start = datetime.combine(sel_from, datetime.min.time(), tzinfo=IST)
        period_end = datetime.combine(sel_to, datetime.max.time(), tzinfo=IST)
        raw = await SaleRepository.get_period_summary(
            db, current_user.tenant_id, period_start, period_end,
        )
        # Money movement on the payment-ledger date axis for the same range.
        coll = await SaleRepository.get_collections_summary(
            db, current_user.tenant_id, period_start, period_end,
        )
        privileged = _is_privileged(current_user)
        return BusinessSummaryResponse(
            period=sel_label,
            date_from=sel_from,
            date_to=sel_to,
            total_sales=raw["total_sales"],
            total_profit=raw["total_profit"] if privileged else None,
            total_loss=raw["total_loss"] if privileged else None,
            current_gold_value_profit_or_loss=(
                raw["current_gold_value_profit_or_loss"] if privileged else None
            ),
            bill_count=raw["bill_count"],
            items_sold=raw["items_sold"],
            total_tax=raw["total_tax"],
            average_bill_value=raw["avg_bill_value"],
            gross_sales=raw["gross_sales"],
            sales_returns=raw["sales_returns"],
            return_count=raw["return_count"],
            total_refunded=raw["total_refunded"],
            cash_collected=coll["cash_collected"],
            scheme_redemption=coll["scheme_redemption"],
            refunds_paid=coll["refunds"],
        )

    @staticmethod
    async def get_receivables_summary(
        db: AsyncSession, current_user: User,
        period: Optional[str] = None, date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> ReceivablesSummaryResponse:
        """Authoritative receivables over a period — same date-range vocabulary
        as Business History (see _resolve_period_range), tenant-scoped, read
        only. Reuses the SalePayment-synced Sale columns; no new payment math."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sel_from, sel_to, sel_label = SaleService._resolve_period_range(
            datetime.now(IST).date(), period, date_from, date_to
        )
        raw = await SaleRepository.get_receivables_summary(
            db, current_user.tenant_id,
            datetime.combine(sel_from, datetime.min.time(), tzinfo=IST),
            datetime.combine(sel_to, datetime.max.time(), tzinfo=IST),
        )
        return ReceivablesSummaryResponse(
            period=sel_label, date_from=sel_from, date_to=sel_to, **raw
        )

    @staticmethod
    async def _period_block(
        db: AsyncSession, tenant_id: str, start_dt: datetime, end_dt: datetime, privileged: bool
    ) -> BillingPeriodSummary:
        """One period's full accounting block — a composition layer over the
        three authoritative aggregations, never a re-implementation:
          - get_period_summary   sale-date: gross/net/returns/profit/tax
          - get_collections_summary  payment-date: cash / scheme / refunds
          - get_receivables_summary  active COMPLETED sales: paid/outstanding/counts
        Each is one grouped SQL; no per-row Python, no N+1. Scheme redemption is
        kept out of cash_collected by get_collections_summary itself."""
        raw = await SaleRepository.get_period_summary(db, tenant_id, start_dt, end_dt)
        coll = await SaleRepository.get_collections_summary(db, tenant_id, start_dt, end_dt)
        rec = await SaleRepository.get_receivables_summary(db, tenant_id, start_dt, end_dt)
        block = {
            "total_sales": raw["total_sales"],
            "total_profit": raw["total_profit"] if privileged else None,
            "total_loss": raw["total_loss"] if privileged else None,
            "current_gold_value_profit_or_loss": (
                raw["current_gold_value_profit_or_loss"] if privileged else None
            ),
            "bill_count": raw["bill_count"],
            "items_sold": raw["items_sold"],
            "total_tax": raw["total_tax"],
            "avg_bill_value": raw["avg_bill_value"],
            "gross_sales": raw["gross_sales"],
            "sales_returns": raw["sales_returns"],
            "return_count": raw["return_count"],
            "total_refunded": raw["total_refunded"],
            "cash_collected": coll["cash_collected"],
            "scheme_redemption": coll["scheme_redemption"],
            "refunds_paid": coll["refunds"],
            # Per-method split of cash_collected only (scheme settlements and
            # refunds are excluded upstream), so the parts sum to cash_collected.
            "collected_by_method": coll.get("collected_by_method", {}),
            "total_paid": rec["total_paid"],
            "total_outstanding": rec["total_outstanding"],
            "paid_count": rec["paid_count"],
            "partial_count": rec["partial_count"],
            "pending_count": rec["pending_count"],
            "sale_count": rec["sale_count"],
        }
        return BillingPeriodSummary(**block)

    @staticmethod
    async def get_dashboard_summary(
        db: AsyncSession, current_user: User,
        period: Optional[str] = None, date_from: Optional[date] = None, date_to: Optional[date] = None,
    ) -> BillingDashboardSummaryResponse:
        """Powers the Admin Dashboard's Billing Summary — every figure is
        aggregated straight off finalized Sale rows (see
        SaleRepository.get_period_summary's own docstring); nothing here is
        recomputed against today's live gold rate."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        privileged = _is_privileged(current_user)
        now_ist = datetime.now(IST)
        today_start = datetime.combine(now_ist.date(), datetime.min.time(), tzinfo=IST)
        today_end = datetime.combine(now_ist.date(), datetime.max.time(), tzinfo=IST)
        month_start = today_start.replace(day=1)

        tid = current_user.tenant_id
        today_block = await SaleService._period_block(db, tid, today_start, today_end, privileged)
        month_block = await SaleService._period_block(db, tid, month_start, today_end, privileged)
        recent = await SaleRepository.get_recent(db, tid, limit=5)
        rate = await GoldRateService.get_customer_today_rate(db, current_user)

        sel_from, sel_to, sel_label = SaleService._resolve_period_range(now_ist.date(), period, date_from, date_to)
        sel_start_dt = datetime.combine(sel_from, datetime.min.time(), tzinfo=IST)
        sel_end_dt = datetime.combine(sel_to, datetime.max.time(), tzinfo=IST)
        selected_block = await SaleService._period_block(db, tid, sel_start_dt, sel_end_dt, privileged)

        return BillingDashboardSummaryResponse(
            today=today_block,
            this_month=month_block,
            today_gold_rate_24k=rate.rate_24k if rate else None,
            selected_period=selected_block,
            selected_period_label=sel_label,
            selected_date_from=sel_from,
            selected_date_to=sel_to,
            recent_sales=[
                RecentSaleSummary(
                    id=s.id,
                    invoice_number=s.invoice_number,
                    customer_name=s.customer_name,
                    product_code=s.product_code,
                    product_name=s.product_name,
                    final_amount=s.final_amount,
                    profit_or_loss=s.estimated_gross_margin if privileged else None,
                    sale_timestamp=s.sale_timestamp,
                )
                for s in recent
            ],
        )

    @staticmethod
    async def get_sale(db: AsyncSession, current_user: User, sale_id: str) -> SaleResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sale = await SaleRepository.get_by_id(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")
        response = SaleService._build_response(sale, current_user)
        if sale.customer_id:
            codes = await CustomerRepository.codes_for_customer_ids(
                db, [sale.customer_id], current_user.tenant_id
            )
            response.customer_code = codes.get(sale.customer_id)
        # Attached on the single-sale read only: the invoice detail view needs
        # the full reversal record, the paginated list does not.
        response.sale_return = await SaleReturnService.get_for_sale(db, current_user, sale_id)
        return response

    @staticmethod
    async def get_sale_orm(db: AsyncSession, current_user: User, sale_id: str) -> Sale:
        """Raw ORM row for invoice export (PDF/Excel) — the export renders
        directly off the immutable snapshot, not the API response shape."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sale = await SaleRepository.get_by_id(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")
        return sale

    @staticmethod
    async def list_for_export(
        db: AsyncSession,
        current_user: User,
        period: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        search: Optional[str] = None,
        payment_status: Optional[str] = None,
        sale_status: Optional[str] = None,
    ) -> tuple[list, dict, str, date, date]:
        """Gathers exactly the filtered Sales History set for the Excel export,
        plus each sale's ledger rows. Same period vocabulary as Business
        History (see _resolve_period_range) so a period label means the same
        thing everywhere in the product."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        sel_from, sel_to, sel_label = SaleService._resolve_period_range(
            datetime.now(IST).date(), period, date_from, date_to
        )
        sales = await SaleRepository.list_all_filtered(
            db, current_user.tenant_id, search, sel_from, sel_to, payment_status, sale_status
        )
        ledger = await SalePaymentRepository.list_by_sale_ids(
            db, [s.id for s in sales], current_user.tenant_id
        )
        by_sale: dict = {}
        for p in ledger:
            by_sale.setdefault(p.sale_id, []).append(p)
        return sales, by_sale, sel_label, sel_from, sel_to


class SalePaymentService:
    """Recording and reading collections against a finalized invoice.

    Every write here is append-only: a new SalePayment row plus a
    transactional refresh of the Sale's derived amount_paid/payment_status
    cache. No code path updates or deletes an existing ledger row, so a
    collection history can never be rewritten or erased.
    """

    @staticmethod
    def _build_response(payment: SalePayment, actor_names: dict) -> SalePaymentResponse:
        return SalePaymentResponse(
            id=payment.id,
            sale_id=payment.sale_id,
            amount=_round2(payment.amount),
            payment_date=payment.payment_date,
            payment_method=payment.payment_method,
            source=payment.source,
            reference_no=payment.reference_no,
            remarks=payment.remarks,
            recorded_by=payment.recorded_by,
            recorded_by_name=actor_names.get(payment.recorded_by),
            created_at=payment.created_at,
        )

    @staticmethod
    async def _actor_names(db: AsyncSession, payments: list) -> dict:
        ids = {p.recorded_by for p in payments}
        if not ids:
            return {}
        rows = (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
        return {row[0]: row[1] for row in rows}

    @staticmethod
    async def get_history(
        db: AsyncSession, current_user: User, sale_id: str
    ) -> SalePaymentHistoryResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sale = await SaleRepository.get_by_id(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")

        payments = await SalePaymentRepository.list_by_sale(db, sale_id, current_user.tenant_id)
        names = await SalePaymentService._actor_names(db, payments)
        return SalePaymentHistoryResponse(
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            final_amount=_round2(sale.final_amount),
            amount_paid=_round2(sale.amount_paid or 0),
            amount_outstanding=_outstanding_of(sale),
            payment_status=sale.payment_status,
            payments=[SalePaymentService._build_response(p, names) for p in payments],
        )

    @staticmethod
    async def record_payment(
        db: AsyncSession, current_user: User, sale_id: str, req: SalePaymentCreateRequest
    ) -> SalePaymentHistoryResponse:
        """Collect money against an existing invoice.

        Ordering matters and is deliberate:
          1. lock the Sale row (tenant-scoped) for the rest of the transaction
          2. compute outstanding from the LEDGER, not the cached column
          3. reject amount <= 0 and any amount above outstanding
          4. insert the ledger row
          5. refresh the derived cache from the ledger
          6. commit once

        Step 1 is what stops two Admins collecting simultaneously from both
        validating against the same stale outstanding figure and together
        over-collecting on one invoice. Frontend validation is a convenience
        only; this is the guard that actually holds.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        sale = await SaleRepository.get_by_id_for_update(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")

        # Money can never be collected against a reversed sale: the customer's
        # liability was closed by the return.
        if (sale.sale_status or SALE_STATUS_COMPLETED) != SALE_STATUS_COMPLETED:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is {sale.sale_status.lower()} — no further payment "
                f"can be collected against it."
            )

        amount = _round2(req.amount)
        if amount <= 0:
            raise ValidationException("Payment amount must be greater than zero")

        already_paid = await SalePaymentRepository.sum_for_sale(db, sale_id, current_user.tenant_id)
        outstanding = _round2(sale.final_amount - already_paid)

        if outstanding <= _MONEY_EPSILON:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is already fully paid — nothing is outstanding."
            )
        # Overpayment is rejected outright, never silently clamped to the
        # outstanding amount: no refund/credit-note model exists yet, so
        # accepting more than is owed would create money the system cannot
        # account for. The Admin is told the exact collectable figure.
        if amount > outstanding + _MONEY_EPSILON:
            raise ValidationException(
                f"Payment of {amount} exceeds the outstanding amount of {outstanding} on invoice "
                f"{sale.invoice_number}. Overpayments are not supported — collect {outstanding} or less."
            )

        payment = SalePayment(
            id=f"sp_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            sale_id=sale.id,
            amount=amount,
            payment_date=req.payment_date,
            payment_method=req.payment_method,
            source=PAYMENT_SOURCE_COUNTER,
            reference_no=req.reference_no,
            remarks=req.remarks,
            recorded_by=current_user.id,
        )
        await SalePaymentRepository.create(db, payment)

        new_paid = _round2(already_paid + amount)
        sale.amount_paid = new_paid
        sale.payment_status = _derive_payment_status(sale.final_amount, new_paid)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SALE_PAYMENT_RECORD",
            target_entity="sale_payments",
            target_id=payment.id,
            before_state={"amount_paid": _round2(already_paid)},
            after_state={
                "invoice_number": sale.invoice_number,
                "amount": amount,
                "payment_method": payment.payment_method,
                "amount_paid": new_paid,
                "payment_status": sale.payment_status,
            },
        )

        await db.commit()
        return await SalePaymentService.get_history(db, current_user, sale_id)



def _derive_refund_status(amount_collected: float, amount_refunded: float) -> str:
    """Payment status of a REVERSED sale. Driven purely by refunded-vs-collected
    on the ledger.

    refunded >= collected    -> REFUNDED             every rupee taken is back
                                                     with the customer; a sale
                                                     where nothing was ever
                                                     collected is vacuously
                                                     fully refunded
    0 < refunded < collected -> PARTIALLY_REFUNDED   negotiated partial refund

    The unpaid balance is never part of this: it is written off by the return,
    not refunded, because the store never received it.
    """
    if amount_refunded >= amount_collected - _MONEY_EPSILON:
        return PAYMENT_STATUS_REFUNDED
    return PAYMENT_STATUS_PARTIALLY_REFUNDED


class SaleReturnService:
    """Sale-level return / cancellation.

    The original invoice is never edited to hide a sale. Reversing a sale writes
    a new SaleReturn row, appends a negative REFUND row to the existing
    sale_payments ledger, and moves the sale's derived status columns — the
    product snapshot, gold rate, gold-rate effective date, charges, GST,
    customer price, purchase-cost snapshot, original margin, invoice number and
    every earlier payment row stay exactly as recorded.

    One sale carries one inventory item here, so a return is all-or-nothing;
    there is no partial-return state, because the schema cannot represent one
    line of a multi-line invoice coming back.
    """

    @staticmethod
    def _build_response(
        row: SaleReturn, actor_names: dict, current_stock_status: Optional[str] = None,
        scheme_restored: float = 0.0,
    ) -> SaleReturnResponse:
        return SaleReturnResponse(
            id=row.id,
            sale_id=row.sale_id,
            invoice_number=row.invoice_number,
            inventory_item_id=row.inventory_item_id,
            product_code=row.product_code,
            return_type=row.return_type,
            reason=row.reason,
            original_sale_amount=_round2(row.original_sale_amount),
            amount_collected_at_return=_round2(row.amount_collected_at_return),
            refund_amount=_round2(row.refund_amount),
            outstanding_written_off=_round2(row.outstanding_written_off),
            scheme_restored=_round2(scheme_restored),
            refund_method=row.refund_method,
            refund_reference_no=row.refund_reference_no,
            inspection_status=row.inspection_status,
            inspection_notes=row.inspection_notes,
            inspected_at=row.inspected_at,
            inspected_by=row.inspected_by,
            inspected_by_name=actor_names.get(row.inspected_by) if row.inspected_by else None,
            returned_at=row.returned_at,
            processed_by=row.processed_by,
            processed_by_name=actor_names.get(row.processed_by),
            current_stock_status=current_stock_status,
            created_at=row.created_at,
        )

    @staticmethod
    async def _actor_names(db: AsyncSession, ids: list) -> dict:
        wanted = {i for i in ids if i}
        if not wanted:
            return {}
        rows = (await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))).all()
        return {r[0]: r[1] for r in rows}

    @staticmethod
    async def get_for_sale(
        db: AsyncSession, current_user: User, sale_id: str
    ) -> Optional[SaleReturnResponse]:
        """The reversal record for one sale, or None if the sale is intact."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        row = await SaleReturnRepository.get_by_sale(db, sale_id, current_user.tenant_id)
        if not row:
            return None
        item = await InventoryRepository.get_by_id(db, row.inventory_item_id, current_user.tenant_id)
        names = await SaleReturnService._actor_names(db, [row.processed_by, row.inspected_by])
        scheme_restored = await SchemeRedemptionRepository.sum_restorations_for_sale(
            db, sale_id, current_user.tenant_id
        )
        return SaleReturnService._build_response(
            row, names, item.stock_status if item else None, scheme_restored
        )

    @staticmethod
    async def get_for_inventory_item(
        db: AsyncSession, current_user: User, inventory_item_id: str
    ) -> Optional[SaleReturnResponse]:
        """The pending-inspection return for one inventory item, so the Inventory
        page can drive the SAME inspection action Sales History uses. Tenant
        scoped; returns None when the item has no return awaiting inspection."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        row = await SaleReturnRepository.get_pending_by_inventory_item(
            db, inventory_item_id, current_user.tenant_id
        )
        if not row:
            return None
        return await SaleReturnService.get_for_sale(db, current_user, row.sale_id)

    @staticmethod
    async def preview(
        db: AsyncSession, current_user: User, sale_id: str
    ) -> SaleReturnPreviewResponse:
        """Backend-computed financial impact for the Admin confirmation dialog.
        Read-only — asking for a preview stores nothing and locks nothing."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        sale = await SaleRepository.get_by_id(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")

        collected = _round2(
            await SalePaymentRepository.sum_for_sale(db, sale_id, current_user.tenant_id)
        )
        current_status = sale.sale_status or SALE_STATUS_COMPLETED
        item = await InventoryRepository.get_by_id(db, sale.inventory_item_id, current_user.tenant_id)
        outstanding = _round2(max(0.0, sale.final_amount - collected))

        blocked = None
        if current_status != SALE_STATUS_COMPLETED:
            blocked = (
                f"Invoice {sale.invoice_number} is already {current_status.lower()} and cannot be "
                f"reversed again."
            )
        elif item is None:
            blocked = "The inventory item for this sale no longer exists and cannot be taken back."
        elif item.stock_status != STOCK_STATUS_SOLD:
            blocked = (
                f"Inventory item {sale.product_code} is not in SOLD state "
                f"(current: {item.stock_status})."
            )

        return SaleReturnPreviewResponse(
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            product_code=sale.product_code,
            product_name=sale.product_name,
            sale_status=current_status,
            payment_status=sale.payment_status,
            original_sale_amount=_round2(sale.final_amount),
            amount_collected=collected,
            outstanding=outstanding,
            max_refundable=collected,
            outstanding_to_write_off=outstanding,
            current_stock_status=item.stock_status if item else "MISSING",
            resulting_stock_status=STOCK_STATUS_RETURNED_PENDING_INSPECTION,
            can_return=blocked is None,
            blocked_reason=blocked,
        )

    @staticmethod
    async def process_return(
        db: AsyncSession, current_user: User, sale_id: str, req: SaleReturnCreateRequest
    ) -> SaleReturnResponse:
        """Reverse one sale, in a single transaction.

        Ordering is deliberate and mirrors SalePaymentService.record_payment:
          1. lock the Sale row (tenant-scoped) for the rest of the transaction
          2. reject an already-reversed sale
          3. compute what was actually COLLECTED from the ledger, not the cache
          4. reject a refund above that figure
          5. take the inventory item back with a guarded status transition
          6. append the negative REFUND row to the existing ledger
          7. write the immutable SaleReturn row
          8. move the sale's derived caches only
          9. audit, then commit once

        Step 1 serialises this against a concurrent collection on the same
        invoice, so an Admin cannot take a payment against a sale another Admin
        is reversing (record_payment additionally refuses a reversed sale).
        Step 5's guarded UPDATE and the unique constraint on
        sale_returns.sale_id are the two hard stops against a double return.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        sale = await SaleRepository.get_by_id_for_update(db, sale_id, current_user.tenant_id)
        if not sale:
            raise ResourceNotFoundException(f"Sale '{sale_id}' not found")

        current_status = sale.sale_status or SALE_STATUS_COMPLETED
        if current_status != SALE_STATUS_COMPLETED:
            raise ConflictException(
                f"Invoice {sale.invoice_number} is already {current_status.lower()} and cannot be "
                f"reversed again."
            )
        if await SaleReturnRepository.get_by_sale(db, sale_id, current_user.tenant_id):
            raise ConflictException(
                f"A return has already been processed against invoice {sale.invoice_number}."
            )

        collected = _round2(
            await SalePaymentRepository.sum_for_sale(db, sale_id, current_user.tenant_id)
        )
        # sum_for_sale counts SCHEME_REDEMPTION as settlement. The scheme portion
        # is customer credit, NOT cash — it is restored to the enrollment below,
        # never handed back as money. Only the real cash collected is refundable.
        scheme_rows = await SalePaymentRepository.scheme_redemption_rows_for_sale(
            db, sale_id, current_user.tenant_id
        )
        scheme_settled = _round2(sum(r.amount for r in scheme_rows))
        cash_collected = _round2(collected - scheme_settled)
        already_refunded = _round2(
            await SalePaymentRepository.sum_refunds_for_sale(db, sale_id, current_user.tenant_id)
        )
        refundable = _round2(max(0.0, cash_collected - already_refunded))

        # Default: hand back exactly the CASH collected. Never the invoice total
        # (unpaid balance was never received) and never the scheme portion (that
        # is restored to the enrollment, not refunded).
        refund_amount = refundable if req.refund_amount is None else _round2(req.refund_amount)
        if refund_amount < 0:
            raise ValidationException("Refund amount cannot be negative")
        if refund_amount > refundable + _MONEY_EPSILON:
            raise ValidationException(
                f"Refund of {refund_amount} exceeds the {refundable} cash actually collected on "
                f"invoice {sale.invoice_number}. The store cannot refund money it never received; the "
                f"unpaid balance is written off and any scheme credit is restored, not refunded."
            )
        if refund_amount > 0 and not req.refund_method:
            raise ValidationException("A refund method is required when money is being refunded")

        outstanding_written_off = _round2(max(0.0, sale.final_amount - collected))

        # Inventory comes back as the SAME original item — never a new row, and
        # never straight into sellable stock.
        moved = await InventoryRepository.transition_stock_status(
            db,
            sale.inventory_item_id,
            current_user.tenant_id,
            expected_from=STOCK_STATUS_SOLD,
            to_status=STOCK_STATUS_RETURNED_PENDING_INSPECTION,
        )
        if not moved:
            item = await InventoryRepository.get_by_id(
                db, sale.inventory_item_id, current_user.tenant_id
            )
            found = item.stock_status if item else "MISSING"
            raise ConflictException(
                f"Inventory item {sale.product_code} is not in SOLD state (current: {found}) and "
                f"cannot be taken back against invoice {sale.invoice_number}."
            )

        now = datetime.now(timezone.utc)
        if refund_amount > 0:
            refund_row = SalePayment(
                id=f"sp_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                sale_id=sale.id,
                # Negative on purpose: the ledger stays append-only and sums to
                # the invoice's net cash position. No collection row is touched.
                amount=-refund_amount,
                payment_date=req.refund_date or datetime.now(IST).date(),
                payment_method=req.refund_method,
                source=PAYMENT_SOURCE_REFUND,
                reference_no=req.refund_reference_no,
                remarks=f"Refund on {req.return_type.lower()}: {req.reason}"[:500],
                recorded_by=current_user.id,
            )
            await SalePaymentRepository.create(db, refund_row)

        sale_return = SaleReturn(
            id=f"sr_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            inventory_item_id=sale.inventory_item_id,
            product_code=sale.product_code,
            return_type=req.return_type,
            reason=req.reason,
            original_sale_amount=_round2(sale.final_amount),
            amount_collected_at_return=collected,
            refund_amount=refund_amount,
            outstanding_written_off=outstanding_written_off,
            refund_method=req.refund_method,
            refund_reference_no=req.refund_reference_no,
            inspection_status=INSPECTION_PENDING,
            returned_at=now,
            processed_by=current_user.id,
        )
        await SaleReturnRepository.create(db, sale_return)

        # Restore scheme credit (Option 1): reverse each SCHEME_REDEMPTION that
        # settled this sale by appending a NEGATIVE scheme_redemptions row, which
        # nets in the derived balance (contributions - SUM(redemptions)). The
        # original redemption row is never deleted or mutated. An enrollment that
        # was flipped REDEEMED only because its balance hit zero is reopened —
        # to CLOSED if it had been closed (redeemable, not contributable), else
        # ACTIVE. Rows grouped by enrollment so a multi-enrollment sale restores
        # each correctly. Later redemptions from the same enrollment are untouched,
        # so the balance can never inflate past true entitlement.
        restored_total = 0.0
        by_enrollment: dict = {}
        for r in scheme_rows:
            if r.enrollment_id:
                by_enrollment[r.enrollment_id] = _round2(by_enrollment.get(r.enrollment_id, 0.0) + r.amount)
        for enrollment_id, amt in by_enrollment.items():
            amt = _round2(amt)
            if amt <= 0:
                continue
            enrollment = await EnrollmentRepository.get_enrollment_by_id_for_update(
                db, enrollment_id, current_user.tenant_id
            )
            if not enrollment:
                continue
            reversal = SchemeRedemption(
                id=f"srd_{uuid.uuid4().hex[:12]}",
                tenant_id=current_user.tenant_id,
                enrollment_id=enrollment_id,
                customer_id=enrollment.customer_id,
                sale_id=sale.id,
                invoice_number=sale.invoice_number,
                amount=-amt,
                redeemed_at=now,
                recorded_by=current_user.id,
            )
            await SchemeRedemptionRepository.create(db, reversal)
            if enrollment.status == ENR_REDEEMED:
                enrollment.status = ENR_CLOSED if enrollment.closed_at else ENR_ACTIVE
            restored_total = _round2(restored_total + amt)

        # Derived caches only. Every historical/financial column on the Sale —
        # including final_amount and amount_paid — is left exactly as recorded.
        total_refunded = _round2(already_refunded + refund_amount)
        sale.amount_refunded = total_refunded
        sale.sale_status = (
            SALE_STATUS_CANCELLED
            if req.return_type == RETURN_TYPE_CANCELLATION
            else SALE_STATUS_RETURNED
        )
        previous_payment_status = sale.payment_status
        # Refund completeness is measured against CASH collected: the scheme
        # portion was restored to the enrollment, not refunded, so it must not
        # drag the status to PARTIALLY_REFUNDED.
        sale.payment_status = _derive_refund_status(cash_collected, total_refunded)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SALE_RETURN_PROCESS",
            target_entity="sale_returns",
            target_id=sale_return.id,
            before_state={
                "sale_status": current_status,
                "payment_status": previous_payment_status,
                "amount_paid": _round2(sale.amount_paid or 0),
                "stock_status": STOCK_STATUS_SOLD,
            },
            after_state={
                "sale_id": sale.id,
                "invoice_number": sale.invoice_number,
                "inventory_item_id": sale.inventory_item_id,
                "product_code": sale.product_code,
                "return_type": sale_return.return_type,
                "reason": sale_return.reason,
                "original_sale_amount": sale_return.original_sale_amount,
                "amount_collected": collected,
                "refund_amount": refund_amount,
                "cash_collected": cash_collected,
                "scheme_restored": restored_total,
                "outstanding_written_off": outstanding_written_off,
                "refund_method": sale_return.refund_method,
                "stock_status": STOCK_STATUS_RETURNED_PENDING_INSPECTION,
                "sale_status": sale.sale_status,
                "payment_status": sale.payment_status,
                "returned_at": now.isoformat(),
                "processed_by": current_user.id,
            },
        )

        await db.commit()
        return await SaleReturnService.get_for_sale(db, current_user, sale_id)

    @staticmethod
    async def record_inspection(
        db: AsyncSession, current_user: User, sale_id: str, req: SaleReturnInspectionRequest
    ) -> SaleReturnResponse:
        """The explicit second step of the inventory lifecycle:

            SOLD -> RETURNED_PENDING_INSPECTION -> IN_STOCK | DAMAGED

        A returned jewellery item is never silently resellable. RESALABLE puts
        the SAME original item back into IN_STOCK; DAMAGED keeps it out of
        sellable stock permanently. Guarded transition, so two Admins cannot
        both decide the same item's fate.
        """
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        row = await SaleReturnRepository.get_by_sale_for_update(db, sale_id, current_user.tenant_id)
        if not row:
            raise ResourceNotFoundException(f"No return recorded against sale '{sale_id}'")
        if row.inspection_status != INSPECTION_PENDING:
            raise ConflictException(
                f"The return on invoice {row.invoice_number} was already inspected "
                f"({row.inspection_status})."
            )

        to_status = (
            STOCK_STATUS_IN_STOCK if req.outcome == INSPECTION_RESALABLE else STOCK_STATUS_DAMAGED
        )
        moved = await InventoryRepository.transition_stock_status(
            db,
            row.inventory_item_id,
            current_user.tenant_id,
            expected_from=STOCK_STATUS_RETURNED_PENDING_INSPECTION,
            to_status=to_status,
        )
        if not moved:
            item = await InventoryRepository.get_by_id(
                db, row.inventory_item_id, current_user.tenant_id
            )
            found = item.stock_status if item else "MISSING"
            raise ConflictException(
                f"Item {row.product_code} is not awaiting inspection (current: {found})."
            )

        before_status = row.inspection_status
        row.inspection_status = (
            INSPECTION_RESALABLE if req.outcome == INSPECTION_RESALABLE else INSPECTION_DAMAGED
        )
        row.inspection_notes = req.notes
        row.inspected_at = datetime.now(timezone.utc)
        row.inspected_by = current_user.id

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="SALE_RETURN_INSPECT",
            target_entity="sale_returns",
            target_id=row.id,
            before_state={
                "inspection_status": before_status,
                "stock_status": STOCK_STATUS_RETURNED_PENDING_INSPECTION,
            },
            after_state={
                "invoice_number": row.invoice_number,
                "inventory_item_id": row.inventory_item_id,
                "product_code": row.product_code,
                "inspection_status": row.inspection_status,
                "inspection_notes": row.inspection_notes,
                "stock_status": to_status,
                "inspected_by": current_user.id,
            },
        )

        await db.commit()
        return await SaleReturnService.get_for_sale(db, current_user, sale_id)



class BillDraftService:
    """Server-side unfinished bills. A draft is never a Sale and lives in its
    own table, so it can never touch inventory, scheme balances or any financial
    total until it is finalized. Finalization reuses SaleService.create_sale and
    the existing scheme-redemption engine verbatim — no financial logic is
    duplicated here.

    Ownership: Admin/SuperAdmin see and act on every draft in their tenant;
    Staff only on drafts they created. Enforced by passing owner_id into every
    repository read (None for privileged, current_user.id for Staff)."""

    @staticmethod
    def _owner_scope(current_user: User) -> Optional[str]:
        return None if _is_privileged(current_user) else current_user.id

    @staticmethod
    def _to_response(draft: BillDraft) -> BillDraftResponse:
        return BillDraftResponse.model_validate(draft)

    @staticmethod
    async def create_draft(
        db: AsyncSession, current_user: User, req: BillDraftCreateRequest
    ) -> BillDraftResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        draft = BillDraft(
            id=f"bd_{uuid.uuid4().hex[:12]}",
            tenant_id=current_user.tenant_id,
            created_by=current_user.id,
            status=BILL_DRAFT_OPEN,
            product_code=req.product_code,
            customer_id=req.customer_id,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            customer_query=req.customer_query,
            customer_price=req.customer_price,
            gst_applied=req.gst_applied,
            making_charge_value=req.making_charge_value,
            wastage_value=req.wastage_value,
            gold_profit_percent=req.gold_profit_percent,
            discount_amount=req.discount_amount,
            payment_method=req.payment_method,
            payment_status=req.payment_status,
            initial_payment=req.initial_payment,
            scheme_amounts=req.scheme_amounts or None,
            note=req.note,
        )
        await BillDraftRepository.create(db, draft)
        await db.commit()
        refreshed = await BillDraftRepository.get_by_id(db, draft.id, current_user.tenant_id)
        return BillDraftService._to_response(refreshed)

    @staticmethod
    async def list_drafts(
        db: AsyncSession,
        current_user: User,
        status: Optional[str] = None,
        product_code: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> List[BillDraftListItem]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rows = await BillDraftRepository.list_drafts(
            db, current_user.tenant_id, BillDraftService._owner_scope(current_user),
            status, product_code, customer_id,
        )
        return [BillDraftListItem.model_validate(r) for r in rows]

    @staticmethod
    async def get_draft(
        db: AsyncSession, current_user: User, draft_id: str
    ) -> BillDraftResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        draft = await BillDraftRepository.get_by_id(
            db, draft_id, current_user.tenant_id, BillDraftService._owner_scope(current_user)
        )
        if not draft:
            raise ResourceNotFoundException(f"Bill draft '{draft_id}' not found")
        return BillDraftService._to_response(draft)

    @staticmethod
    async def update_draft(
        db: AsyncSession, current_user: User, draft_id: str, req: BillDraftUpdateRequest
    ) -> BillDraftResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        draft = await BillDraftRepository.get_by_id_for_update(
            db, draft_id, current_user.tenant_id, BillDraftService._owner_scope(current_user)
        )
        if not draft:
            raise ResourceNotFoundException(f"Bill draft '{draft_id}' not found")
        if draft.status != BILL_DRAFT_OPEN:
            raise ConflictException(f"Bill draft is '{draft.status}' and can no longer be edited")

        for field in (
            "product_code", "customer_id", "customer_name", "customer_phone", "customer_query",
            "customer_price", "gst_applied", "making_charge_value", "wastage_value",
            "gold_profit_percent", "discount_amount", "payment_method", "payment_status",
            "initial_payment", "note",
        ):
            val = getattr(req, field, None)
            if val is not None:
                setattr(draft, field, val)
        if req.scheme_amounts is not None:
            draft.scheme_amounts = req.scheme_amounts or None

        await db.commit()
        refreshed = await BillDraftRepository.get_by_id(db, draft_id, current_user.tenant_id)
        return BillDraftService._to_response(refreshed)

    @staticmethod
    async def discard_draft(db: AsyncSession, current_user: User, draft_id: str) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        draft = await BillDraftRepository.get_by_id_for_update(
            db, draft_id, current_user.tenant_id, BillDraftService._owner_scope(current_user)
        )
        if not draft:
            raise ResourceNotFoundException(f"Bill draft '{draft_id}' not found")
        if draft.status == BILL_DRAFT_FINALIZED:
            raise ConflictException("A finalized draft cannot be discarded")
        draft.status = BILL_DRAFT_DISCARDED
        await db.commit()

    @staticmethod
    async def finalize_draft(
        db: AsyncSession, current_user: User, draft_id: str, req: BillDraftFinalizeRequest
    ) -> SaleResponse:
        """Convert an OPEN draft into exactly one finalized Sale.

        Reuses SaleService.create_sale verbatim (recompute-from-live pricing +
        atomic inventory SOLD + snapshot). Stored draft pricing is treated as
        INPUT only; every money figure is recomputed from the live item and gold
        rate.

        Scheme selection: the scheme-redemption OTP is issued PER SALE
        (OtpService.create_redemption_challenge needs an existing sale_id), and a
        draft has no sale until this call runs — so scheme credit cannot be
        applied inside finalize. When the draft carries a scheme selection the
        sale is created PENDING (its outstanding preserved) and the caller then
        settles it through the existing per-sale request-otp + redeem-schemes
        flow, exactly as the live sell screen does. draft.scheme_amounts is
        carried on the response's caller so the frontend can drive that step.

        Idempotency / double-finalize: the draft is row-locked and checked OPEN
        before anything runs; a second finalize sees a non-OPEN status and is
        rejected. If the item was sold elsewhere between save and finalize,
        create_sale raises (item not IN_STOCK) and the draft is left OPEN with no
        partial Sale."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        draft = await BillDraftRepository.get_by_id_for_update(
            db, draft_id, current_user.tenant_id, BillDraftService._owner_scope(current_user)
        )
        if not draft:
            raise ResourceNotFoundException(f"Bill draft '{draft_id}' not found")
        if draft.status != BILL_DRAFT_OPEN:
            raise ConflictException(f"Bill draft is '{draft.status}' and cannot be finalized again")

        has_scheme = bool({k: v for k, v in (draft.scheme_amounts or {}).items() if float(v) > 0})

        # Build the sale request from the draft's INPUTS. When scheme credit will
        # settle part of the bill, the sale is created PENDING so its outstanding
        # is preserved for the subsequent per-sale scheme redemption step.
        sale_req = SaleCreateRequest(
            product_code=draft.product_code,
            customer_id=draft.customer_id,
            customer_name=draft.customer_name,
            customer_phone=draft.customer_phone,
            discount_amount=draft.discount_amount or 0,
            customer_price=draft.customer_price,
            making_charge_value=draft.making_charge_value,
            wastage_value=draft.wastage_value,
            gold_profit_percent=draft.gold_profit_percent,
            gst_applied=draft.gst_applied,
            payment_method=draft.payment_method,
            payment_status=("PENDING" if has_scheme else draft.payment_status),
            initial_payment_amount=(
                draft.initial_payment if (not has_scheme and draft.payment_status == "PARTIAL") else None
            ),
        )
        sale = await SaleService.create_sale(db, current_user, sale_req)

        # Flip the draft to FINALIZED. Re-lock in this transaction; a racing
        # finalize is impossible because create_sale already marked the item SOLD
        # (a second attempt would have failed above).
        locked = await BillDraftRepository.get_by_id_for_update(
            db, draft_id, current_user.tenant_id
        )
        locked.status = BILL_DRAFT_FINALIZED
        locked.finalized_sale_id = sale.id
        await AuditRepository.create_log(
            db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
            actor_name=current_user.name, actor_role=current_user.role.name,
            action="BILL_DRAFT_FINALIZE", target_entity="bill_drafts", target_id=draft_id,
            before_state={"status": BILL_DRAFT_OPEN},
            after_state={"status": BILL_DRAFT_FINALIZED, "finalized_sale_id": sale.id},
        )
        await db.commit()

        return await SaleService.get_sale(db, current_user, sale.id)


class QuotationService:
    """Phase 4 — generate a QUOTATION ('sample bill'): the full computed bill a
    customer is handed before buying. It reuses the SAME BillingCalculationEngine
    a real sale uses, so the printed figures match a future finalize, but it
    NEVER marks the item SOLD and NEVER spends a scheme balance (scheme amounts
    are a read-only preview). It lives in its own table, so no financial query
    ever reads it."""

    @staticmethod
    def _quotation_number() -> str:
        return f"QTN-{date.today():%y%m%d}-{uuid.uuid4().hex[:6].upper()}"

    @staticmethod
    async def _scheme_preview(db, current_user, customer_id, scheme_amounts, invoice_total):
        """Read-only preview of what the customer's scheme balances WOULD cover.
        Caps mirror the real redemption path exactly (per enrollment <= available
        balance derived from the ledgers; combined <= the invoice). Writes nothing."""
        items: list = []
        applied_total = 0.0
        remaining = invoice_total
        for enr_id, requested in (scheme_amounts or {}).items():
            requested = _round2(requested)
            if requested <= 0:
                continue
            enr = await EnrollmentRepository.get_enrollment_by_id(db, enr_id, current_user.tenant_id)
            if not enr:
                raise ResourceNotFoundException(f"Enrollment '{enr_id}' not found")
            if enr.customer_id != customer_id:
                raise ValidationException(
                    f"Enrollment {enr.enrollment_number} does not belong to this customer"
                )
            if enr.status not in REDEEMABLE_STATUSES:
                raise ValidationException(
                    f"Enrollment {enr.enrollment_number} is {enr.status.lower()} and its balance "
                    f"cannot be applied."
                )
            paid = await SchemeRedemptionRepository.sum_successful_contributions(
                db, enr.id, current_user.tenant_id
            )
            spent = await SchemeRedemptionRepository.sum_for_enrollment(
                db, enr.id, current_user.tenant_id
            )
            available = _round2(max(0.0, paid - spent))
            applied = _round2(min(requested, available, remaining))
            remaining = _round2(max(0.0, remaining - applied))
            applied_total = _round2(applied_total + applied)
            items.append(QuotationSchemePreviewItem(
                enrollment_id=enr.id,
                enrollment_number=enr.enrollment_number,
                requested_amount=requested,
                available_balance=available,
                applied_amount=applied,
            ))
        return items, applied_total

    @staticmethod
    def _to_response(q: Quotation, current_user: User, breakdown, preview) -> QuotationResponse:
        privileged = _is_privileged(current_user)
        # Mask internal store margin in the printed breakdown and withhold the
        # P/L label from Staff (Staff Financial Visibility baseline) — same
        # treatment as SaleService.get_quote / SaleService._build_response.
        breakdown_out = (
            breakdown if privileged
            else breakdown.model_copy(update={"gold_profit_percent": None, "gold_profit_amount": None})
        )
        return QuotationResponse(
            id=q.id,
            tenant_id=q.tenant_id,
            quotation_number=q.quotation_number,
            inventory_item_id=q.inventory_item_id,
            product_code=q.product_code,
            product_name=q.product_name,
            customer_id=q.customer_id,
            customer_name=q.customer_name,
            customer_phone=q.customer_phone,
            breakdown=breakdown_out,
            gst_applied=q.gst_applied,
            final_amount=_round2(q.final_amount),
            scheme_amount_total=_round2(q.scheme_amount_total or 0),
            outstanding_amount=_round2(q.outstanding_amount),
            scheme_preview=preview,
            estimated_gross_margin=q.estimated_gross_margin if privileged else None,
            profit_or_loss_label=q.profit_or_loss_label if privileged else None,
            note=q.note,
            created_by=q.created_by,
            created_at=q.created_at,
        )

    @staticmethod
    def _rebuild_view(q: Quotation, current_user: User) -> QuotationResponse:
        """Reconstruct a response from a stored quotation (list/get reprint)."""
        breakdown = PriceBreakdown(**q.breakdown_json)
        preview = [
            QuotationSchemePreviewItem(**i)
            for i in ((q.scheme_breakdown_json or {}).get("items", []))
        ]
        return QuotationService._to_response(q, current_user, breakdown, preview)

    @staticmethod
    async def generate(db: AsyncSession, current_user: User, req: QuotationCreateRequest) -> QuotationResponse:
        await SaleService._validate_customer_id(db, current_user, req.customer_id)
        item, rate = await SaleService._get_sellable_item_and_rate(db, current_user, req.product_code)
        breakdown = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            req.discount_amount, req.gst_applied, req.customer_price,
            req.making_charge_value, req.wastage_value, req.gold_profit_percent,
            req.making_charge_type, req.wastage_type,
        )
        invoice_total = breakdown.final_amount

        preview, scheme_total = await QuotationService._scheme_preview(
            db, current_user, req.customer_id, req.scheme_amounts, invoice_total
        )
        outstanding = _round2(max(0.0, invoice_total - scheme_total))

        # Same profit definition and gating as a real sale.
        margin = BillingCalculationEngine.realized_profit_or_loss(
            invoice_total, breakdown.tax_rate_percent, breakdown.gst_applied, item.purchase_cost
        )
        label = _pl_label(margin)

        q_id = f"qtn_{uuid.uuid4().hex[:12]}"
        quotation = Quotation(
            id=q_id,
            tenant_id=current_user.tenant_id,
            quotation_number=QuotationService._quotation_number(),
            inventory_item_id=item.id,  # reference only — NEVER marked SOLD
            product_code=item.product_code,
            product_name=item.product_name,
            customer_id=req.customer_id,
            customer_name=req.customer_name,
            customer_phone=req.customer_phone,
            gst_applied=breakdown.gst_applied,
            final_amount=invoice_total,
            scheme_amount_total=scheme_total,
            outstanding_amount=outstanding,
            breakdown_json=breakdown.model_dump(mode="json"),
            scheme_breakdown_json={"items": [p.model_dump(mode="json") for p in preview]} if preview else None,
            estimated_gross_margin=margin,
            profit_or_loss_label=label,
            note=req.note,
            created_by=current_user.id,
        )
        await QuotationRepository.create(db, quotation)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="QUOTATION_CREATE",
            target_entity="quotations",
            target_id=q_id,
            before_state=None,
            after_state={
                "quotation_number": quotation.quotation_number,
                "product_code": item.product_code,
                "final_amount": invoice_total,
                "scheme_amount_total": scheme_total,
                "outstanding_amount": outstanding,
            },
        )

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException("Could not generate a unique quotation number. Please try again.")

        quotation = await QuotationRepository.get_by_id(db, q_id, current_user.tenant_id)
        return QuotationService._to_response(quotation, current_user, breakdown, preview)

    @staticmethod
    async def get_quotation(db: AsyncSession, current_user: User, quotation_id: str) -> QuotationResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        q = await QuotationRepository.get_by_id(db, quotation_id, current_user.tenant_id)
        if not q:
            raise ResourceNotFoundException(f"Quotation '{quotation_id}' not found")
        return QuotationService._rebuild_view(q, current_user)

    @staticmethod
    async def get_quotation_orm(db: AsyncSession, current_user: User, quotation_id: str) -> Quotation:
        """Tenant-scoped ORM fetch for the PDF export — same authorization and
        tenant isolation as get_quotation, returning the frozen row itself so the
        exporter reads the stored breakdown snapshot without a recompute."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        q = await QuotationRepository.get_by_id(db, quotation_id, current_user.tenant_id)
        if not q:
            raise ResourceNotFoundException(f"Quotation '{quotation_id}' not found")
        return q

    @staticmethod
    async def list_quotations(db: AsyncSession, current_user: User) -> QuotationListResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        rows = await QuotationRepository.list_by_tenant(db, current_user.tenant_id)
        return QuotationListResponse(
            quotations=[QuotationService._rebuild_view(q, current_user) for q in rows],
            total=len(rows),
        )
