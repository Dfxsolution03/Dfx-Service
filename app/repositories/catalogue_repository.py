from typing import List, Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalogue import Product, ProductImage, CatalogueDesign


class CatalogueRepository:
    # -- Products ---------------------------------------------------------
    @staticmethod
    async def get_products_by_tenant(db: AsyncSession, tenant_id: str) -> List[Product]:
        stmt = (
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.tenant_id == tenant_id)
            .order_by(Product.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())

    @staticmethod
    async def get_product_by_id(
        db: AsyncSession, product_id: str, tenant_id: str
    ) -> Optional[Product]:
        stmt = (
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id == product_id, Product.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_products_by_ids(
        db: AsyncSession, product_ids: List[str], tenant_id: str
    ) -> List[Product]:
        """Batch lookup, same tenant-scoped filtering + eager-loaded images
        as get_product_by_id, for many ids in one round trip. Missing ids
        are simply absent from the result — callers that need all-or-
        nothing validation compare the ids returned against ids requested."""
        if not product_ids:
            return []
        stmt = (
            select(Product)
            .options(selectinload(Product.images))
            .where(Product.id.in_(product_ids), Product.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())

    @staticmethod
    async def create_product(db: AsyncSession, product: Product) -> Product:
        db.add(product)
        return product

    # -- Images -------------------------------------------------------------
    @staticmethod
    async def get_image_by_id(
        db: AsyncSession, image_id: str, tenant_id: str
    ) -> Optional[ProductImage]:
        stmt = select(ProductImage).where(
            ProductImage.id == image_id, ProductImage.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_images_by_ids(
        db: AsyncSession, image_ids: List[str], tenant_id: str
    ) -> List[ProductImage]:
        """Batch lookup — same tenant-scoped filtering as get_image_by_id,
        just for many ids in one round trip instead of one call per id.
        Missing ids are simply absent from the result (same as
        get_image_by_id returning None for a missing single id); callers
        that need to detect a missing id do so by comparing ids returned
        against ids requested."""
        if not image_ids:
            return []
        stmt = select(ProductImage).where(
            ProductImage.id.in_(image_ids), ProductImage.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_images_by_product(
        db: AsyncSession, product_id: str, tenant_id: str
    ) -> List[ProductImage]:
        stmt = (
            select(ProductImage)
            .where(ProductImage.product_id == product_id, ProductImage.tenant_id == tenant_id)
            .order_by(ProductImage.variant_type, ProductImage.display_order)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_all_images_by_tenant(db: AsyncSession, tenant_id: str) -> List[ProductImage]:
        """Backs the Media Library — every image variant across every
        product for the tenant, newest first."""
        stmt = (
            select(ProductImage)
            .where(ProductImage.tenant_id == tenant_id)
            .order_by(ProductImage.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_image(db: AsyncSession, image: ProductImage) -> ProductImage:
        db.add(image)
        return image

    @staticmethod
    async def clear_primary_flag(db: AsyncSession, product_id: str, tenant_id: str) -> None:
        await db.execute(
            update(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.tenant_id == tenant_id,
                ProductImage.is_primary == True,  # noqa: E712
            )
            .values(is_primary=False)
        )

    @staticmethod
    async def delete_image(db: AsyncSession, image: ProductImage) -> None:
        await db.delete(image)

    # -- Designs (Phase B — Design Studio & Rendering Engine) ----------------
    @staticmethod
    async def create_design(db: AsyncSession, design: CatalogueDesign) -> CatalogueDesign:
        db.add(design)
        return design

    @staticmethod
    async def get_next_version(db: AsyncSession, product_id: str, tenant_id: str) -> int:
        """1, 2, 3... per product — a plain human-readable ordinal over this
        product's own CatalogueDesign rows, not a global counter."""
        stmt = select(func.count(CatalogueDesign.id)).where(
            CatalogueDesign.product_id == product_id, CatalogueDesign.tenant_id == tenant_id
        )
        count = (await db.execute(stmt)).scalar_one()
        return int(count) + 1

    @staticmethod
    async def get_designs_by_product(
        db: AsyncSession, product_id: str, tenant_id: str
    ) -> List[CatalogueDesign]:
        """Every version, newest first — this listing *is* the version
        history (see CatalogueDesign's own docstring)."""
        stmt = (
            select(CatalogueDesign)
            .where(CatalogueDesign.product_id == product_id, CatalogueDesign.tenant_id == tenant_id)
            .order_by(CatalogueDesign.version.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_design_by_id(
        db: AsyncSession, design_id: str, tenant_id: str
    ) -> Optional[CatalogueDesign]:
        stmt = select(CatalogueDesign).where(
            CatalogueDesign.id == design_id, CatalogueDesign.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
