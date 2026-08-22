"""
DFX Backend Tests — Phase 8: Staff Scheme/Business permission grouping
======================================================================

Constants/schema/authorization tests need no database (authorization is tested
by calling the dependency's checker directly with lightweight fake users). The
staff CRUD persistence tests require Postgres (TEST_DATABASE_URL).
"""
import asyncio
from types import SimpleNamespace

import pytest


# ───────────────────────── Grouping constants (no database) ─────────────────────────

class TestPermissionGroupingConstants:
    def test_groups_use_only_existing_keys(self):
        from app.core.constants import STAFF_MODULE_GROUPS, ALL_STAFF_MODULES
        for g in STAFF_MODULE_GROUPS:
            for m in g["modules"]:
                assert m["key"] in ALL_STAFF_MODULES, f"{m['key']} not a real module key"
                assert m["label"]

    def test_both_groups_present(self):
        from app.core.constants import STAFF_MODULE_GROUPS
        names = {g["group"] for g in STAFF_MODULE_GROUPS}
        assert names == {"SCHEME", "BUSINESS"}

    def test_expected_membership(self):
        from app.core.constants import STAFF_MODULE_GROUPS
        by_group = {g["group"]: {m["key"] for m in g["modules"]} for g in STAFF_MODULE_GROUPS}
        assert {"customers", "schemes", "enrollments", "payments", "kyc"} <= by_group["SCHEME"]
        assert {"catalogue", "billing", "gold_rate", "branches", "marketing"} <= by_group["BUSINESS"]
        # Shared modules surface under both groups (single underlying key).
        for shared in ("reports", "analytics", "notifications"):
            assert shared in by_group["SCHEME"] and shared in by_group["BUSINESS"]


# ───────────────────────── Assignment validation (no database) ─────────────────────────

class TestModuleValidation:
    def test_known_modules_accepted(self):
        from app.schemas.staff import _validate_modules
        assert _validate_modules(["customers", "catalogue"]) == ["customers", "catalogue"]

    def test_unknown_module_rejected(self):
        from app.schemas.staff import _validate_modules
        with pytest.raises(Exception):
            _validate_modules(["customers", "not_a_real_module"])

    def test_mixed_group_assignment_ok(self):
        from app.schemas.staff import _validate_modules
        # A staff member may legitimately hold both scheme- and business-group keys.
        assert _validate_modules(["schemes", "billing"]) == ["schemes", "billing"]


# ───────────────────────── Authorization semantics (no database) ─────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _user(role_name, perms=""):
    return SimpleNamespace(role=SimpleNamespace(name=role_name), staff_permissions=perms)


class TestAuthorization:
    def _checker(self, *modules):
        from app.permissions.dependencies import require_admin_or_staff_module
        return require_admin_or_staff_module(*modules)

    def test_admin_unrestricted(self):
        from app.core.constants import ROLE_ADMIN
        checker = self._checker("schemes")
        u = _user(ROLE_ADMIN, perms="")  # no staff perms at all
        assert _run(checker(current_user=u)) is u

    def test_superadmin_unrestricted(self):
        from app.core.constants import ROLE_SUPERADMIN
        checker = self._checker("billing")
        u = _user(ROLE_SUPERADMIN)
        assert _run(checker(current_user=u)) is u

    def test_staff_allowed_for_granted_module(self):
        from app.core.constants import ROLE_STAFF
        checker = self._checker("schemes")
        u = _user(ROLE_STAFF, perms="schemes,enrollments")
        assert _run(checker(current_user=u)) is u

    def test_staff_denied_for_ungranted_module(self):
        from app.core.constants import ROLE_STAFF
        from app.exceptions.base import ForbiddenException
        checker = self._checker("billing")  # business module
        u = _user(ROLE_STAFF, perms="schemes,enrollments")  # only scheme perms
        with pytest.raises(ForbiddenException):
            _run(checker(current_user=u))

    def test_cross_group_isolation(self):
        from app.core.constants import ROLE_STAFF
        from app.exceptions.base import ForbiddenException
        # A staff member with only business perms cannot reach a scheme module.
        checker = self._checker("schemes")
        u = _user(ROLE_STAFF, perms="catalogue,billing")
        with pytest.raises(ForbiddenException):
            _run(checker(current_user=u))

    def test_customer_denied(self):
        from app.core.constants import ROLE_CUSTOMER
        from app.exceptions.base import ForbiddenException
        checker = self._checker("schemes")
        with pytest.raises(ForbiddenException):
            _run(checker(current_user=_user(ROLE_CUSTOMER)))


# ───────────────────────── Catalog service (no DB, needs app importable) ─────────────────────────

class TestCatalogService:
    def test_catalog_matches_constants(self):
        from app.services.staff_service import StaffService
        from app.core.constants import ALL_STAFF_MODULES
        catalog = StaffService.get_permission_catalog()
        assert {g.group for g in catalog.groups} == {"SCHEME", "BUSINESS"}
        assert set(catalog.all_modules) == set(ALL_STAFF_MODULES)


# ───────────────────────── DB-backed integration (require Postgres) ─────────────────────────

class TestStaffAssignmentDB:
    async def test_create_staff_with_scheme_perms(self, db_session, admin_user):
        from app.services.staff_service import StaffService
        from app.schemas.staff import StaffCreateRequest
        import uuid
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(
                name="Scheme Clerk", email=f"s_{uuid.uuid4().hex[:8]}@t.com",
                phone=None, password="TestPass@123",
                permissions=["customers", "schemes", "enrollments"],
            ),
        )
        assert set(staff.permissions) == {"customers", "schemes", "enrollments"}

    async def test_update_staff_business_perms(self, db_session, admin_user):
        from app.services.staff_service import StaffService
        from app.schemas.staff import StaffCreateRequest, StaffPermissionsUpdateRequest
        import uuid
        staff = await StaffService.create_staff(
            db_session, admin_user,
            StaffCreateRequest(
                name="Biz Clerk", email=f"b_{uuid.uuid4().hex[:8]}@t.com",
                phone=None, password="TestPass@123", permissions=["catalogue"],
            ),
        )
        updated = await StaffService.update_staff_permissions(
            db_session, admin_user, staff.id,
            StaffPermissionsUpdateRequest(permissions=["catalogue", "billing", "gold_rate"]),
        )
        assert set(updated.permissions) == {"catalogue", "billing", "gold_rate"}
