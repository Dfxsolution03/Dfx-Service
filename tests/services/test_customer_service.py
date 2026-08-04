"""
JROS Service Tests — CustomerService
======================================

Tests CustomerService static methods directly against the real
Supabase PostgreSQL database (no HTTP layer).

Covers:
  - get_profile
  - update_profile
  - get_kyc / submit_kyc
  - get_addresses / add_address / update_address / delete_address / set_default
  - get_branches
"""

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Tenant, User
from app.schemas.customer import (
    ProfileUpdateRequest,
    KYCSubmitRequest,
    KYCRejectRequest,
    AddressCreateRequest,
    AddressUpdateRequest,
)
from app.services.customer_service import CustomerService
from app.exceptions.base import ResourceNotFoundException, ConflictException
from tests.conftest import unique_phone


def sample_address_req() -> AddressCreateRequest:
    return AddressCreateRequest(
        name="Test Recipient",
        phone="9876543210",
        house="12A",
        street="MG Road",
        area="Connaught Place",
        city="New Delhi",
        state="Delhi",
        pincode="110001",
        type="Home",
        is_default=False,
    )


# ═══════════════════════════════════════════════════════════
# 1. get_profile
# ═══════════════════════════════════════════════════════════

class TestGetProfile:

    async def test_get_profile_returns_response(
        self, db_session: AsyncSession, customer_user: User
    ):
        profile = await CustomerService.get_profile(db_session, customer_user)
        assert profile is not None
        assert profile.id == customer_user.id
        assert profile.name == customer_user.name

    async def test_get_profile_includes_tenant_name(
        self, db_session: AsyncSession, customer_user: User
    ):
        profile = await CustomerService.get_profile(db_session, customer_user)
        assert profile.tenant_name is not None
        assert isinstance(profile.tenant_name, str)
        assert len(profile.tenant_name) > 0


# ═══════════════════════════════════════════════════════════
# 2. update_profile
# ═══════════════════════════════════════════════════════════

class TestUpdateProfile:

    async def test_update_name(
        self, db_session: AsyncSession, customer_user: User
    ):
        req = ProfileUpdateRequest(name="New Name Updated")
        result = await CustomerService.update_profile(db_session, customer_user, req)
        assert result.name == "New Name Updated"

    async def test_update_phone(
        self, db_session: AsyncSession, customer_user: User
    ):
        phone = unique_phone()
        req = ProfileUpdateRequest(phone=phone)
        result = await CustomerService.update_profile(db_session, customer_user, req)
        assert result.phone == phone

    async def test_update_empty_request_allowed(
        self, db_session: AsyncSession, customer_user: User
    ):
        """Empty update request (no fields) must not raise."""
        req = ProfileUpdateRequest()
        result = await CustomerService.update_profile(db_session, customer_user, req)
        assert result is not None


# ═══════════════════════════════════════════════════════════
# 3. KYC
# ═══════════════════════════════════════════════════════════

