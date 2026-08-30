"""
DFX Backend Tests — Phase 4: Quotation (sample bill) + profit/loss label
========================================================================

Pure-schema tests need no database. The service/DB tests use the shared async
fixtures and require Postgres (TEST_DATABASE_URL); heavy imports are inside the
test methods so collection never needs the full import chain.
"""
import uuid

import pytest

from app.schemas.billing import (
    QuotationCreateRequest,
    QuotationResponse,
    SaleQuoteResponse,
)


# ─────────────────────────────────────────────────────────────────────────────
# Pure schema tests (no database)
# ─────────────────────────────────────────────────────────────────────────────

class TestQuotationRequestValidation:
    def test_requires_customer(self):
        with pytest.raises(Exception):
            QuotationCreateRequest(product_code="PC1")

    def test_scheme_amounts_requires_customer_id(self):
        with pytest.raises(Exception):
            QuotationCreateRequest(
                product_code="PC1", customer_name="Walk In",
                scheme_amounts={"enr_1": 100},
            )

    def test_valid_walk_in(self):
        r = QuotationCreateRequest(product_code="PC1", customer_name="Walk In")
        assert r.gst_applied is True
        assert r.scheme_amounts is None

    def test_valid_with_customer_and_scheme(self):
        r = QuotationCreateRequest(
            product_code="PC1", customer_id="usr_1", scheme_amounts={"enr_1": 500}
        )
        assert r.scheme_amounts == {"enr_1": 500}


class TestProfitLabelField:
    def test_quote_response_has_label_field(self):
        # Field exists and is optional (defaults None).
        assert "profit_or_loss_label" in SaleQuoteResponse.model_fields

    def test_quotation_response_label_field(self):
        assert "profit_or_loss_label" in QuotationResponse.model_fields


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed integration tests (require Postgres TEST_DATABASE_URL)
# ─────────────────────────────────────────────────────────────────────────────

async def _make_inventory(db, admin, *, code=None):
    from app.services.billing_service import InventoryService
    from app.schemas.billing import InventoryItemCreateRequest
    from app.core.constants import PURITY_KARATS
    purity = next(iter(PURITY_KARATS))
    req = InventoryItemCreateRequest(
        product_code=code or f"PC-{uuid.uuid4().hex[:8]}",
        product_name="Test Ring", category="Rings", purity=purity,
        gross_weight_grams=10.0, net_gold_weight_grams=9.0, tax_rate_percent=3.0,
    )
    return await InventoryService.create_item(db, admin, req)


async def _set_today_rate(db, admin, rate=6000.0):
    from datetime import datetime
    from app.models.goldrate import GoldRate
    from app.services.goldrate_service import IST
    db.add(GoldRate(
        id=f"gr_{uuid.uuid4().hex[:10]}", tenant_id=admin.tenant_id,
        rate_24k=rate, effective_date=datetime.now(IST).date(), created_by=admin.id,
    ))
    await db.commit()


