"""
Phase 1 — Customer Date of Birth.

Schema tests (TestDobValidation) are pure-pydantic and need no database.
Service tests (TestDobPersistence) use the standard fixtures and exercise the
NULL-DOB backfill / update paths.
"""
import datetime
import pytest
from pydantic import ValidationError

from app.models.auth import User
from app.schemas.auth import UserRegisterRequest, GoogleLoginRequest, UserResponse
from app.schemas.customer import (
    AdminCustomerCreateRequest,
    AdminCustomerUpdateRequest,
    ProfileUpdateRequest,
)

_FUTURE = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()


class TestDobValidation:
    def test_valid_dob_accepted_on_signup(self):
        m = UserRegisterRequest(name="Priya", password="secret1", tenant_id="t1", date_of_birth="1995-08-21")
        assert m.date_of_birth == datetime.date(1995, 8, 21)

    def test_malformed_dob_rejected(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Priya", password="secret1", tenant_id="t1", date_of_birth="2020-13-40")

    def test_future_dob_rejected(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Priya", password="secret1", tenant_id="t1", date_of_birth=_FUTURE)

    def test_signup_requires_dob(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(name="Priya", password="secret1", tenant_id="t1")

    def test_admin_create_requires_dob(self):
        with pytest.raises(ValidationError):
            AdminCustomerCreateRequest(name="Priya", password="password1")

    def test_admin_create_accepts_dob(self):
        m = AdminCustomerCreateRequest(name="Priya", password="password1", date_of_birth="1990-01-01")
        assert m.date_of_birth == datetime.date(1990, 1, 1)

    def test_google_dob_optional_for_login(self):
        assert GoogleLoginRequest(id_token="x").date_of_birth is None

    def test_google_future_dob_rejected_when_provided(self):
        with pytest.raises(ValidationError):
            GoogleLoginRequest(id_token="x", date_of_birth=_FUTURE)

    def test_profile_update_dob_optional(self):
        assert ProfileUpdateRequest().date_of_birth is None

    def test_profile_update_future_dob_rejected(self):
        with pytest.raises(ValidationError):
            ProfileUpdateRequest(date_of_birth=_FUTURE)

    def test_admin_update_dob_optional(self):
        assert AdminCustomerUpdateRequest(date_of_birth="1988-05-05").date_of_birth == datetime.date(1988, 5, 5)

    def test_response_carries_dob(self):
        u = UserResponse(
            id="1", tenant_id="t", role="Customer", name="P", email=None, phone=None,
            kyc_status="Pending", member_since=None, date_of_birth="1995-08-21", is_active=True,
        )
        assert u.date_of_birth == datetime.date(1995, 8, 21)


class TestDobPersistence:
    async def test_existing_null_dob_customer_can_authenticate(self, db_session, customer_user: User):
        # customer_user is created with no DOB → login must still succeed.
        from app.services.auth_service import AuthService
        from app.schemas.auth import UserLoginRequest
        assert customer_user.date_of_birth is None
        tokens = await AuthService.login_user(
            db_session, UserLoginRequest(username=customer_user.email or customer_user.phone, password="password123")
        )
        assert tokens.access_token

    async def test_existing_customer_can_add_dob_via_profile(self, db_session, customer_user: User):
        from app.services.customer_service import CustomerService
        res = await CustomerService.update_profile(
            db_session, customer_user, ProfileUpdateRequest(date_of_birth="1992-03-15")
        )
        assert str(res.date_of_birth) == "1992-03-15"

    async def test_get_profile_returns_dob(self, db_session, customer_user: User):
        from app.services.customer_service import CustomerService
        await CustomerService.update_profile(db_session, customer_user, ProfileUpdateRequest(date_of_birth="1985-07-01"))
        res = await CustomerService.get_profile(db_session, customer_user)
        assert str(res.date_of_birth) == "1985-07-01"
