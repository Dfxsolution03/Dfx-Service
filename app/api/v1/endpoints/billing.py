from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.config import settings
from app.models.auth import User
from app.permissions.dependencies import require_admin_or_staff_module
from app.schemas.auth import StandardSuccessResponse
from app.schemas.billing import (
    InventoryItemCreateRequest,
    InventoryItemUpdateRequest,
    SaleCreateRequest,
)
from app.services.billing_service import InventoryService, SaleService
from app.exceptions.base import ValidationException

router = APIRouter()


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
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    result = await InventoryService.list_items(db, current_user, page, limit, search, stock_status, category)
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
    current_user: User = Depends(require_admin_or_staff_module("billing")),
    db: AsyncSession = Depends(get_async_db),
):
    quote = await SaleService.get_quote(db, current_user, product_code, discount_amount)
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
