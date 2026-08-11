import uuid
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.wishlist import WishlistItem
from app.repositories.wishlist_repository import WishlistRepository
from app.repositories.customer_catalogue_repository import CustomerCatalogueRepository
from app.repositories.audit_repository import AuditRepository
from app.exceptions.base import ResourceNotFoundException, ConflictException, ForbiddenException
from app.schemas.wishlist import WishlistItemResponse
from app.services.storage_service import get_storage_provider


def _primary_image_url(product) -> str | None:
    """Resolve a product's primary image to a public URL, mirroring
    CustomerCatalogueService._primary_image_path. Never return a raw
    storage_path — that is a provider-internal object key, not a URL."""
    provider = get_storage_provider()
    for img in product.images:
        if img.is_primary:
            return provider.get_public_url(img.storage_path)
    return provider.get_public_url(product.images[0].storage_path) if product.images else None


class WishlistService:
    @staticmethod
    async def add_to_wishlist(
        db: AsyncSession, current_user: User, product_id: str
    ) -> WishlistItemResponse:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        product = await CustomerCatalogueRepository.get_product_by_id(db, product_id, current_user.tenant_id)
        if not product:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found")

        existing = await WishlistRepository.get_item_by_user_and_product(
            db, current_user.id, product_id, current_user.tenant_id
        )
        if existing:
            raise ConflictException("Product is already in your wishlist")

        item_id = f"wsh_{uuid.uuid4().hex[:12]}"
        item = WishlistItem(
            id=item_id,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            product_id=product_id,
        )
        await WishlistRepository.create_item(db, item)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="WISHLIST_ADD",
            target_entity="wishlist_items",
            target_id=item_id,
            before_state=None,
            after_state={"product_id": product_id},
        )

        await db.commit()
        await db.refresh(item)

        return WishlistItemResponse(
            id=item.id,
            product_id=product.id,
            product_name=product.name,
            product_price=product.price,
            product_image_path=_primary_image_url(product),
            created_at=item.created_at,
        )

    @staticmethod
    async def remove_from_wishlist(db: AsyncSession, current_user: User, product_id: str) -> None:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        item = await WishlistRepository.get_item_by_user_and_product(
            db, current_user.id, product_id, current_user.tenant_id
        )
        if not item:
            raise ResourceNotFoundException(f"Product ID '{product_id}' not found in wishlist")

        await WishlistRepository.delete_item(db, item)

        await AuditRepository.create_log(
            db,
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_name=current_user.name,
            actor_role=current_user.role.name,
            action="WISHLIST_REMOVE",
            target_entity="wishlist_items",
            target_id=item.id,
            before_state={"product_id": product_id},
            after_state=None,
        )

        await db.commit()

    @staticmethod
    async def get_wishlist(db: AsyncSession, current_user: User) -> List[WishlistItemResponse]:
        if not current_user.tenant_id:
            raise ForbiddenException("Tenant context required")

        items = await WishlistRepository.get_items_by_user(db, current_user.id, current_user.tenant_id)
        if not items:
            return []

        product_ids = [i.product_id for i in items]
        products = await CustomerCatalogueRepository.get_products_by_ids(
            db, product_ids, current_user.tenant_id
        )
        products_by_id = {p.id: p for p in products}

        results = []
        for item in items:
            product = products_by_id.get(item.product_id)
            if not product:
                # Product was deactivated/deleted after being wishlisted —
                # skip rather than error, same "just absent" convention
                # CatalogueRepository.get_products_by_ids already documents.
                continue
            results.append(
                WishlistItemResponse(
                    id=item.id,
                    product_id=product.id,
                    product_name=product.name,
                    product_price=product.price,
                    product_image_path=_primary_image_url(product),
                    created_at=item.created_at,
                )
            )
        return results
