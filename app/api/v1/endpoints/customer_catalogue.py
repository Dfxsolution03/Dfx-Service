from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.models.auth import User
from app.permissions.dependencies import get_current_user
from app.schemas.auth import StandardSuccessResponse
from app.schemas.customer_catalogue import SortOption
from app.services.customer_catalogue_service import CustomerCatalogueService

router = APIRouter()


@router.get(
    "/customer/catalogue/products",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Products (Customer)",
    description="Paginated, searchable, filterable list of active products for the customer's tenant.",
)
async def list_products(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sort: Optional[SortOption] = Query(None),
    price_min: Optional[float] = Query(None, ge=0, description="Phase 6C — minimum price filter"),
    price_max: Optional[float] = Query(None, ge=0, description="Phase 6C — maximum price filter"),
    weight_min: Optional[float] = Query(None, ge=0, description="Phase 6C — minimum weight (grams) filter"),
    weight_max: Optional[float] = Query(None, ge=0, description="Phase 6C — maximum weight (grams) filter"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    products, pagination = await CustomerCatalogueService.list_products(
        db, current_user, page, limit, search, category, sort,
        price_min, price_max, weight_min, weight_max,
    )
    return StandardSuccessResponse(
        success=True,
        message="Products retrieved successfully",
        data={"products": [p.model_dump(mode="json") for p in products]},
        meta={"pagination": pagination.model_dump(mode="json")},
    )


@router.get(
    "/customer/catalogue/categories",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="List Product Categories (Customer)",
    description="Returns the distinct set of categories among active products for the customer's tenant.",
)
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    categories = await CustomerCatalogueService.get_categories(db, current_user)
    return StandardSuccessResponse(
        success=True,
        message="Categories retrieved successfully",
        data={"categories": categories},
    )


@router.get(
    "/customer/catalogue/search",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Search Products (Customer)",
    description="Free-text search over active products' name/description/category for the customer's tenant.",
)
async def search_products(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    products = await CustomerCatalogueService.search_products(db, current_user, q)
    return StandardSuccessResponse(
        success=True,
        message="Search results retrieved successfully",
        data={"products": [p.model_dump(mode="json") for p in products]},
    )


@router.get(
    "/customer/catalogue/products/{product_id}",
    response_model=StandardSuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Product Detail (Customer)",
    description="Returns full detail for a single active product, including images, category, and pricing.",
)
async def get_product_detail(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    product = await CustomerCatalogueService.get_product_detail(db, current_user, product_id)
    return StandardSuccessResponse(
        success=True,
        message="Product retrieved successfully",
        data={"product": product.model_dump(mode="json")},
    )
