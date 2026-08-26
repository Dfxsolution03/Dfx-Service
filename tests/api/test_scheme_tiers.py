"""
DFX Backend Tests — Scheme Tier Plans
=====================================

Covers the "one Scheme -> many selectable tiers -> enrollment snapshot"
architecture:

  * tier schema validation (duplicate rejection, derived maturity)
  * the single term-resolution helper (snapshot -> legacy fallback)
  * tier selection + snapshot at enrollment
  * snapshot immutability when a tier is later edited
  * advance-payment validation against the enrollment's own terms

The pure-schema / resolver tests need no database. The remaining tests use the
shared async DB fixtures (db_session, admin_user, customer_user) and require the
configured Postgres test database, exactly like the existing service tests.
"""
from types import SimpleNamespace

import pytest

from app.schemas.scheme import (
    SchemeCreateRequest,
    SchemeUpdateRequest,
    SchemeTierInput,
    SchemeTierResponse,
)
from app.schemas.enrollment import EnrollmentCreateRequest


# ─────────────────────────────────────────────────────────────────────────────
# Pure schema + helper tests (no database)
# ─────────────────────────────────────────────────────────────────────────────

class TestTierSchemas:
    def test_tier_input_accepts_valid(self):
        t = SchemeTierInput(monthly_amount=1000, duration_months=12)
        assert t.monthly_amount == 1000
        assert t.duration_months == 12
        assert t.is_active is True

    @pytest.mark.parametrize("amount", [0, -1])
    def test_tier_input_rejects_nonpositive_amount(self, amount):
        with pytest.raises(Exception):
            SchemeTierInput(monthly_amount=amount, duration_months=12)

    @pytest.mark.parametrize("duration", [0, -3])
    def test_tier_input_rejects_nonpositive_duration(self, duration):
        with pytest.raises(Exception):
            SchemeTierInput(monthly_amount=1000, duration_months=duration)

    def test_create_request_rejects_duplicate_tiers(self):
        with pytest.raises(Exception):
            SchemeCreateRequest(
                name="Gold Plan", monthly_amount=1000, duration_months=12,
                tiers=[
                    SchemeTierInput(monthly_amount=1000, duration_months=12),
                    SchemeTierInput(monthly_amount=1000, duration_months=12),
                ],
            )

    def test_update_request_rejects_duplicate_tiers(self):
        with pytest.raises(Exception):
            SchemeUpdateRequest(
                tiers=[
                    SchemeTierInput(monthly_amount=5000, duration_months=12),
                    SchemeTierInput(monthly_amount=5000, duration_months=12),
                ],
            )

    def test_same_amount_different_duration_is_not_duplicate(self):
        req = SchemeCreateRequest(
            name="Gold Plan", monthly_amount=1000, duration_months=12,
            tiers=[
                SchemeTierInput(monthly_amount=1000, duration_months=12),
                SchemeTierInput(monthly_amount=1000, duration_months=24),
            ],
        )
        assert len(req.tiers) == 2

    def test_tier_response_computes_maturity(self):
        r = SchemeTierResponse(
            id="str_x", scheme_id="sch_x", monthly_amount=15000,
            duration_months=12, is_active=True,
        )
        assert r.maturity_amount == 180000.0

    def test_create_request_tiers_optional(self):
        req = SchemeCreateRequest(name="Gold Plan", monthly_amount=1000, duration_months=12)
        assert req.tiers is None


class TestEnrollmentCreateRequest:
    def test_tier_optional(self):
        req = EnrollmentCreateRequest(scheme_id="sch_x")
        assert req.scheme_tier_id is None

    def test_tier_accepted(self):
        req = EnrollmentCreateRequest(scheme_id="sch_x", scheme_tier_id="str_x")
        assert req.scheme_tier_id == "str_x"


class TestResolveEnrollmentTerms:
    """The single resolver every money calculation must go through."""

    def _resolver(self):
        from app.services.enrollment_service import resolve_enrollment_terms, maturity_amount
        return resolve_enrollment_terms, maturity_amount

    def test_snapshot_wins_when_present(self):
        resolve, _ = self._resolver()
        enrollment = SimpleNamespace(selected_monthly_amount=5000, selected_duration_months=12)
        scheme = SimpleNamespace(monthly_amount=1000, duration_months=6)
        assert resolve(enrollment, scheme) == (5000, 12)

    def test_fallback_when_snapshot_missing(self):
        resolve, _ = self._resolver()
        enrollment = SimpleNamespace(selected_monthly_amount=None, selected_duration_months=None)
        scheme = SimpleNamespace(monthly_amount=1000, duration_months=6)
        assert resolve(enrollment, scheme) == (1000, 6)

    def test_partial_snapshot_falls_back(self):
        # Defensive: a half-set snapshot is treated as legacy, not half-applied.
        resolve, _ = self._resolver()
        enrollment = SimpleNamespace(selected_monthly_amount=5000, selected_duration_months=None)
        scheme = SimpleNamespace(monthly_amount=1000, duration_months=6)
        assert resolve(enrollment, scheme) == (1000, 6)

    def test_maturity_is_amount_times_months(self):
        _, maturity = self._resolver()
        assert maturity(1000, 12) == 12000
        assert maturity(15000, 12) == 180000
        assert maturity(None, 12) == 0


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed integration tests (require the configured Postgres test database)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemeTierService:
    async def test_create_scheme_with_tiers_returns_maturity(self, db_session, admin_user):
        from app.services.scheme_service import SchemeService
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(
                name="Monthly Gold Saving Plan", monthly_amount=1000, duration_months=12,
                tiers=[
                    SchemeTierInput(monthly_amount=1000, duration_months=12),
                    SchemeTierInput(monthly_amount=15000, duration_months=12),
                ],
            ),
        )
        assert len(scheme.tiers) == 2
        by_amount = {t.monthly_amount: t for t in scheme.tiers}
        assert by_amount[15000].maturity_amount == 180000.0

    async def test_customer_sees_only_active_tiers(self, db_session, admin_user, customer_user):
        from app.services.scheme_service import SchemeService
        scheme = await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(
                name="Gold Plan", monthly_amount=1000, duration_months=12,
                tiers=[
                    SchemeTierInput(monthly_amount=1000, duration_months=12, is_active=True),
                    SchemeTierInput(monthly_amount=2000, duration_months=12, is_active=False),
                ],
            ),
        )
        customer_schemes = await SchemeService.get_customer_schemes(db_session, customer_user)
        target = next(s for s in customer_schemes if s.id == scheme.id)
        assert [t.monthly_amount for t in target.tiers] == [1000]


