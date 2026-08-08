from typing import List, Optional, Tuple
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalogue import Product


class CustomerCatalogueRepository:
    """
    Read-only, customer-facing queries over the EXISTING Product/ProductImage
    tables (Phase 6A / Module 31 — Part 2). Deliberately separate from
    CatalogueRepository (the admin/staff repository) per the spec's explicit
    "build new, separate customer-facing read-only files instead" instruction
    — this file is never imported by the admin catalogue module and never
    writes to either table.
    """

    @staticmethod
    def _base_query():
        return select(Product).options(selectinload(Product.images)).where(Product.is_active == True)  # noqa: E712

    @staticmethod
    async def list_products(
        db: AsyncSession,
        tenant_id: str,
        page: int,
        limit: int,
        search: Optional[str],
        category: Optional[str],
        sort: Optional[str],
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        weight_min: Optional[float] = None,
        weight_max: Optional[float] = None,
    ) -> Tuple[List[Product], int]:
        """
        Phase 6C / Module 33 — price_min/price_max/weight_min/weight_max are
        additive, all default None (i.e. no filter, byte-for-byte the same
        query as before this module when omitted — backward compatible).
        """
        conditions = [Product.tenant_id == tenant_id, Product.is_active == True]  # noqa: E712
        if search:
            like = f"%{search}%"
            conditions.append(or_(Product.name.ilike(like), Product.description.ilike(like)))
        if category:
            conditions.append(Product.category == category)
        if price_min is not None:
            conditions.append(Product.price >= price_min)
        if price_max is not None:
            conditions.append(Product.price <= price_max)
        if weight_min is not None:
            conditions.append(Product.weight_grams >= weight_min)
        if weight_max is not None:
            conditions.append(Product.weight_grams <= weight_max)

        count_stmt = select(func.count(Product.id))
        list_stmt = select(Product).options(selectinload(Product.images))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        if sort == "price_asc":
            list_stmt = list_stmt.order_by(Product.price.asc().nulls_last())
        elif sort == "price_desc":
            list_stmt = list_stmt.order_by(Product.price.desc().nulls_last())
        elif sort == "name_asc":
            list_stmt = list_stmt.order_by(Product.name.asc())
        else:
            list_stmt = list_stmt.order_by(Product.created_at.desc())

        total = int((await db.execute(count_stmt)).scalar_one())
        list_stmt = list_stmt.offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(list_stmt)).unique().scalars().all()
        return list(rows), total

    @staticmethod
    async def get_product_by_id(db: AsyncSession, product_id: str, tenant_id: str) -> Optional[Product]:
        stmt = (
            CustomerCatalogueRepository._base_query()
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_distinct_categories(db: AsyncSession, tenant_id: str) -> List[str]:
        stmt = (
            select(Product.category)
            .where(
                Product.tenant_id == tenant_id,
                Product.is_active == True,  # noqa: E712
                Product.category.is_not(None),
            )
            .distinct()
            .order_by(Product.category)
        )
        result = await db.execute(stmt)
        return [c for c in result.scalars().all() if c]

    @staticmethod
    async def search_products(
        db: AsyncSession, tenant_id: str, query: str, limit: int = 50
    ) -> List[Product]:
        like = f"%{query}%"
        stmt = (
            CustomerCatalogueRepository._base_query()
            .where(
                Product.tenant_id == tenant_id,
                or_(Product.name.ilike(like), Product.description.ilike(like), Product.category.ilike(like)),
            )
            .order_by(Product.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())

    @staticmethod
    async def get_products_by_ids(db: AsyncSession, product_ids: List[str], tenant_id: str) -> List[Product]:
        """Batch, active-only lookup — backs the Wishlist list endpoint's
        product-info join without querying the admin catalogue repository."""
        if not product_ids:
            return []
        stmt = (
            CustomerCatalogueRepository._base_query()
            .where(Product.id.in_(product_ids), Product.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())
