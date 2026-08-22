from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.config import settings
from app.models.auth import User, Tenant
from app.permissions.dependencies import require_admin_or_staff_module
from app.schemas.auth import StandardSuccessResponse
from app.schemas.billing import (
    VendorCreateRequest,
    VendorUpdateRequest,
    CategoryDefaultUpsertRequest,
    StoreDefaultsUpdateRequest,
    InventoryItemCreateRequest,
    InventoryItemUpdateRequest,
    BulkPurchaseRequest,
    PriceLinePreviewRequest,
    SaleCreateRequest,
    SalePaymentCreateRequest,
    SaleReturnCreateRequest,
    SaleReturnInspectionRequest,
    BillDraftCreateRequest,
    BillDraftUpdateRequest,
    BillDraftFinalizeRequest,
)
from app.services.billing_service import (
    VendorService,
    BillingDefaultsService,
    InventoryService,
    SaleService,
    SalePaymentService,
    SaleReturnService,
    BillDraftService,
    _is_privileged,
)
from app.schemas.catalogue import InventoryPublishRequest, InventoryBulkPublishRequest
from app.services.catalogue_service import CatalogueService
from app.services.enrollment_service import SchemeBalanceService
from app.services.otp_service import OtpService
from app.schemas.enrollment import MultiSchemeRedeemRequest
from app.services import billing_export_service
from app.exceptions.base import ValidationException

router = APIRouter()


# =============================================================================
# 0. Vendors
# =============================================================================

