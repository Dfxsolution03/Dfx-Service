from datetime import date
from typing import Dict, List, Optional
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Tenant, User, Role
from app.models.scheme import Scheme
from app.models.enrollment import SchemeEnrollment
from app.models.payment import Payment, STATUS_SUCCESS
from app.core.constants import ROLE_ADMIN, ROLE_CUSTOMER


class SuperAdminRepository:
    """Tenant-CRUD-lite and platform-wide (cross-tenant) aggregation queries
    for Module 14. Per-tenant business aggregation (payments, enrollments,
    gold, schemes) deliberately reuses ReportRepository (Module 12) instead
    of being duplicated here — see SuperAdminService.get_tenant_statistics."""

    # ─── Tenants ───

    @staticmethod
    async def get_tenants(
        db: AsyncSession, status_filter: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Tenant]:
        stmt = select(Tenant).order_by(Tenant.created_at.desc())
        if status_filter:
            stmt = stmt.where(Tenant.status == status_filter)
        if limit:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_tenant_by_id(db: AsyncSession, tenant_id: str) -> Optional[Tenant]:
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ─── Module 29 — Tenant Provisioning uniqueness checks ───

    @staticmethod
    async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_tenant_by_contact_email(db: AsyncSession, contact_email: str) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.contact_email == contact_email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_tenant_by_contact_phone(db: AsyncSession, contact_phone: str) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.contact_phone == contact_phone))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_tenant_by_gst_number(db: AsyncSession, gst_number: str) -> Optional[Tenant]:
        result = await db.execute(select(Tenant).where(Tenant.gst_number == gst_number))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_primary_admin_for_tenant(db: AsyncSession, tenant_id: str) -> Optional[User]:
        """First Admin-role user for a tenant — Tenant has no owner/contact
        columns of its own, so this is the closest real "who runs this
        business" relationship available."""
        stmt = (
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(User.tenant_id == tenant_id, Role.name == ROLE_ADMIN)
            .order_by(User.created_at.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_primary_admins_for_tenants(db: AsyncSession, tenant_ids: List[str]) -> Dict[str, User]:
        """Bulk version of get_primary_admin_for_tenant — avoids N+1 queries on list pages."""
        if not tenant_ids:
            return {}
        stmt = (
            select(User)
            .join(Role, Role.id == User.role_id)
            .where(User.tenant_id.in_(tenant_ids), Role.name == ROLE_ADMIN)
            .order_by(User.tenant_id, User.created_at.asc())
        )
        result = await db.execute(stmt)
        by_tenant: Dict[str, User] = {}
        for user in result.scalars().all():
            if user.tenant_id not in by_tenant:
                by_tenant[user.tenant_id] = user
        return by_tenant

    @staticmethod
    async def get_tenant_status_counts(db: AsyncSession) -> List[dict]:
        stmt = select(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status)
        result = await db.execute(stmt)
        return [{"status": s, "count": int(c)} for s, c in result.all()]

    @staticmethod
    async def get_tenant_growth_trend(
        db: AsyncSession, date_from: date, date_to: date, group_by_month: bool
    ) -> List[dict]:
        created_date = func.date(Tenant.created_at)
        bucket = func.date_trunc("month", Tenant.created_at) if group_by_month else created_date
        stmt = (
            select(bucket.label("bucket"), func.count(Tenant.id).label("new_tenants"))
            .where(created_date >= date_from, created_date <= date_to)
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [{"bucket": row.bucket, "new_tenants": int(row.new_tenants)} for row in rows]

    # ─── Platform-wide (cross-tenant) entity counts ───

    @staticmethod
    async def get_platform_entity_counts(db: AsyncSession) -> dict:
        total_customers_stmt = (
            select(func.count(User.id))
            .join(Role, Role.id == User.role_id)
            .where(Role.name == ROLE_CUSTOMER)
        )
        total_schemes_stmt = select(func.count(Scheme.id))
        total_enrollments_stmt = select(func.count(SchemeEnrollment.id))
        total_payments_stmt = select(
            func.count(Payment.id),
            func.coalesce(
                func.sum(case((Payment.payment_status == STATUS_SUCCESS, Payment.amount), else_=0.0)), 0.0
            ),
        )

        total_customers = (await db.execute(total_customers_stmt)).scalar_one()
        total_schemes = (await db.execute(total_schemes_stmt)).scalar_one()
        total_enrollments = (await db.execute(total_enrollments_stmt)).scalar_one()
        payments_count, payments_amount = (await db.execute(total_payments_stmt)).one()

        return {
            "total_customers": int(total_customers),
            "total_schemes": int(total_schemes),
            "total_enrollments": int(total_enrollments),
            "total_payments": int(payments_count),
            "total_payment_amount": float(payments_amount),
        }
