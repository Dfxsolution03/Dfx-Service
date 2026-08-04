"""
JROS Service Tests — SchemeService
=====================================
"""

import pytest
from app.models.auth import User
from app.schemas.scheme import SchemeCreateRequest, SchemeUpdateRequest
from app.services.scheme_service import SchemeService
from app.exceptions.base import ResourceNotFoundException


def sample_req() -> SchemeCreateRequest:
    return SchemeCreateRequest(
        name="Monthly Gold Plan",
        description="Save monthly for 11 months",
        monthly_amount=1000,
        duration_months=11,
        bonus_description="8% bonus on maturity",
    )


class TestCreateScheme:

    async def test_create_persists_scheme(self, db_session, admin_user: User):
        result = await SchemeService.create_scheme(db_session, admin_user, sample_req())
        assert result.name == "Monthly Gold Plan"
        assert result.is_active is True
        assert result.created_by == admin_user.id


class TestUpdateScheme:

    async def test_update_not_found_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await SchemeService.update_scheme(
                db_session, admin_user, "sch_does_not_exist", SchemeUpdateRequest(monthly_amount=2000)
            )

    async def test_update_modifies_fields(self, db_session, admin_user: User):
        created = await SchemeService.create_scheme(db_session, admin_user, sample_req())
        updated = await SchemeService.update_scheme(
            db_session, admin_user, created.id, SchemeUpdateRequest(monthly_amount=2000)
        )
        assert updated.id == created.id
        assert updated.monthly_amount == 2000


class TestDeactivateScheme:

    async def test_deactivate_sets_is_active_false(self, db_session, admin_user: User):
        created = await SchemeService.create_scheme(db_session, admin_user, sample_req())
        await SchemeService.deactivate_scheme(db_session, admin_user, created.id)

        fetched = await SchemeService.get_scheme_by_id(db_session, admin_user, created.id)
        assert fetched.is_active is False

    async def test_deactivate_not_found_raises(self, db_session, admin_user: User):
        with pytest.raises(ResourceNotFoundException):
            await SchemeService.deactivate_scheme(db_session, admin_user, "sch_does_not_exist")


class TestGetCustomerSchemes:

    async def test_excludes_inactive(self, db_session, admin_user: User, customer_user: User):
        active = await SchemeService.create_scheme(db_session, admin_user, sample_req())
        inactive_req = SchemeCreateRequest(name="Old Plan", monthly_amount=500, duration_months=6)
        inactive = await SchemeService.create_scheme(db_session, admin_user, inactive_req)
        await SchemeService.deactivate_scheme(db_session, admin_user, inactive.id)

        result = await SchemeService.get_customer_schemes(db_session, customer_user)
        result_ids = [s.id for s in result]
        assert active.id in result_ids
        assert inactive.id not in result_ids