@router.post(
    "/billing/vendors",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Vendor (Admin)",
)
async def create_vendor(
    req: VendorCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    vendor = await VendorService.create_vendor(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Vendor created successfully", data={"vendor": vendor.model_dump(mode="json")})


@router.get(
    "/billing/vendors",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Vendors (Admin)",
)
async def list_vendors(
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    vendors = await VendorService.list_vendors(db, current_user, search)
    return StandardSuccessResponse(
        success=True, message="Vendors retrieved successfully", data={"vendors": [v.model_dump(mode="json") for v in vendors]}
    )


@router.put(
    "/billing/vendors/{vendor_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Vendor (Admin)",
)
async def update_vendor(
    vendor_id: str,
    req: VendorUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    vendor = await VendorService.update_vendor(db, current_user, vendor_id, req)
    return StandardSuccessResponse(success=True, message="Vendor updated successfully", data={"vendor": vendor.model_dump(mode="json")})


# =============================================================================
# 0b. Billing Defaults — Store / Category / Resolver
# =============================================================================

@router.get(
    "/billing/defaults/store",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Store Billing Defaults (Admin)",
)
async def get_store_defaults(
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await BillingDefaultsService.get_store_defaults(db, current_user)
    return StandardSuccessResponse(success=True, message="Store defaults retrieved successfully", data=result.model_dump(mode="json"))


@router.put(
    "/billing/defaults/store",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Store Billing Defaults (Admin)",
    description="Pre-fill source only — never changes any already-saved inventory or sale.",
)
async def update_store_defaults(
    req: StoreDefaultsUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await BillingDefaultsService.update_store_defaults(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Store defaults updated successfully", data=result.model_dump(mode="json"))


@router.get(
    "/billing/defaults/categories",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Category Pricing Defaults (Admin)",
)
async def list_category_defaults(
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    rows = await BillingDefaultsService.list_category_defaults(db, current_user)
    return StandardSuccessResponse(
        success=True, message="Category defaults retrieved successfully", data={"categories": [r.model_dump(mode="json") for r in rows]}
    )


@router.put(
    "/billing/defaults/categories",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Create/Update Category Pricing Default (Admin)",
    description="Upserts by category name — never changes any already-saved inventory or sale.",
)
async def upsert_category_default(
    req: CategoryDefaultUpsertRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await BillingDefaultsService.upsert_category_default(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Category default saved successfully", data=result.model_dump(mode="json"))


@router.get(
    "/billing/defaults/resolve",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve Field-by-Field Inventory Defaults (Admin)",
    description=(
        "For each configurable field independently: Vendor default -> Category default -> Store default. "
        "Pre-fill only — the caller must still save whatever value lands in the form."
    ),
)
async def resolve_defaults(
    vendor_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await BillingDefaultsService.resolve_defaults(db, current_user, vendor_id, category)
    return StandardSuccessResponse(success=True, message="Defaults resolved successfully", data=result.model_dump(mode="json"))


# =============================================================================
# 1. Inventory / Product Master
# =============================================================================

@router.post(
    "/billing/inventory",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Inventory Item (Admin)",
    description="Registers a finished jewellery item bought from a vendor, with a unique Product Code used later during Selling.",
)
async def create_inventory_item(
    req: InventoryItemCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    item = await InventoryService.create_item(db, current_user, req)
    return StandardSuccessResponse(
        success=True, message="Inventory item created successfully", data={"item": item.model_dump(mode="json")}
    )


@router.get(
    "/billing/inventory",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Inventory Items (Admin)",
)
async def list_inventory_items(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Matches product code or product name"),
    stock_status: Optional[str] = Query(None, description="IN_STOCK | SOLD | INACTIVE"),
    category: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await InventoryService.list_items(db, current_user, page, limit, search, stock_status, category, vendor_id)
    return StandardSuccessResponse(
        success=True,
        message="Inventory items retrieved successfully",
        data={"items": [i.model_dump(mode="json") for i in result.items], "total": result.total},
    )


@router.get(
    "/billing/inventory/{item_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Inventory Item (Admin)",
)
async def get_inventory_item(
    item_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    item = await InventoryService.get_item(db, current_user, item_id)
    return StandardSuccessResponse(
        success=True, message="Inventory item retrieved successfully", data={"item": item.model_dump(mode="json")}
    )


@router.put(
    "/billing/inventory/{item_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Inventory Item (Admin)",
    description="Rejected once the item has been sold, so a completed sale's historical record can never drift from what was actually sold.",
)
async def update_inventory_item(
    item_id: str,
    req: InventoryItemUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    item = await InventoryService.update_item(db, current_user, item_id, req)
    return StandardSuccessResponse(
        success=True, message="Inventory item updated successfully", data={"item": item.model_dump(mode="json")}
    )


@router.post(
    "/billing/inventory/{item_id}/image",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload Inventory Item Image (Admin)",
)
async def upload_inventory_item_image(
    item_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    content_type = file.content_type or ""
    file_bytes = await file.read()
    if not file_bytes:
        raise ValidationException("Uploaded file is empty.")
    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        max_mb = settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)
        raise ValidationException(f"Image exceeds the {max_mb}MB upload limit.")

    item = await InventoryService.upload_image(
        db, current_user, item_id, file_bytes, file.filename or "upload", content_type
    )
    return StandardSuccessResponse(
        success=True, message="Image uploaded successfully", data={"item": item.model_dump(mode="json")}
    )


@router.post(
    "/billing/inventory/publish-bulk",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish Inventory Items To Catalogue In Bulk (Admin)",
    description="Publishes many inventory items to the catalogue. Each item needs its own catalogue "
                "image; items that fail validation are reported individually and do not roll back the rest.",
)
async def publish_inventory_bulk(
    req: InventoryBulkPublishRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await CatalogueService.publish_inventory_bulk(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message=f"Published {result.published_count}, failed {result.failed_count}",
        data=result.model_dump(mode="json"),
    )


@router.post(
    "/billing/inventory/{item_id}/publish",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish Inventory Item To Catalogue (Admin)",
    description="Publishes (or idempotently re-publishes) one inventory item to the catalogue. "
                "SELLING_COST is server-calculated (client price rejected); CATALOGUE_COST is the "
                "admin's manual price. A catalogue image is mandatory; duplicate publishing updates "
                "the same linked product instead of creating a new one.",
)
async def publish_inventory_item(
    item_id: str,
    req: InventoryPublishRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    product = await CatalogueService.publish_inventory_item(db, current_user, item_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Inventory item published to catalogue",
        data={"product": product.model_dump(mode="json")},
    )


@router.post(
    "/billing/inventory/bulk-purchase",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk Purchase Entry (Admin)",
    description="One vendor/date/invoice header entered once, many finished-goods items created together in a single transaction.",
)
async def bulk_purchase(
    req: BulkPurchaseRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await InventoryService.bulk_create_items(db, current_user, req)
    return StandardSuccessResponse(
        success=True,
        message=f"{len(result.items)} inventory item(s) created successfully",
        data={"items": [i.model_dump(mode="json") for i in result.items]},
    )


@router.post(
    "/billing/inventory/preview-price",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Suggested Price / Profit for an unsaved row (Admin)",
    description="Bulk Inventory's live preview — reuses the same calculation engine Selling uses, against not-yet-saved field values. Nothing is persisted.",
)
async def preview_price(
    req: PriceLinePreviewRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await InventoryService.preview_price(db, current_user, req)
    return StandardSuccessResponse(success=True, message="Price preview calculated", data=result.model_dump(mode="json"))


# =============================================================================
# 2. Selling
# =============================================================================

@router.get(
    "/billing/sell/quote/{product_code}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sale Price Quote (Admin)",
    description=(
        "Scan/enter a Product Code to load the item and compute a full, transparent price breakdown "
        "using the current live gold rate and the item's stored charge rules. Ephemeral — nothing is "
        "persisted, and the eventual sale is always recomputed fresh at commit time."
    ),
)
async def get_sale_quote(
    product_code: str,
    discount_amount: float = Query(0, ge=0),
    gst_applied: bool = Query(True),
    customer_price: Optional[float] = Query(None, ge=0),
    making_charge_value: Optional[float] = Query(None, ge=0),
    wastage_value: Optional[float] = Query(None, ge=0),
    gold_profit_percent: Optional[float] = Query(None, ge=0, le=100),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    quote = await SaleService.get_quote(
        db, current_user, product_code, discount_amount, gst_applied, customer_price,
        making_charge_value, wastage_value, gold_profit_percent,
    )
    return StandardSuccessResponse(
        success=True, message="Quote calculated successfully", data=quote.model_dump(mode="json")
    )


@router.post(
    "/billing/sell",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete Sale (Admin)",
    description=(
        "Recomputes the price fresh (ignoring any client-supplied amounts), creates the permanent Sale "
        "record with a full snapshot of the pricing used, and marks the inventory item SOLD."
    ),
)
async def create_sale(
    req: SaleCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sale = await SaleService.create_sale(db, current_user, req)
    return StandardSuccessResponse(
        success=True, message="Sale completed successfully", data={"sale": sale.model_dump(mode="json")}
    )


@router.get(
    "/billing/dashboard-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Billing Dashboard Summary (Admin)",
    description="Today's and this-month's sales/profit/loss aggregated from finalized sale records, plus a caller-selected Business History period (via `period` or date_from/date_to) and the 5 most recent sales.",
)
async def get_billing_dashboard_summary(
    period: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    summary = await SaleService.get_dashboard_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True, message="Billing summary retrieved successfully", data=summary.model_dump(mode="json")
    )


@router.get(
    "/billing/business-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Business History Summary (Admin)",
    description="Sales/profit/loss/bills/items/tax/average-bill aggregated over a named `period` or an explicit date_from+date_to range, straight off finalized sale snapshots.",
)
async def get_business_summary(
    period: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    summary = await SaleService.get_business_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True, message="Business summary retrieved successfully", data=summary.model_dump(mode="json")
    )


@router.get(
    "/billing/receivables-summary",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Receivables Summary (Admin)",
    description=(
        "Read-only receivables over a named `period` or an explicit date_from+date_to range: "
        "total invoiced, total paid, total outstanding, and PAID/PARTIAL/PENDING counts. Derived "
        "from the SalePayment-synced sale columns; reversed sales are excluded, so this reflects "
        "only what customers still owe."
    ),
)
async def get_receivables_summary(
    period: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    summary = await SaleService.get_receivables_summary(db, current_user, period, date_from, date_to)
    return StandardSuccessResponse(
        success=True, message="Receivables summary retrieved successfully", data=summary.model_dump(mode="json")
    )


# =============================================================================
# 3. Sales History
# =============================================================================

@router.get(
    "/billing/sales",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Sales History (Admin)",
)
async def list_sales(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Matches invoice number, product code, or customer name"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    payment_status: Optional[str] = Query(
        None,
        pattern="^(PAID|PARTIAL|PENDING|REFUNDED|PARTIALLY_REFUNDED)$",
        description="Omit for ALL. Filters on the ledger-derived status, never a client-set label.",
    ),
    sale_status: Optional[str] = Query(
        None,
        pattern="^(COMPLETED|RETURNED|CANCELLED)$",
        description="Omit for ALL. The sale lifecycle, independent of the payment status.",
    ),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SaleService.list_sales(
        db, current_user, page, limit, search, date_from, date_to, payment_status, sale_status
    )
    return StandardSuccessResponse(
        success=True,
        message="Sales retrieved successfully",
        data={"sales": [s.model_dump(mode="json") for s in result.sales], "total": result.total},
    )


@router.get(
    "/billing/sales/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Download Sales History Excel (Admin)",
    description=(
        "Exports the sales history for the selected period and payment-status filter as one Excel "
        "workbook. Declared before /billing/sales/{sale_id} on purpose — otherwise 'export.xlsx' "
        "would match that path parameter."
    ),
)
async def download_sales_history_excel(
    period: Optional[str] = Query(
        None,
        description=(
            "today | yesterday | this_week | last_week | this_month | last_month | "
            "last_3_months | last_6_months | last_12_months. Ignored when both dates are given."
        ),
    ),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(
        None, pattern="^(PAID|PARTIAL|PENDING|REFUNDED|PARTIALLY_REFUNDED)$"
    ),
    sale_status: Optional[str] = Query(None, pattern="^(COMPLETED|RETURNED|CANCELLED)$"),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sales, payments_by_sale, period_label, sel_from, sel_to = await SaleService.list_for_export(
        db, current_user, period, date_from, date_to, search, payment_status, sale_status
    )
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    xlsx_bytes = billing_export_service.build_sales_history_excel(
        sales, payments_by_sale, tenant, period_label, payment_status or "ALL",
        include_internal=_is_privileged(current_user),
    )
    filename = f"sales-history-{sel_from.isoformat()}-to-{sel_to.isoformat()}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/billing/sales/ca-export.xlsx",
    summary="CA / Accounting Export (Admin)",
    description="Accounting-only xlsx over a period — established Sale/tax fields only, "
                "no internal margin, no invented GST/HSN fields. Returned/cancelled sales "
                "are included with their status so the accountant reconciles reversals.",
)
async def export_ca_xlsx(
    period: Optional[str] = Query(None, pattern="^(today|this_week|this_month|this_year|custom)$"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("reports")),
    db: AsyncSession = Depends(get_async_db),
):
    sales, _payments, period_label, sel_from, sel_to = await SaleService.list_for_export(
        db, current_user, period, date_from, date_to, None, None, None
    )
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    xlsx_bytes = billing_export_service.build_ca_export_excel(sales, tenant, period_label)
    filename = f"ca-export-{sel_from.isoformat()}-to-{sel_to.isoformat()}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/billing/sales/{sale_id}/payments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Invoice Payment History (Admin)",
)
async def list_sale_payments(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    history = await SalePaymentService.get_history(db, current_user, sale_id)
    return StandardSuccessResponse(
        success=True,
        message="Payment history retrieved successfully",
        data={"paymentHistory": history.model_dump(mode="json")},
    )


@router.post(
    "/billing/sales/{sale_id}/payments",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record Payment Against Invoice (Admin)",
    description=(
        "Appends one collection to the invoice's permanent payment ledger and recomputes the "
        "derived paid/outstanding/status figures in the same transaction. Never overwrites an "
        "earlier payment. Rejects a zero/negative amount, and rejects any amount above the "
        "outstanding balance (overpayments are not supported)."
    ),
)
async def record_sale_payment(
    sale_id: str,
    req: SalePaymentCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    history = await SalePaymentService.record_payment(db, current_user, sale_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Payment recorded successfully",
        data={"paymentHistory": history.model_dump(mode="json")},
    )


# =============================================================================
# 3b. Sale Return / Cancellation
# =============================================================================

@router.post(
    "/billing/sales/{sale_id}/redeem-schemes/request-otp",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send Scheme-Redemption OTP To The Customer App (Admin)",
    description=(
        "Generates a single-use, 5-minute verification code for the sale's customer and "
        "delivers it to their app as an IN_APP notification (never SMS/WhatsApp). The code "
        "must be entered back into the redeem-schemes call to authorise the redemption."
    ),
)
async def request_redemption_otp(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await OtpService.create_redemption_challenge(db, current_user, sale_id)
    return StandardSuccessResponse(
        success=True,
        message="Verification code sent to the customer's app",
        data={"otp": {"challenge_id": result["challenge_id"], "expires_at": result["expires_at"].isoformat()}},
    )


@router.post(
    "/billing/sales/{sale_id}/redeem-schemes",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Settle An Invoice From Several Scheme Balances (Admin)",
    description=(
        "Applies one or more of the customer's scheme balances to a single invoice in ONE "
        "transaction. Every enrollment is locked and fully validated (customer ownership, tenant, "
        "redeemable status, own balance) and the COMBINED amount is checked against the invoice's "
        "outstanding before anything is written, so a failure on one scheme leaves none of the "
        "others spent. Each scheme gets its own redemption and SCHEME_REDEMPTION ledger row, so the "
        "invoice always shows which scheme funded which rupee; scheme credit settles the invoice but "
        "is never counted as cash."
    ),
)
async def redeem_schemes_against_sale(
    sale_id: str,
    req: MultiSchemeRedeemRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    # Phase 5 gate: the customer-app OTP must verify (and is consumed) before any
    # scheme balance is touched. On an invalid/expired/exhausted code this raises
    # and the redemption engine never runs. The engine itself is unchanged.
    await OtpService.verify_and_consume(db, current_user, sale_id, req.otp_code)
    result = await SchemeBalanceService.redeem_multiple_against_sale(db, current_user, sale_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Scheme balances redeemed successfully",
        data={"settlement": result.model_dump(mode="json")},
    )


@router.get(
    "/billing/inventory/{inventory_item_id}/return",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Pending-Inspection Return For An Inventory Item (Admin)",
    description=(
        "Read-only. Returns the return record awaiting inspection for this inventory item, so the "
        "Inventory page can drive the same inspection action as Sales History. Tenant scoped; "
        "null when nothing is awaiting inspection."
    ),
)
async def get_inventory_item_return(
    inventory_item_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    record = await SaleReturnService.get_for_inventory_item(db, current_user, inventory_item_id)
    return StandardSuccessResponse(
        success=True,
        message="Inventory return retrieved successfully",
        data={"saleReturn": record.model_dump(mode="json") if record else None},
    )


@router.get(
    "/billing/sales/{sale_id}/return/preview",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Financial Impact Of Reversing A Sale (Admin)",
    description=(
        "Backend-computed impact of returning/cancelling this invoice: what was actually "
        "collected, the maximum refundable amount, the outstanding balance that would be written "
        "off, and the resulting inventory status. Read-only — nothing is stored or locked. The "
        "confirmation dialog must show these figures rather than any number computed in the "
        "browser."
    ),
)
async def preview_sale_return(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    preview = await SaleReturnService.preview(db, current_user, sale_id)
    return StandardSuccessResponse(
        success=True,
        message="Return preview generated successfully",
        data={"preview": preview.model_dump(mode="json")},
    )


@router.get(
    "/billing/sales/{sale_id}/return",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sale Return Record (Admin)",
)
async def get_sale_return(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    record = await SaleReturnService.get_for_sale(db, current_user, sale_id)
    return StandardSuccessResponse(
        success=True,
        message="Sale return retrieved successfully",
        data={"saleReturn": record.model_dump(mode="json") if record else None},
    )


@router.post(
    "/billing/sales/{sale_id}/return",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Return / Cancel A Sale (Admin)",
    description=(
        "Reverses one sale in a single transaction: takes the original inventory item back as "
        "RETURNED_PENDING_INSPECTION (never straight into sellable stock), appends the refund to "
        "the invoice's permanent payment ledger as a negative REFUND row, writes an immutable "
        "return record, and closes the customer's outstanding balance. The original invoice is "
        "never edited — its product snapshot, gold rate, charges, GST, customer price, cost "
        "snapshot and every earlier payment row stay exactly as recorded. Refunding more than was "
        "actually collected is rejected; the unpaid balance is written off, not refunded. A sale "
        "can only be reversed once."
    ),
)
async def return_sale(
    sale_id: str,
    req: SaleReturnCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    record = await SaleReturnService.process_return(db, current_user, sale_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Sale returned successfully",
        data={"saleReturn": record.model_dump(mode="json")},
    )


@router.post(
    "/billing/sales/{sale_id}/return/inspection",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Record Return Inspection Outcome (Admin)",
    description=(
        "The explicit second step of the inventory lifecycle: RESALABLE puts the same original "
        "item back into IN_STOCK, DAMAGED keeps it permanently out of sellable stock. A returned "
        "item never becomes sellable without this decision. Can only be recorded once."
    ),
)
async def inspect_sale_return(
    sale_id: str,
    req: SaleReturnInspectionRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    record = await SaleReturnService.record_inspection(db, current_user, sale_id, req)
    return StandardSuccessResponse(
        success=True,
        message="Return inspection recorded successfully",
        data={"saleReturn": record.model_dump(mode="json")},
    )


@router.get(
    "/billing/sales/{sale_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Sale / Invoice Detail (Admin)",
)
async def get_sale(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sale = await SaleService.get_sale(db, current_user, sale_id)
    return StandardSuccessResponse(
        success=True, message="Sale retrieved successfully", data={"sale": sale.model_dump(mode="json")}
    )


@router.get(
    "/billing/sales/{sale_id}/invoice.pdf",
    status_code=status.HTTP_200_OK,
    summary="Download Invoice PDF (Admin)",
)
async def download_invoice_pdf(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sale = await SaleService.get_sale_orm(db, current_user, sale_id)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    pdf_bytes = billing_export_service.build_invoice_pdf(sale, tenant)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{sale.invoice_number}.pdf"'},
    )


@router.get(
    "/billing/sales/{sale_id}/invoice.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Download Invoice Excel (Admin)",
)
async def download_invoice_excel(
    sale_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sale = await SaleService.get_sale_orm(db, current_user, sale_id)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    xlsx_bytes = billing_export_service.build_invoice_excel(sale, tenant)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{sale.invoice_number}.xlsx"'},
    )



# =============================================================================
# Bill Drafts (unfinished bills)
# =============================================================================
@router.post(
    "/billing/drafts",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save Unfinished Bill (Admin/Staff)",
    description="Saves an unfinished bill (draft). A draft is never a Sale and never touches "
                "inventory, scheme balances or any financial total until finalized. Multiple "
                "drafts may exist at once.",
)
async def create_bill_draft(
    req: BillDraftCreateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    draft = await BillDraftService.create_draft(db, current_user, req)
    return StandardSuccessResponse(
        success=True, message="Unfinished bill saved", data={"draft": draft.model_dump(mode="json")}
    )


@router.get(
    "/billing/drafts",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Unfinished Bills (Admin/Staff)",
    description="Admin sees all tenant drafts; Staff sees only their own. Optional filters: "
                "status, product_code (resume by code), customer_id.",
)
async def list_bill_drafts(
    status_filter: Optional[str] = Query(None, alias="status"),
    product_code: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    drafts = await BillDraftService.list_drafts(db, current_user, status_filter, product_code, customer_id)
    return StandardSuccessResponse(
        success=True,
        message="Unfinished bills retrieved",
        data={"drafts": [d.model_dump(mode="json") for d in drafts]},
    )


@router.get(
    "/billing/drafts/{draft_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Unfinished Bill (Admin/Staff)",
)
async def get_bill_draft(
    draft_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    draft = await BillDraftService.get_draft(db, current_user, draft_id)
    return StandardSuccessResponse(
        success=True, message="Unfinished bill retrieved", data={"draft": draft.model_dump(mode="json")}
    )


@router.put(
    "/billing/drafts/{draft_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit Unfinished Bill (Admin/Staff)",
)
async def update_bill_draft(
    draft_id: str,
    req: BillDraftUpdateRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    draft = await BillDraftService.update_draft(db, current_user, draft_id, req)
    return StandardSuccessResponse(
        success=True, message="Unfinished bill updated", data={"draft": draft.model_dump(mode="json")}
    )


@router.delete(
    "/billing/drafts/{draft_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Discard Unfinished Bill (Admin/Staff)",
)
async def discard_bill_draft(
    draft_id: str,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    await BillDraftService.discard_draft(db, current_user, draft_id)
    return StandardSuccessResponse(success=True, message="Unfinished bill discarded", data={})


@router.post(
    "/billing/drafts/{draft_id}/finalize",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Finalize Unfinished Bill Into A Sale (Admin/Staff)",
    description="Converts an OPEN draft into exactly one finalized Sale: recomputes pricing from "
                "the live item and gold rate, marks inventory SOLD atomically, applies selected "
                "scheme redemption (OTP-gated), and flips the draft to FINALIZED. Any failure "
                "leaves the draft OPEN. A finalized draft cannot be finalized again.",
)
async def finalize_bill_draft(
    draft_id: str,
    req: BillDraftFinalizeRequest,
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    sale = await BillDraftService.finalize_draft(db, current_user, draft_id, req)
    return StandardSuccessResponse(
        success=True, message="Bill finalized", data={"sale": sale.model_dump(mode="json")}
    )
