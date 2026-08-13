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
)
from app.services.billing_service import VendorService, BillingDefaultsService, InventoryService, SaleService
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
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    quote = await SaleService.get_quote(db, current_user, product_code, discount_amount, gst_applied, customer_price)
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
    description="Today's and this-month's sales/profit/loss aggregated from finalized sale records, plus the 5 most recent sales.",
)
async def get_billing_dashboard_summary(
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    summary = await SaleService.get_dashboard_summary(db, current_user)
    return StandardSuccessResponse(
        success=True, message="Billing summary retrieved successfully", data=summary.model_dump(mode="json")
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
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await SaleService.list_sales(db, current_user, page, limit, search, date_from, date_to)
    return StandardSuccessResponse(
        success=True,
        message="Sales retrieved successfully",
        data={"sales": [s.model_dump(mode="json") for s in result.sales], "total": result.total},
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