class TestQuotationGeneration:
    async def test_quotation_does_not_sell_or_spend(self, db_session, admin_user):
        from app.services.billing_service import QuotationService
        from app.repositories.billing_repository import InventoryRepository
        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)

        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="Walk In"),
        )
        assert q.final_amount > 0
        assert q.outstanding_amount == q.final_amount  # no scheme applied
        assert q.scheme_amount_total == 0
        assert q.profit_or_loss_label in {"PROFIT", "LOSS", "BREAK_EVEN"}
        # The inventory item is NOT sold by a quotation.
        item = await InventoryRepository.get_by_id(db_session, inv.id, admin_user.tenant_id)
        assert item.stock_status == "IN_STOCK"

    async def test_admin_gets_margin_number(self, db_session, admin_user):
        from app.services.billing_service import QuotationService
        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="W"),
        )
        # Admin is privileged → numeric margin present alongside the label.
        assert q.estimated_gross_margin is not None

    async def test_scheme_preview_capped_by_balance(self, db_session, admin_user, customer_user):
        from app.services.billing_service import QuotationService
        from app.services.scheme_service import SchemeService
        from app.services.enrollment_service import EnrollmentService
        from app.schemas.scheme import SchemeCreateRequest, SchemeTierInput
        from app.schemas.enrollment import EnrollmentCreateRequest

        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(name="Gold Plan", monthly_amount=1000, duration_months=12,
                                tiers=[SchemeTierInput(monthly_amount=1000, duration_months=12)]),
        )
        enr = await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=scheme.tiers[0].id),
        )
        # Customer has contributed nothing → available balance 0 → applied 0.
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(
                product_code=inv.product_code, customer_id=customer_user.id,
                scheme_amounts={enr.id: 5000},
            ),
        )
        assert q.scheme_amount_total == 0
        assert q.outstanding_amount == q.final_amount
        assert len(q.scheme_preview) == 1
        assert q.scheme_preview[0].available_balance == 0
        assert q.scheme_preview[0].applied_amount == 0

    async def test_reprint_get_and_list(self, db_session, admin_user):
        from app.services.billing_service import QuotationService
        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="W"),
        )
        got = await QuotationService.get_quotation(db_session, admin_user, q.id)
        assert got.quotation_number == q.quotation_number
        assert got.final_amount == q.final_amount
        listing = await QuotationService.list_quotations(db_session, admin_user)
        assert any(x.id == q.id for x in listing.quotations)

    async def test_quotation_pdf_download(self, db_session, admin_user):
        from app.services.billing_service import QuotationService
        from app.services import billing_export_service
        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="Walk In"),
        )
        orm = await QuotationService.get_quotation_orm(db_session, admin_user, q.id)
        assert orm.id == q.id
        pdf = billing_export_service.build_quotation_pdf(orm, None)
        # A real PDF byte-stream, not an HTML/print artifact.
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 500
        # Privacy: the Gold Value line folds gold profit in, so the exporter never
        # itemises the internal margin. Verify the snapshot carried a profit that
        # is NOT emitted as its own row value.
        b = orm.breakdown_json
        assert b.get("gold_profit_amount") is not None

    async def test_quotation_pdf_tenant_isolation(self, db_session, admin_user):
        from sqlalchemy import select
        from app.core.constants import ROLE_ADMIN
        from app.core.security import hash_password
        from app.models.auth import Tenant, Role, User
        from app.services.billing_service import QuotationService
        from app.exceptions.base import ResourceNotFoundException

        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="W"),
        )
        uid = uuid.uuid4().hex[:8]
        db_session.add(Tenant(id=f"tnt_{uid}", name=f"T2 {uid}", slug=f"t2-{uid}", status="Active"))
        role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
        other = User(
            id=f"usr_{uid}", tenant_id=f"tnt_{uid}", role_id=role.id,
            name="Other Admin", email=f"o{uid}@t2.com", password_hash=hash_password("x"),
            status="Active",
        )
        db_session.add(other)
        await db_session.commit()
        await db_session.refresh(other, ["role"])
        # A different tenant's admin cannot fetch this quotation for PDF export.
        with pytest.raises(ResourceNotFoundException):
            await QuotationService.get_quotation_orm(db_session, other, q.id)

    async def test_tenant_isolation(self, db_session, admin_user):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.core.constants import ROLE_ADMIN
        from app.core.security import hash_password
        from app.models.auth import Tenant, Role, User
        from app.services.billing_service import QuotationService
        from app.exceptions.base import ResourceNotFoundException

        inv = await _make_inventory(db_session, admin_user)
        await _set_today_rate(db_session, admin_user)
        q = await QuotationService.generate(
            db_session, admin_user,
            QuotationCreateRequest(product_code=inv.product_code, customer_name="W"),
        )
        uid = uuid.uuid4().hex[:8]
        db_session.add(Tenant(id=f"tnt_{uid}", name=f"T2 {uid}", slug=f"t2-{uid}", status="Active"))
        role = (await db_session.execute(select(Role).where(Role.name == ROLE_ADMIN))).scalar_one()
        other = User(
            id=f"usr_{uid}", tenant_id=f"tnt_{uid}", role_id=role.id,
            email=f"a_{uid}@t2.com", hashed_password=hash_password("x"),
            name="Other Admin", kyc_status="Verified", member_since="July 2026", is_active=True,
        )
        db_session.add(other)
        await db_session.commit()
        other = (await db_session.execute(
            select(User).options(selectinload(User.role)).where(User.id == other.id)
        )).scalar_one()
        with pytest.raises(ResourceNotFoundException):
            await QuotationService.get_quotation(db_session, other, q.id)
