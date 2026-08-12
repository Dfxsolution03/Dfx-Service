import uuid
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import PURITY_KARATS, ROLE_ADMIN, ROLE_SUPERADMIN
from app.models.auth import User
from app.models.billing import Vendor, InventoryItem, Sale
from app.repositories.billing_repository import VendorRepository, InventoryRepository, SaleRepository
from app.repositories.audit_repository import AuditRepository
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
    InventoryItemCreateRequest,
    InventoryItemUpdateRequest,
    InventoryItemResponse,
    InventoryItemListResponse,
    BulkPurchaseRequest,
    BulkPurchaseResponse,
    PriceBreakdown,
    SaleQuoteResponse,
    SaleCreateRequest,
    SaleResponse,
    SaleListResponse,
    BillingPeriodSummary,
    RecentSaleSummary,
    BillingDashboardSummaryResponse,
)


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


class BillingCalculationEngine:
    """The one place a sale's price is computed — used identically by the
    ephemeral quote (SaleService.get_quote) and the persisted sale
    (SaleService.create_sale), so a confirmed sale is always priced by
    exactly the same math the staff member previewed. Deterministic: same
    item + same gold rate + same discount always produces the same
    breakdown."""

    @staticmethod
    def calculate(
        item: InventoryItem,
        rate_24k: float,
        rate_source: str,
        rate_effective_date: date,
        discount_amount: float,
        gst_applied: bool = True,
        customer_price: Optional[float] = None,
    ) -> PriceBreakdown:
        karat = PURITY_KARATS.get(item.purity)
        if karat is None:
            raise ValidationException(f"Unsupported purity '{item.purity}'")
        purity_factor = karat / 24.0
        gold_rate_applied = rate_24k * purity_factor
        gold_value_amount = item.net_gold_weight_grams * gold_rate_applied

        making_charge_amount = _charge_amount(
            item.making_charge_type, item.making_charge_value, item.net_gold_weight_grams, gold_value_amount
        )
        wastage_amount = _charge_amount(
            item.wastage_type, item.wastage_value, item.net_gold_weight_grams, gold_value_amount
        )

        subtotal_before_tax = (
            gold_value_amount
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
            making_charge_type=item.making_charge_type,
            making_charge_value=item.making_charge_value,
            making_charge_amount=_round2(making_charge_amount),
            wastage_type=item.wastage_type,
            wastage_value=item.wastage_value,
            wastage_amount=_round2(wastage_amount),
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
        for field in ["name", "contact_person", "phone", "email", "address", "gst_number", "is_active"]:
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
            stone_charge_amount=item.stone_charge_amount,
            other_charges_amount=item.other_charges_amount,
            tax_rate_percent=item.tax_rate_percent,
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
    ) -> InventoryItemListResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        items, total = await InventoryRepository.list_by_tenant(
            db, current_user.tenant_id, page, limit, search, stock_status, category, vendor_id
        )
        return InventoryItemListResponse(
            items=[InventoryService._build_response(i, current_user) for i in items], total=total
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

        existing = await InventoryRepository.get_by_product_code(
            db, req.product_code, current_user.tenant_id
        )
        if existing:
            raise ConflictException(f"Product code '{req.product_code}' is already in use")

        vendor_id, vendor_name = await InventoryService._resolve_vendor_snapshot(
            db, current_user, req.vendor_id, req.vendor_name
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
            stock_status="IN_STOCK",
            making_charge_type=req.making_charge_type,
            making_charge_value=req.making_charge_value,
            wastage_type=req.wastage_type,
            wastage_value=req.wastage_value,
            stone_charge_amount=req.stone_charge_amount,
            other_charges_amount=req.other_charges_amount,
            tax_rate_percent=req.tax_rate_percent,
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
            "gross_weight_grams", "net_gold_weight_grams", "vendor_name",
            "purchase_date", "purchase_invoice_ref", "purchase_cost",
            "making_charge_type", "making_charge_value", "wastage_type", "wastage_value",
            "stone_charge_amount", "other_charges_amount", "tax_rate_percent", "stock_status",
        ]
        for field in fields:
            val = getattr(req, field, None)
            if val is not None:
                setattr(item, field, val)

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
                stone_charge_amount=line.stone_charge_amount,
                other_charges_amount=line.other_charges_amount,
                tax_rate_percent=line.tax_rate_percent,
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
            purchase_cost_snapshot=sale.purchase_cost_snapshot if privileged else None,
            estimated_gross_margin=sale.estimated_gross_margin if privileged else None,
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
    ) -> SaleQuoteResponse:
        item, rate = await SaleService._get_sellable_item_and_rate(db, current_user, product_code)
        breakdown = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            discount_amount, gst_applied, customer_price,
        )
        return SaleQuoteResponse(
            inventory_item=InventoryService._build_response(item, current_user),
            breakdown=breakdown,
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
    async def create_sale(db: AsyncSession, current_user: User, req: SaleCreateRequest) -> SaleResponse:
        await SaleService._validate_customer_id(db, current_user, req.customer_id)
        item, rate = await SaleService._get_sellable_item_and_rate(db, current_user, req.product_code)
        breakdown = BillingCalculationEngine.calculate(
            item, rate.rate_24k, rate.source or "MANUAL", rate.effective_date,
            req.discount_amount, req.gst_applied, req.customer_price,
        )

        sold = await InventoryRepository.mark_sold_if_in_stock(db, item.id, current_user.tenant_id)
        if not sold:
            await db.rollback()
            raise ConflictException(
                f"Product '{req.product_code}' was just sold in another transaction. Please rescan."
            )

        purchase_cost_snapshot = item.purchase_cost
        estimated_gross_margin = (
            _round2(breakdown.subtotal_before_tax - purchase_cost_snapshot)
            if purchase_cost_snapshot is not None
            else None
        )

        sale_id = f"sl_{uuid.uuid4().hex[:12]}"
        sale = Sale(
            id=sale_id,
            tenant_id=current_user.tenant_id,
            invoice_number=SaleService._generate_invoice_number(),
            inventory_item_id=item.id,
            customer_id=req.customer_id,
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
            stone_charge_amount=breakdown.stone_charge_amount,
            other_charges_amount=breakdown.other_charges_amount,
            subtotal_before_tax=breakdown.subtotal_before_tax,
            gst_applied=breakdown.gst_applied,
            tax_rate_percent=breakdown.tax_rate_percent,
            tax_amount=breakdown.tax_amount,
            discount_amount=breakdown.discount_amount,
            final_amount=breakdown.final_amount,
            payment_method=req.payment_method,
            payment_status=req.payment_status,
            purchase_cost_snapshot=purchase_cost_snapshot,
            estimated_gross_margin=estimated_gross_margin,
            sale_timestamp=datetime.now(timezone.utc),
            created_by=current_user.id,
        )
        await SaleRepository.create(db, sale)

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
    ) -> SaleListResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")
        sales, total = await SaleRepository.list_by_tenant(
            db, current_user.tenant_id, page, limit, search, date_from, date_to
        )
        return SaleListResponse(
            sales=[SaleService._build_response(s, current_user) for s in sales], total=total
        )

    @staticmethod
    async def get_dashboard_summary(db: AsyncSession, current_user: User) -> BillingDashboardSummaryResponse:
        """Powers the Admin Dashboard's Billing Summary — every figure is
        aggregated straight off finalized Sale rows (see
        SaleRepository.get_period_summary's own docstring); nothing here is
        recomputed against today's live gold rate."""
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        now_ist = datetime.now(IST)
        today_start = datetime.combine(now_ist.date(), datetime.min.time(), tzinfo=IST)
        today_end = datetime.combine(now_ist.date(), datetime.max.time(), tzinfo=IST)
        month_start = today_start.replace(day=1)

        today_raw = await SaleRepository.get_period_summary(db, current_user.tenant_id, today_start, today_end)
        month_raw = await SaleRepository.get_period_summary(db, current_user.tenant_id, month_start, today_end)
        recent = await SaleRepository.get_recent(db, current_user.tenant_id, limit=5)
        rate = await GoldRateService.get_customer_today_rate(db, current_user)

        return BillingDashboardSummaryResponse(
            today=BillingPeriodSummary(**today_raw),
            this_month=BillingPeriodSummary(**month_raw),
            today_gold_rate_24k=rate.rate_24k if rate else None,
            recent_sales=[
                RecentSaleSummary(
                    id=s.id,
                    invoice_number=s.invoice_number,
                    customer_name=s.customer_name,
                    product_code=s.product_code,
                    product_name=s.product_name,
                    final_amount=s.final_amount,
                    profit_or_loss=s.estimated_gross_margin,
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
        return SaleService._build_response(sale, current_user)

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
