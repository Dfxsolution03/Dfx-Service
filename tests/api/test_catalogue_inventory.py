"""
DFX Backend Tests — Phase 3: Catalogue & Inventory publishing
=============================================================

Pure-schema tests need no database. The service/DB tests use the shared async
fixtures (db_session, admin_user, customer_user) and require the configured
Postgres test database (TEST_DATABASE_URL), exactly like the other service
tests. Heavy imports are done inside test methods so collection never depends
on the full app import chain being present.
"""
import uuid

import pytest

from app.schemas.catalogue import (
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductResponse,
    InventoryPublishRequest,
    InventoryBulkPublishItem,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pure schema tests (no database)
# ─────────────────────────────────────────────────────────────────────────────

class TestPublishRequestValidation:
    def test_selling_cost_ok_without_price(self):
        r = InventoryPublishRequest(pricing_source="SELLING_COST")
        assert r.catalogue_price is None

    def test_selling_cost_rejects_client_price(self):
        # The server calculates SELLING_COST; a client price must be refused.
        with pytest.raises(Exception):
            InventoryPublishRequest(pricing_source="SELLING_COST", catalogue_price=999)

    def test_catalogue_cost_requires_price(self):
        with pytest.raises(Exception):
            InventoryPublishRequest(pricing_source="CATALOGUE_COST")

    @pytest.mark.parametrize("price", [0, -5])
    def test_catalogue_cost_rejects_nonpositive(self, price):
        with pytest.raises(Exception):
            InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=price)

    def test_catalogue_cost_ok(self):
        r = InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=25000)
        assert r.catalogue_price == 25000

    def test_bulk_item_requires_inventory_id(self):
        with pytest.raises(Exception):
            InventoryBulkPublishItem(pricing_source="CATALOGUE_COST", catalogue_price=1)


class TestProductSchemaSubCategory:
    def test_create_accepts_sub_category(self):
        req = ProductCreateRequest(name="Ring", sub_category="Wedding")
        assert req.sub_category == "Wedding"

    def test_update_accepts_sub_category(self):
        req = ProductUpdateRequest(sub_category="Daily")
        assert req.sub_category == "Daily"

    def test_response_new_fields_default_none(self):
        from datetime import datetime
        r = ProductResponse(
            id="p", tenant_id="t", name="Ring", is_active=True, created_by="u",
            created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
        )
        assert r.sub_category is None
        assert r.inventory_item_id is None
        assert r.pricing_source is None
        assert r.computed_selling_cost is None
        assert r.price_effective_date is None


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed integration tests (require Postgres TEST_DATABASE_URL)
# ─────────────────────────────────────────────────────────────────────────────

async def _make_inventory(db, admin, *, with_image=True, code=None):
    from app.services.billing_service import InventoryService
    from app.schemas.billing import InventoryItemCreateRequest
    from app.core.constants import PURITY_KARATS
    from app.repositories.billing_repository import InventoryRepository

    purity = next(iter(PURITY_KARATS))
    req = InventoryItemCreateRequest(
        product_code=code or f"PC-{uuid.uuid4().hex[:8]}",
        product_name="Test Ring",
        category="Rings",
        subcategory="Wedding",
        purity=purity,
        gross_weight_grams=10.0,
        net_gold_weight_grams=9.0,
        tax_rate_percent=3.0,
    )
    resp = await InventoryService.create_item(db, admin, req)
    if with_image:
        item = await InventoryRepository.get_by_id(db, resp.id, admin.tenant_id)
        item.image_storage_path = "tenant/test/inv.jpg"
        await db.commit()
    return resp


async def _set_today_rate(db, admin, rate=6000.0):
    from datetime import datetime
    from app.models.goldrate import GoldRate
    from app.services.goldrate_service import IST
    gr = GoldRate(
        id=f"gr_{uuid.uuid4().hex[:10]}",
        tenant_id=admin.tenant_id,
        rate_24k=rate,
        effective_date=datetime.now(IST).date(),
        created_by=admin.id,
    )
    db.add(gr)
    await db.commit()


class TestSubCategoryAndFilters:
    async def test_sub_category_create_update_response(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        p = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Gold Ring", category="Rings", sub_category="Wedding")
        )
        assert p.sub_category == "Wedding"
        p2 = await CatalogueService.update_product(
            db_session, admin_user, p.id, ProductUpdateRequest(sub_category="Daily")
        )
        assert p2.sub_category == "Daily"

    async def test_admin_filters(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="A", category="Rings", purity="22K", sub_category="Wedding")
        )
        await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="B", category="Chains", purity="18K", sub_category="Daily")
        )
        by_cat = await CatalogueService.get_products(db_session, admin_user, category="Rings")
        assert {p.name for p in by_cat} == {"A"}
        by_pur = await CatalogueService.get_products(db_session, admin_user, purity="18K")
        assert {p.name for p in by_pur} == {"B"}
        by_sub = await CatalogueService.get_products(db_session, admin_user, sub_category="Wedding")
        assert {p.name for p in by_sub} == {"A"}


