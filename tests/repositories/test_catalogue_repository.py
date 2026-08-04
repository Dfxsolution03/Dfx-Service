"""
DFX Solution Repository Tests — CatalogueRepository (Module 20)
================================================================
"""

import uuid
from app.models.catalogue import Product, ProductImage
from app.repositories.catalogue_repository import CatalogueRepository


def _make_product(tenant_id: str, created_by: str, name: str = "Gold Necklace") -> Product:
    return Product(
        id=f"prd_test_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        name=name,
        description=None,
        category="Necklaces",
        sku=None,
        is_active=True,
        created_by=created_by,
    )


def _make_image(product_id: str, tenant_id: str, created_by: str, **overrides) -> ProductImage:
    defaults = dict(
        id=f"img_test_{uuid.uuid4().hex[:12]}",
        product_id=product_id,
        tenant_id=tenant_id,
        variant_type="ORIGINAL",
        source_image_id=None,
        storage_path=f"{tenant_id}/test.jpg",
        file_name="test.jpg",
        content_type="image/jpeg",
        file_size_bytes=1024,
        display_order=0,
        is_primary=False,
        created_by=created_by,
    )
    defaults.update(overrides)
    return ProductImage(**defaults)


class TestCatalogueRepositoryProducts:
    async def test_get_products_by_tenant_returns_empty_initially(self, db_session, admin_user):
        result = await CatalogueRepository.get_products_by_tenant(db_session, admin_user.tenant_id)
        assert result == []

    async def test_create_and_get_by_id(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        fetched = await CatalogueRepository.get_product_by_id(
            db_session, product.id, admin_user.tenant_id
        )
        assert fetched is not None
        assert fetched.name == "Gold Necklace"
        assert fetched.images == []

    async def test_get_product_by_id_scoped_to_tenant(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        fetched = await CatalogueRepository.get_product_by_id(
            db_session, product.id, "tnt_some_other_tenant"
        )
        assert fetched is None


class TestCatalogueRepositoryImages:
    async def test_get_images_by_product_returns_empty_initially(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        images = await CatalogueRepository.get_images_by_product(
            db_session, product.id, admin_user.tenant_id
        )
        assert images == []

    async def test_create_and_get_image_by_id(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        image = _make_image(product.id, admin_user.tenant_id, admin_user.id, is_primary=True)
        await CatalogueRepository.create_image(db_session, image)
        await db_session.commit()

        fetched = await CatalogueRepository.get_image_by_id(
            db_session, image.id, admin_user.tenant_id
        )
        assert fetched is not None
        assert fetched.is_primary is True
        assert fetched.variant_type == "ORIGINAL"

    async def test_clear_primary_flag_unsets_existing_primary(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        image = _make_image(product.id, admin_user.tenant_id, admin_user.id, is_primary=True)
        await CatalogueRepository.create_image(db_session, image)
        await db_session.commit()

        await CatalogueRepository.clear_primary_flag(db_session, product.id, admin_user.tenant_id)
        await db_session.commit()
        await db_session.refresh(image)
        assert image.is_primary is False

    async def test_get_all_images_by_tenant_spans_multiple_products(self, db_session, admin_user):
        product_a = _make_product(admin_user.tenant_id, admin_user.id, name="A")
        product_b = _make_product(admin_user.tenant_id, admin_user.id, name="B")
        await CatalogueRepository.create_product(db_session, product_a)
        await CatalogueRepository.create_product(db_session, product_b)
        await db_session.commit()

        img_a = _make_image(product_a.id, admin_user.tenant_id, admin_user.id)
        img_b = _make_image(product_b.id, admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_image(db_session, img_a)
        await CatalogueRepository.create_image(db_session, img_b)
        await db_session.commit()

        all_images = await CatalogueRepository.get_all_images_by_tenant(db_session, admin_user.tenant_id)
        ids = {i.id for i in all_images}
        assert img_a.id in ids
        assert img_b.id in ids

    async def test_delete_image_removes_row(self, db_session, admin_user):
        product = _make_product(admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_product(db_session, product)
        await db_session.commit()

        image = _make_image(product.id, admin_user.tenant_id, admin_user.id)
        await CatalogueRepository.create_image(db_session, image)
        await db_session.commit()

        await CatalogueRepository.delete_image(db_session, image)
        await db_session.commit()

        fetched = await CatalogueRepository.get_image_by_id(
            db_session, image.id, admin_user.tenant_id
        )
        assert fetched is None