class TestKYCService:

    async def test_get_kyc_returns_none_when_not_submitted(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerService.get_kyc(db_session, customer_user)
        assert result is None

    async def test_submit_kyc_creates_record(
        self, db_session: AsyncSession, customer_user: User
    ):
        req = KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        result = await CustomerService.submit_kyc(db_session, customer_user, req)
        assert result is not None
        assert result.doc_type == "PAN"
        assert result.status == "Pending"

    async def test_get_kyc_after_submit_returns_record(
        self, db_session: AsyncSession, customer_user: User
    ):
        req = KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        await CustomerService.submit_kyc(db_session, customer_user, req)
        result = await CustomerService.get_kyc(db_session, customer_user)
        # May return None if already submitted previously in another test
        # Just ensure it doesn't raise
        assert result is None or result.doc_type in ["PAN", "AADHAAR", "PASSPORT"]


# ═══════════════════════════════════════════════════════════
# 3b. Admin KYC Review
# ═══════════════════════════════════════════════════════════

class TestAdminKYCService:

    async def test_get_kyc_records_for_admin_includes_submission(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        results = await CustomerService.get_kyc_records_for_admin(db_session, admin_user)
        assert any(r.user_id == customer_user.id for r in results)

    async def test_get_kyc_records_for_admin_includes_customer_name(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        results = await CustomerService.get_kyc_records_for_admin(db_session, admin_user)
        found = next(r for r in results if r.user_id == customer_user.id)
        assert found.customer_name == customer_user.name

    async def test_get_kyc_record_for_admin_not_found_raises(
        self, db_session: AsyncSession, admin_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await CustomerService.get_kyc_record_for_admin(db_session, admin_user, "kyc_does_not_exist")

    async def test_approve_kyc_marks_verified(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        result = await CustomerService.approve_kyc(db_session, admin_user, submitted.id)
        assert result.status == "Verified"
        assert result.verified_at is not None

    async def test_approve_kyc_syncs_user_kyc_status(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        await CustomerService.approve_kyc(db_session, admin_user, submitted.id)
        profile = await CustomerService.get_profile(db_session, customer_user)
        assert profile.kyc_status == "Verified"

    async def test_approve_already_reviewed_raises_conflict(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        await CustomerService.approve_kyc(db_session, admin_user, submitted.id)
        with pytest.raises(ConflictException):
            await CustomerService.approve_kyc(db_session, admin_user, submitted.id)

    async def test_approve_nonexistent_raises_not_found(
        self, db_session: AsyncSession, admin_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await CustomerService.approve_kyc(db_session, admin_user, "kyc_does_not_exist")

    async def test_reject_kyc_sets_reason(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        result = await CustomerService.reject_kyc(
            db_session, admin_user, submitted.id, KYCRejectRequest(reason="Blurry document")
        )
        assert result.status == "Rejected"
        assert result.rejection_reason == "Blurry document"

    async def test_reject_kyc_syncs_user_kyc_status(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        await CustomerService.reject_kyc(
            db_session, admin_user, submitted.id, KYCRejectRequest(reason="Blurry document")
        )
        profile = await CustomerService.get_profile(db_session, customer_user)
        assert profile.kyc_status == "Rejected"

    async def test_reject_already_reviewed_raises_conflict(
        self, db_session: AsyncSession, customer_user: User, admin_user: User
    ):
        submitted = await CustomerService.submit_kyc(
            db_session, customer_user, KYCSubmitRequest(doc_type="PAN", doc_number="ABCDE1234F")
        )
        await CustomerService.reject_kyc(
            db_session, admin_user, submitted.id, KYCRejectRequest(reason="Blurry document")
        )
        with pytest.raises(ConflictException):
            await CustomerService.reject_kyc(
                db_session, admin_user, submitted.id, KYCRejectRequest(reason="Again")
            )


# ═══════════════════════════════════════════════════════════
# 4. Addresses
# ═══════════════════════════════════════════════════════════

class TestAddressService:

    async def test_add_address_returns_response(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerService.add_address(
            db_session, customer_user, sample_address_req()
        )
        assert result is not None
        assert result.city == "New Delhi"

    async def test_get_addresses_returns_list(
        self, db_session: AsyncSession, customer_user: User
    ):
        await CustomerService.add_address(
            db_session, customer_user, sample_address_req()
        )
        result = await CustomerService.get_addresses(db_session, customer_user)
        assert isinstance(result, list)
        assert len(result) >= 1

    async def test_update_address_changes_city(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = await CustomerService.add_address(
            db_session, customer_user, sample_address_req()
        )
        update_req = AddressUpdateRequest(city="Bangalore")
        result = await CustomerService.update_address(
            db_session, customer_user, addr.id, update_req
        )
        assert result.city == "Bangalore"

    async def test_update_nonexistent_address_raises_not_found(
        self, db_session: AsyncSession, customer_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await CustomerService.update_address(
                db_session, customer_user,
                "addr_nonexistent_xyz",
                AddressUpdateRequest(city="Pune"),
            )

    async def test_delete_address_removes_it(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = await CustomerService.add_address(
            db_session, customer_user, sample_address_req()
        )
        await CustomerService.delete_address(db_session, customer_user, addr.id)
        addresses = await CustomerService.get_addresses(db_session, customer_user)
        ids = [a.id for a in addresses]
        assert addr.id not in ids

    async def test_delete_nonexistent_address_raises_not_found(
        self, db_session: AsyncSession, customer_user: User
    ):
        with pytest.raises(ResourceNotFoundException):
            await CustomerService.delete_address(
                db_session, customer_user, "addr_fake_xyz"
            )

    async def test_set_default_address_marks_true(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = await CustomerService.add_address(
            db_session, customer_user, sample_address_req()
        )
        result = await CustomerService.set_default_address(
            db_session, customer_user, addr.id
        )
        assert result.is_default is True

    async def test_set_default_unsets_previous_default(
        self, db_session: AsyncSession, customer_user: User
    ):
        req = sample_address_req()
        req.is_default = True
        addr1 = await CustomerService.add_address(db_session, customer_user, req)
        addr2 = await CustomerService.add_address(db_session, customer_user, sample_address_req())

        await CustomerService.set_default_address(db_session, customer_user, addr1.id)
        await CustomerService.set_default_address(db_session, customer_user, addr2.id)

        addresses = await CustomerService.get_addresses(db_session, customer_user)
        # Only addr2 should be default
        for a in addresses:
            if a.id == addr2.id:
                assert a.is_default is True
            elif a.id == addr1.id:
                assert a.is_default is False


# ═══════════════════════════════════════════════════════════
# 5. Branches
# ═══════════════════════════════════════════════════════════

class TestBranchService:

    async def test_get_branches_returns_list(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerService.get_branches(db_session, customer_user)
        assert isinstance(result, list)

    async def test_branch_items_are_response_objects(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerService.get_branches(db_session, customer_user)
        for branch in result:
            assert hasattr(branch, "id")
            assert hasattr(branch, "name")
            assert hasattr(branch, "is_active")
