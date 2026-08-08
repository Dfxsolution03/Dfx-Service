from typing import List, Optional, Tuple
from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.constants import ROLE_CUSTOMER, ROLE_STAFF
from app.models.auth import Tenant, User, Role
from app.models.customer import KYCRecord, UserAddress, Branch, KycDocument


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
    async def create_kyc_document(db: AsyncSession, document: KycDocument) -> KycDocument:
        db.add(document)
        return document

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

    # ─── Phase 7 — Admin Branch Management ───

    @staticmethod
    async def get_all_tenant_branches(db: AsyncSession, tenant_id: str) -> List[Branch]:
        """Admin: every branch for the tenant including inactive ones —
        distinct from get_tenant_branches, which is the customer-facing
        locator and deliberately only returns active branches."""
        stmt = select(Branch).where(Branch.tenant_id == tenant_id).order_by(Branch.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_branch_by_id_for_tenant(
        db: AsyncSession, tenant_id: str, branch_id: str
    ) -> Optional[Branch]:
        stmt = select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_branch(db: AsyncSession, branch: Branch) -> Branch:
        db.add(branch)
        return branch

    # ─── Phase 6C / Module 33 — Admin Customer Management ───

    @staticmethod
    async def get_customers_by_tenant(
        db: AsyncSession, tenant_id: str, page: int, limit: int, search: Optional[str]
    ) -> Tuple[List[User], int]:
        """Admin: paginated, searchable list of Customer-role users for the
        tenant — the one "list all customers" query this codebase never had."""
        conditions = [User.tenant_id == tenant_id, Role.name == ROLE_CUSTOMER]
        if search:
            like = f"%{search}%"
            conditions.append(or_(User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like)))

        count_stmt = select(func.count(User.id)).join(Role, User.role_id == Role.id)
        list_stmt = select(User).join(Role, User.role_id == Role.id).options(joinedload(User.role))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        list_stmt = list_stmt.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit)
        rows = (await db.execute(list_stmt)).unique().scalars().all()
        return list(rows), total

    @staticmethod
    async def get_customer_by_id_for_tenant(
        db: AsyncSession, tenant_id: str, customer_id: str
    ) -> Optional[User]:
        """Admin: fetch a single user, own-tenant only, AND only if they're
        actually a Customer — so this endpoint can never be used to peek at
        an Admin/Staff account under the same tenant."""
        stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .options(joinedload(User.role))
            .where(User.id == customer_id, User.tenant_id == tenant_id, Role.name == ROLE_CUSTOMER)
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one_or_none()

    # ─── Phase 6C / Module 33 — Admin Staff Management ───

    @staticmethod
    async def get_staff_by_tenant(db: AsyncSession, tenant_id: str) -> List[User]:
        stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .options(joinedload(User.role))
            .where(User.tenant_id == tenant_id, Role.name == ROLE_STAFF)
            .order_by(User.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())

    @staticmethod
    async def get_staff_by_id_for_tenant(
        db: AsyncSession, tenant_id: str, staff_id: str
    ) -> Optional[User]:
        stmt = (
            select(User)
            .join(Role, User.role_id == Role.id)
            .options(joinedload(User.role))
            .where(User.id == staff_id, User.tenant_id == tenant_id, Role.name == ROLE_STAFF)
        )
        result = await db.execute(stmt)
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """Global (not tenant-scoped) — email uniqueness is global in this
        codebase, same check auth_service.register_customer already performs."""
        stmt = select(User).where(User.email == email)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_user_by_phone(db: AsyncSession, phone: str) -> Optional[User]:
        stmt = select(User).where(User.phone == phone)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_role_by_name(db: AsyncSession, name: str) -> Optional[Role]:
        stmt = select(Role).where(Role.name == name)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def create_staff_user(db: AsyncSession, user: User) -> User:
        db.add(user)
        return user

    # ─── Phase 6C / Module 33 — Vendor/Tenant Self-Service Profile ───

    @staticmethod
    async def get_tenant_by_contact_email(db: AsyncSession, contact_email: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.contact_email == contact_email)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_tenant_by_contact_phone(db: AsyncSession, contact_phone: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.contact_phone == contact_phone)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_tenant_by_gst_number(db: AsyncSession, gst_number: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.gst_number == gst_number)
        return (await db.execute(stmt)).scalar_one_or_none()