class TestInventoryPublish:
    async def test_publish_selling_cost_uses_engine(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        from app.services.billing_service import BillingCalculationEngine
        from app.repositories.billing_repository import InventoryRepository
        from app.services.goldrate_service import IST
        from datetime import datetime

        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user, rate=6000.0)

        product = await CatalogueService.publish_inventory_item(
            db_session, admin_user, inv.id, InventoryPublishRequest(pricing_source="SELLING_COST")
        )
        # Independently compute the expected price with the SAME authoritative engine.
        item = await InventoryRepository.get_by_id(db_session, inv.id, admin_user.tenant_id)
        expected = round(
            BillingCalculationEngine.calculate(
                item, 6000.0, "MANUAL", datetime.now(IST).date(), 0, True
            ).final_amount, 2
        )
        assert product.pricing_source == "SELLING_COST"
        assert product.computed_selling_cost == expected
        assert product.price == expected
        assert product.inventory_item_id == inv.id

    async def test_publish_catalogue_cost_manual(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        inv = await _make_inventory(db_session, admin_user)
        product = await CatalogueService.publish_inventory_item(
            db_session, admin_user, inv.id,
            InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=99999),
        )
        assert product.pricing_source == "CATALOGUE_COST"
        assert product.price == 99999
        assert product.computed_selling_cost is None

    async def test_duplicate_publish_is_idempotent(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        from app.repositories.catalogue_repository import CatalogueRepository
        inv = await _make_inventory(db_session, admin_user)
        p1 = await CatalogueService.publish_inventory_item(
            db_session, admin_user, inv.id,
            InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=100),
        )
        p2 = await CatalogueService.publish_inventory_item(
            db_session, admin_user, inv.id,
            InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=200),
        )
        assert p1.id == p2.id  # same product updated, not duplicated
        assert p2.price == 200
        all_products = await CatalogueRepository.get_products_by_tenant(db_session, admin_user.tenant_id)
        linked = [p for p in all_products if p.inventory_item_id == inv.id]
        assert len(linked) == 1

    async def test_mandatory_image(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        from app.exceptions.base import ValidationException
        inv = await _make_inventory(db_session, admin_user, with_image=False)
        with pytest.raises(ValidationException):
            await CatalogueService.publish_inventory_item(
                db_session, admin_user, inv.id,
                InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=100),
            )

    async def test_tenant_isolation(self, db_session, admin_user):
        """An admin from another tenant cannot publish this tenant's item —
        the tenant-scoped lookup makes it invisible (ResourceNotFound)."""
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.core.constants import ROLE_ADMIN
        from app.core.security import hash_password
        from app.models.auth import Tenant, Role, User
        from app.services.catalogue_service import CatalogueService
        from app.exceptions.base import ResourceNotFoundException

        inv = await _make_inventory(db_session, admin_user)

        # Build a second tenant + its admin inline (no dedicated fixture needed).
        uid = uuid.uuid4().hex[:8]
        t2 = Tenant(id=f"tnt_{uid}", name=f"T2 {uid}", slug=f"t2-{uid}", status="Active")
        db_session.add(t2)
        role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
        other = User(
            id=f"usr_{uid}", tenant_id=t2.id, role_id=role.id,
            email=f"a_{uid}@t2.com", hashed_password=hash_password("x"),
            name="Other Admin", kyc_status="Verified", member_since="July 2026", is_active=True,
        )
        db_session.add(other)
        await db_session.commit()
        other = (await db_session.execute(
            select(User).options(selectinload(User.role)).where(User.id == other.id)
        )).scalar_one()

        with pytest.raises(ResourceNotFoundException):
            await CatalogueService.publish_inventory_item(
                db_session, other, inv.id,
                InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=100),
            )

    async def test_sold_inventory_leaves_catalogue_unchanged(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        from app.repositories.billing_repository import InventoryRepository
        inv = await _make_inventory(db_session, admin_user)
        product = await CatalogueService.publish_inventory_item(
            db_session, admin_user, inv.id,
            InventoryPublishRequest(pricing_source="CATALOGUE_COST", catalogue_price=100),
        )
        # Simulate a sale marking the inventory item SOLD.
        item = await InventoryRepository.get_by_id(db_session, inv.id, admin_user.tenant_id)
        item.stock_status = "SOLD"
        await db_session.commit()
        # Catalogue product is independent — still present, active, same price.
        got = await CatalogueService.get_product_by_id(db_session, admin_user, product.id)
        assert got.is_active is True
        assert got.price == 100


class TestExistingCatalogueCompatibility:
    async def test_standalone_manual_product_still_works(self, db_session, admin_user):
        from app.services.catalogue_service import CatalogueService
        p = await CatalogueService.create_product(
            db_session, admin_user, ProductCreateRequest(name="Manual", price=500)
        )
        assert p.inventory_item_id is None
        assert p.price == 500
        assert p.pricing_source is None
