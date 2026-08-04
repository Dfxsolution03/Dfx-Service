"""
JROS Repository Tests — SchemeRepository
============================================
"""

import uuid
from app.models.scheme import Scheme
from app.repositories.scheme_repository import SchemeRepository


class TestSchemeRepository:

    async def test_get_schemes_by_tenant_returns_empty_initially(self, db_session, admin_user):
        result = await SchemeRepository.get_schemes_by_tenant(db_session, admin_user.tenant_id)
        assert result == []

    async def test_create_and_get_by_id(self, db_session, admin_user):
        scheme = Scheme(
            id=f"sch_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            name="Test Plan",
            description=None,
            monthly_amount=1000.0,
            duration_months=12,
            bonus_description=None,
            is_active=True,
            created_by=admin_user.id,
        )
        await SchemeRepository.create_scheme(db_session, scheme)
        await db_session.commit()

        fetched = await SchemeRepository.get_scheme_by_id(db_session, scheme.id, admin_user.tenant_id)
        assert fetched is not None
        assert fetched.name == "Test Plan"

    async def test_active_only_filter_excludes_inactive(self, db_session, admin_user):
        active = Scheme(
            id=f"sch_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            name="Active Plan",
            monthly_amount=1000.0,
            duration_months=12,
            is_active=True,
            created_by=admin_user.id,
        )
        inactive = Scheme(
            id=f"sch_test_{uuid.uuid4().hex[:12]}",
            tenant_id=admin_user.tenant_id,
            name="Inactive Plan",
            monthly_amount=500.0,
            duration_months=6,
            is_active=False,
            created_by=admin_user.id,
        )
        await SchemeRepository.create_scheme(db_session, active)
        await SchemeRepository.create_scheme(db_session, inactive)
        await db_session.commit()

        active_only = await SchemeRepository.get_schemes_by_tenant(db_session, admin_user.tenant_id, active_only=True)
        names = [s.name for s in active_only]
        assert "Active Plan" in names
        assert "Inactive Plan" not in names

        all_schemes = await SchemeRepository.get_schemes_by_tenant(db_session, admin_user.tenant_id, active_only=False)
        all_names = [s.name for s in all_schemes]
        assert "Active Plan" in all_names
        assert "Inactive Plan" in all_names
