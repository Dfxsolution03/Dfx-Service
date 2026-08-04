from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.auth import Tenant, User
from app.models.customer import KYCRecord, UserAddress, Branch


class CustomerRepository:
    @staticmethod
    async def get_tenant_by_id(db: AsyncSession, tenant_id: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_id(
        db: AsyncSession, user_id: str, tenant_id: Optional[str]
    ) -> Optional[User]:
        stmt = select(User).options(joinedload(User.role)).where(User.id == user_id)
        if tenant_id:
            stmt = stmt.where(User.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_kyc_record(
        db: AsyncSession, user_id: str, tenant_id: str
    ) -> Optional[KYCRecord]:
        stmt = (
            select(KYCRecord)
            .where(KYCRecord.user_id == user_id, KYCRecord.tenant_id == tenant_id)
            .order_by(KYCRecord.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create_kyc_record(db: AsyncSession, record: KYCRecord) -> KYCRecord:
        db.add(record)
        return record

    @staticmethod
    async def get_kyc_records_by_tenant(
        db: AsyncSession, tenant_id: str
    ) -> List[KYCRecord]:
        """Admin: list all KYC submissions for a tenant, newest first."""
        stmt = (
            select(KYCRecord)
            .options(joinedload(KYCRecord.user))
            .where(KYCRecord.tenant_id == tenant_id)
            .order_by(KYCRecord.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_kyc_record_by_id(
        db: AsyncSession, kyc_id: str, tenant_id: str
    ) -> Optional[KYCRecord]:
        """Admin: fetch a single KYC submission by its own ID, scoped to tenant."""
        stmt = (
            select(KYCRecord)
            .options(joinedload(KYCRecord.user))
            .where(KYCRecord.id == kyc_id, KYCRecord.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_addresses(
        db: AsyncSession, user_id: str, tenant_id: str
    ) -> List[UserAddress]:
        stmt = (
            select(UserAddress)
            .where(UserAddress.user_id == user_id, UserAddress.tenant_id == tenant_id)
            .order_by(UserAddress.is_default.desc(), UserAddress.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_address_by_id(
        db: AsyncSession, address_id: str, user_id: str, tenant_id: str
    ) -> Optional[UserAddress]:
        stmt = select(UserAddress).where(
            UserAddress.id == address_id,
            UserAddress.user_id == user_id,
            UserAddress.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def unset_default_addresses(
        db: AsyncSession, user_id: str, tenant_id: str
    ) -> None:
        stmt = (
            update(UserAddress)
            .where(
                UserAddress.user_id == user_id,
                UserAddress.tenant_id == tenant_id,
                UserAddress.is_default == True,
            )
            .values(is_default=False)
        )
        await db.execute(stmt)

    @staticmethod
    async def create_address(db: AsyncSession, address: UserAddress) -> UserAddress:
        db.add(address)
        return address

    @staticmethod
    async def delete_address(db: AsyncSession, address: UserAddress) -> None:
        await db.delete(address)

    @staticmethod
    async def get_tenant_branches(
        db: AsyncSession, tenant_id: str
    ) -> List[Branch]:
        stmt = (
            select(Branch)
            .where(Branch.tenant_id == tenant_id, Branch.is_active == True)
            .order_by(Branch.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
