"""
JROS Repository Tests — CustomerRepository
===========================================

Tests repository methods directly against the Supabase PostgreSQL database
(AsyncSession) without going through the HTTP layer.

Covers:
  - get_tenant_by_id
  - get_user_by_id
  - get_kyc_record
  - create_kyc_record
  - get_user_addresses
  - get_address_by_id
  - create_address
  - delete_address
  - unset_default_addresses
  - get_tenant_branches
"""

import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Tenant, User
from app.models.customer import KYCRecord, UserAddress
from app.repositories.customer_repository import CustomerRepository


# ═══════════════════════════════════════════════════════════
# 1. Tenant Repository
# ═══════════════════════════════════════════════════════════

class TestTenantRepository:

    async def test_get_tenant_by_id_returns_tenant(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        result = await CustomerRepository.get_tenant_by_id(
            db_session, test_tenant.id
        )
        assert result is not None
        assert result.id == test_tenant.id
        assert result.name == test_tenant.name

    async def test_get_tenant_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession
    ):
        result = await CustomerRepository.get_tenant_by_id(
            db_session, "tnt_does_not_exist_xyz999"
        )
        assert result is None


# ═══════════════════════════════════════════════════════════
# 2. User Repository
# ═══════════════════════════════════════════════════════════

class TestUserRepository:

    async def test_get_user_by_id_returns_user(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerRepository.get_user_by_id(
            db_session, customer_user.id, customer_user.tenant_id
        )
        assert result is not None
        assert result.id == customer_user.id

    async def test_get_user_by_id_wrong_tenant_returns_none(
        self, db_session: AsyncSession, customer_user: User
    ):
        """Tenant isolation: wrong tenant_id must return None."""
        result = await CustomerRepository.get_user_by_id(
            db_session, customer_user.id, "tnt_wrong_tenant_xyz"
        )
        assert result is None

    async def test_get_user_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        result = await CustomerRepository.get_user_by_id(
            db_session, "usr_does_not_exist_abc", test_tenant.id
        )
        assert result is None


# ═══════════════════════════════════════════════════════════
# 3. KYC Repository
# ═══════════════════════════════════════════════════════════

class TestKYCRepository:

    async def test_get_kyc_record_none_when_empty(
        self, db_session: AsyncSession, customer_user: User
    ):
        result = await CustomerRepository.get_kyc_record(
            db_session, customer_user.id, customer_user.tenant_id
        )
        assert result is None

    async def test_create_and_get_kyc_record(
        self, db_session: AsyncSession, customer_user: User
    ):
        uid = uuid.uuid4().hex[:8]
        record = KYCRecord(
            id=f"kyc_test_{uid}",
            user_id=customer_user.id,
            tenant_id=customer_user.tenant_id,
            doc_type="PAN",
            doc_number=f"ABCDE{uid[:4].upper()}F",
            status="Pending",
        )
        await CustomerRepository.create_kyc_record(db_session, record)
        await db_session.commit()

        fetched = await CustomerRepository.get_kyc_record(
            db_session, customer_user.id, customer_user.tenant_id
        )
        assert fetched is not None
        assert fetched.doc_type == "PAN"
        assert fetched.status == "Pending"


# ═══════════════════════════════════════════════════════════
# 3b. Admin KYC Repository
# ═══════════════════════════════════════════════════════════

class TestAdminKYCRepository:

    async def _create_record(self, db_session: AsyncSession, user: User) -> KYCRecord:
        uid = uuid.uuid4().hex[:8]
        record = KYCRecord(
            id=f"kyc_test_{uid}",
            user_id=user.id,
            tenant_id=user.tenant_id,
            doc_type="PAN",
            doc_number=f"ABCDE{uid[:4].upper()}F",
            status="Pending",
        )
        await CustomerRepository.create_kyc_record(db_session, record)
        await db_session.commit()
        return record

    async def test_get_kyc_records_by_tenant_includes_created_record(
        self, db_session: AsyncSession, customer_user: User
    ):
        record = await self._create_record(db_session, customer_user)
        results = await CustomerRepository.get_kyc_records_by_tenant(
            db_session, customer_user.tenant_id
        )
        assert any(r.id == record.id for r in results)

    async def test_get_kyc_records_by_tenant_eager_loads_user(
        self, db_session: AsyncSession, customer_user: User
    ):
        record = await self._create_record(db_session, customer_user)
        results = await CustomerRepository.get_kyc_records_by_tenant(
            db_session, customer_user.tenant_id
        )
        found = next(r for r in results if r.id == record.id)
        assert found.user.id == customer_user.id
        assert found.user.name == customer_user.name

    async def test_get_kyc_record_by_id_returns_record(
        self, db_session: AsyncSession, customer_user: User
    ):
        record = await self._create_record(db_session, customer_user)
        fetched = await CustomerRepository.get_kyc_record_by_id(
            db_session, record.id, customer_user.tenant_id
        )
        assert fetched is not None
        assert fetched.id == record.id

    async def test_get_kyc_record_by_id_wrong_tenant_returns_none(
        self, db_session: AsyncSession, customer_user: User
    ):
        record = await self._create_record(db_session, customer_user)
        fetched = await CustomerRepository.get_kyc_record_by_id(
            db_session, record.id, "tnt_wrong_tenant_xyz"
        )
        assert fetched is None

    async def test_get_kyc_record_by_id_nonexistent_returns_none(
        self, db_session: AsyncSession, customer_user: User
    ):
        fetched = await CustomerRepository.get_kyc_record_by_id(
            db_session, "kyc_does_not_exist_xyz", customer_user.tenant_id
        )
        assert fetched is None


# ═══════════════════════════════════════════════════════════
# 4. Address Repository
# ═══════════════════════════════════════════════════════════

class TestAddressRepository:

    def _make_address(self, user: User) -> UserAddress:
        uid = uuid.uuid4().hex[:8]
        return UserAddress(
            id=f"addr_test_{uid}",
            user_id=user.id,
            tenant_id=user.tenant_id,
            name="Test Recipient",
            phone="9876543210",
            house="1A",
            street="MG Road",
            area="Connaught Place",
            city="New Delhi",
            state="Delhi",
            pincode="110001",
            country="India",
            type="Home",
            is_default=False,
        )

    async def test_create_address_persists(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = self._make_address(customer_user)
        await CustomerRepository.create_address(db_session, addr)
        await db_session.commit()

        fetched = await CustomerRepository.get_address_by_id(
            db_session, addr.id, customer_user.id, customer_user.tenant_id
        )
        assert fetched is not None
        assert fetched.city == "New Delhi"

    async def test_get_user_addresses_returns_list(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = self._make_address(customer_user)
        await CustomerRepository.create_address(db_session, addr)
        await db_session.commit()

        addresses = await CustomerRepository.get_user_addresses(
            db_session, customer_user.id, customer_user.tenant_id
        )
        assert isinstance(addresses, list)
        assert any(a.id == addr.id for a in addresses)

    async def test_get_address_wrong_tenant_returns_none(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = self._make_address(customer_user)
        await CustomerRepository.create_address(db_session, addr)
        await db_session.commit()

        result = await CustomerRepository.get_address_by_id(
            db_session, addr.id, customer_user.id, "tnt_wrong_xyz"
        )
        assert result is None, "Tenant isolation failed: address returned for wrong tenant"

    async def test_delete_address_removes_from_db(
        self, db_session: AsyncSession, customer_user: User
    ):
        addr = self._make_address(customer_user)
        await CustomerRepository.create_address(db_session, addr)
        await db_session.commit()

        to_delete = await CustomerRepository.get_address_by_id(
            db_session, addr.id, customer_user.id, customer_user.tenant_id
        )
        await CustomerRepository.delete_address(db_session, to_delete)
        await db_session.commit()

        result = await CustomerRepository.get_address_by_id(
            db_session, addr.id, customer_user.id, customer_user.tenant_id
        )
        assert result is None, "Address was not deleted"

    async def test_unset_default_addresses(
        self, db_session: AsyncSession, customer_user: User
    ):
        """Setting default=True on two addresses then unsetting should clear both."""
        addr1 = self._make_address(customer_user)
        addr1.is_default = True
        addr2 = self._make_address(customer_user)
        addr2.is_default = True
        await CustomerRepository.create_address(db_session, addr1)
        await CustomerRepository.create_address(db_session, addr2)
        await db_session.commit()

        await CustomerRepository.unset_default_addresses(
            db_session, customer_user.id, customer_user.tenant_id
        )
        await db_session.commit()

        addresses = await CustomerRepository.get_user_addresses(
            db_session, customer_user.id, customer_user.tenant_id
        )
        for a in addresses:
            if a.id in [addr1.id, addr2.id]:
                assert a.is_default is False, f"Address {a.id} still has is_default=True"


# ═══════════════════════════════════════════════════════════
# 5. Branch Repository
# ═══════════════════════════════════════════════════════════

class TestBranchRepository:

    async def test_get_tenant_branches_returns_list(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        branches = await CustomerRepository.get_tenant_branches(
            db_session, test_tenant.id
        )
        assert isinstance(branches, list)

    async def test_get_branches_wrong_tenant_returns_empty(
        self, db_session: AsyncSession
    ):
        """Non-existent tenant should return empty list."""
        branches = await CustomerRepository.get_tenant_branches(
            db_session, "tnt_nonexistent_xyz999"
        )
        assert branches == []