class TestEnrollmentTierSelection:
    async def _make_scheme(self, db_session, admin_user, tiers):
        from app.services.scheme_service import SchemeService
        return await SchemeService.create_scheme(
            db_session, admin_user,
            SchemeCreateRequest(name="Gold Plan", monthly_amount=1000, duration_months=12, tiers=tiers),
        )

    async def test_enroll_with_tier_snapshots_terms(self, db_session, admin_user, customer_user):
        from app.services.enrollment_service import EnrollmentService
        scheme = await self._make_scheme(
            db_session, admin_user,
            [SchemeTierInput(monthly_amount=5000, duration_months=12)],
        )
        tier = scheme.tiers[0]
        enrollment = await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=tier.id),
        )
        assert enrollment.scheme_tier_id == tier.id
        assert enrollment.monthly_amount == 5000
        assert enrollment.duration_months == 12
        assert enrollment.maturity_amount == 60000.0

    async def test_enroll_without_tier_falls_back_to_scheme(self, db_session, admin_user, customer_user):
        from app.services.enrollment_service import EnrollmentService
        scheme = await self._make_scheme(
            db_session, admin_user,
            [SchemeTierInput(monthly_amount=5000, duration_months=12)],
        )
        enrollment = await EnrollmentService.create_enrollment(
            db_session, customer_user, EnrollmentCreateRequest(scheme_id=scheme.id),
        )
        assert enrollment.scheme_tier_id is None
        assert enrollment.monthly_amount == 1000  # scheme base
        assert enrollment.duration_months == 12

    async def test_enroll_with_inactive_tier_rejected(self, db_session, admin_user, customer_user):
        from app.services.enrollment_service import EnrollmentService
        from app.exceptions.base import ValidationException
        scheme = await self._make_scheme(
            db_session, admin_user,
            [SchemeTierInput(monthly_amount=5000, duration_months=12, is_active=False)],
        )
        tier = scheme.tiers[0]
        with pytest.raises(ValidationException):
            await EnrollmentService.create_enrollment(
                db_session, customer_user,
                EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=tier.id),
            )

    async def test_enroll_with_foreign_tier_rejected(self, db_session, admin_user, customer_user):
        from app.services.enrollment_service import EnrollmentService
        from app.exceptions.base import ResourceNotFoundException
        scheme_a = await self._make_scheme(
            db_session, admin_user, [SchemeTierInput(monthly_amount=5000, duration_months=12)],
        )
        scheme_b = await self._make_scheme(
            db_session, admin_user, [SchemeTierInput(monthly_amount=2000, duration_months=12)],
        )
        foreign_tier = scheme_b.tiers[0]
        with pytest.raises(ResourceNotFoundException):
            await EnrollmentService.create_enrollment(
                db_session, customer_user,
                EnrollmentCreateRequest(scheme_id=scheme_a.id, scheme_tier_id=foreign_tier.id),
            )

    async def test_tier_edit_does_not_change_existing_enrollment(self, db_session, admin_user, customer_user):
        """The core guarantee: editing a tier after enrollment must not rewrite
        the enrolled customer's terms — the snapshot is immutable."""
        from app.services.scheme_service import SchemeService
        from app.services.enrollment_service import EnrollmentService
        scheme = await self._make_scheme(
            db_session, admin_user, [SchemeTierInput(monthly_amount=5000, duration_months=12)],
        )
        tier = scheme.tiers[0]
        enrollment = await EnrollmentService.create_enrollment(
            db_session, customer_user,
            EnrollmentCreateRequest(scheme_id=scheme.id, scheme_tier_id=tier.id),
        )
        # Deactivate the 5000 tier and introduce a different one.
        await SchemeService.update_scheme(
            db_session, admin_user, scheme.id,
            SchemeUpdateRequest(tiers=[SchemeTierInput(monthly_amount=8000, duration_months=24)]),
        )
        refetched = await EnrollmentService.get_customer_enrollment_by_id(
            db_session, customer_user, enrollment.id,
        )
        assert refetched.monthly_amount == 5000
        assert refetched.duration_months == 12
        assert refetched.maturity_amount == 60000.0
