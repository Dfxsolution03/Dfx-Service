from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.enrollment import SchemeEnrollment


class EnrollmentRepository:
    @staticmethod
    def _with_relations(stmt):
        # Both customer and scheme are many-to-one from SchemeEnrollment, so
        # joinedload collapses what was 3 sequential round trips (base query
        # + 2 selectinload batches) into 1 query with 2 joins — no risk of
        # duplicate rows since neither relationship fans out per enrollment.
        return stmt.options(
            joinedload(SchemeEnrollment.customer),
            joinedload(SchemeEnrollment.scheme),
        )

    @staticmethod
    async def get_enrollments_by_tenant(
        db: AsyncSession, tenant_id: str
    ) -> List[SchemeEnrollment]:
        stmt = EnrollmentRepository._with_relations(
            select(SchemeEnrollment)
            .where(SchemeEnrollment.tenant_id == tenant_id)
            .order_by(SchemeEnrollment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_enrollment_by_id(
        db: AsyncSession, enrollment_id: str, tenant_id: str
    ) -> Optional[SchemeEnrollment]:
        stmt = EnrollmentRepository._with_relations(
            select(SchemeEnrollment).where(
                SchemeEnrollment.id == enrollment_id,
                SchemeEnrollment.tenant_id == tenant_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_enrollments_by_customer(
        db: AsyncSession, tenant_id: str, customer_id: str
    ) -> List[SchemeEnrollment]:
        stmt = EnrollmentRepository._with_relations(
            select(SchemeEnrollment)
            .where(
                SchemeEnrollment.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
            .order_by(SchemeEnrollment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_enrollment_by_id_for_customer(
        db: AsyncSession, enrollment_id: str, tenant_id: str, customer_id: str
    ) -> Optional[SchemeEnrollment]:
        stmt = EnrollmentRepository._with_relations(
            select(SchemeEnrollment).where(
                SchemeEnrollment.id == enrollment_id,
                SchemeEnrollment.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_enrollment_for_scheme(
        db: AsyncSession, tenant_id: str, customer_id: str, scheme_id: str
    ) -> Optional[SchemeEnrollment]:
        stmt = select(SchemeEnrollment).where(
            SchemeEnrollment.tenant_id == tenant_id,
            SchemeEnrollment.customer_id == customer_id,
            SchemeEnrollment.scheme_id == scheme_id,
            SchemeEnrollment.status == "ACTIVE",
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_enrollment(db: AsyncSession, enrollment: SchemeEnrollment) -> SchemeEnrollment:
        db.add(enrollment)
        return enrollment
