import math
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.catalogue import Product
from app.repositories.customer_catalogue_repository import CustomerCatalogueRepository
from app.exceptions.base import ResourceNotFoundException, ForbiddenException, ValidationException
from app.schemas.customer_catalogue import (
    CustomerProductListItem,
    CustomerProductDetailResponse,
    CustomerProductImageResponse,
    ProductListPaginationInfo,
)


def _primary_image_path(product: Product) -> Optional[str]:
    for img in product.images:
        if img.is_primary:
            return img.storage_path
    return product.images[0].storage_path if product.images else None


def _to_list_item(product: Product) -> CustomerProductListItem:
    return CustomerProductListItem(
        id=product.id,
        name=product.name,
        description=product.description,
        category=product.category,
        purity=product.purity,
        price=product.price,
        weight_grams=product.weight_grams,
        primary_image_path=_primary_image_path(product),
    )


def _to_detail(product: Product) -> CustomerProductDetailResponse:
    tags = [t.strip() for t in (product.tags or "").split(",") if t.strip()]
    return CustomerProductDetailResponse(
        id=product.id,
        name=product.name,
        description=product.description,
        category=product.category,
        sku=product.sku,
        purity=product.purity,
        price=product.price,
        weight_grams=product.weight_grams,
        tags=tags,
        images=[CustomerProductImageResponse.model_validate(i) for i in product.images],
    )


class CustomerCatalogueService:
    @staticmethod
    async def list_products(
        db: AsyncSession,
        current_user: User,
        page: int,
        limit: int,
        search: Optional[str],
        category: Optional[str],
        sort: Optional[str],
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        weight_min: Optional[float] = None,
        weight_max: Optional[float] = None,
    ) -> Tuple[List[CustomerProductListItem], ProductListPaginationInfo]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValidationException("price_min cannot be greater than price_max")
        if weight_min is not None and weight_max is not None and weight_min > weight_max:
            raise ValidationException("weight_min cannot be greater than weight_max")

        products, total = await CustomerCatalogueRepository.list_products(
            db, current_user.tenant_id, page, limit, search, category, sort,
            price_min, price_max, weight_min, weight_max,
        )
        total_pages = math.ceil(total / limit) if limit else 0
        pagination = ProductListPaginationInfo(
            page=page, page_size=limit, total_items=total, total_pages=total_pages
        )
        return [_to_list_item(p) for p in products], pagination

    @staticmethod
    async def get_product_detail(
        db: AsyncSession, current_user: User, product_id: str
    ) -> CustomerProductDetailResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product = await CustomerCatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")
        return _to_detail(product)

    @staticmethod
    async def get_categories(db: AsyncSession, current_user: User) -> List[str]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        return await CustomerCatalogueRepository.get_distinct_categories(db, current_user.tenant_id)

    @staticmethod
    async def search_products(
        db: AsyncSession, current_user: User, query: str
    ) -> List[CustomerProductListItem]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        products = await CustomerCatalogueRepository.search_products(db, current_user.tenant_id, query)
        return [_to_list_item(p) for p in products]
