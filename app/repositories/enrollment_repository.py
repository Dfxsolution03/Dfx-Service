from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.payment import Payment, STATUS_SUCCESS as PAYMENT_STATUS_SUCCESS
from app.models.enrollment import SchemeRedemption, SchemeEnrollment


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

    @staticmethod
    async def get_enrollment_by_id_for_update(
        db: AsyncSession, enrollment_id: str, tenant_id: str
    ):
        """Tenant-scoped fetch holding a row lock for the rest of the transaction.

        Used only by the closure and redemption paths: two Admins redeeming the
        same enrollment at the same moment must serialise here, or both could
        validate against the same stale available balance and together spend
        more scheme credit than the customer ever paid in."""
        stmt = (
            select(SchemeEnrollment)
            .where(SchemeEnrollment.id == enrollment_id, SchemeEnrollment.tenant_id == tenant_id)
            .with_for_update()
        )
        return (await db.execute(stmt)).scalar_one_or_none()


class SchemeRedemptionRepository:
    """Append-only. No update or delete counterpart by design."""

    @staticmethod
    async def create(db: AsyncSession, row: SchemeRedemption) -> SchemeRedemption:
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def sum_restorations_for_sale(db: AsyncSession, sale_id: str, tenant_id: str) -> float:
        """Scheme credit restored to enrollments by returning ONE sale, as a
        POSITIVE figure. Restoration rows are the negative reversal rows written
        during return processing, carrying that sale's sale_id; scoping to
        sale_id + tenant_id means later or unrelated redemptions (different
        sale_id) can never be included."""
        stmt = select(func.coalesce(func.sum(SchemeRedemption.amount), 0.0)).where(
            SchemeRedemption.sale_id == sale_id,
            SchemeRedemption.tenant_id == tenant_id,
            SchemeRedemption.amount < 0,
        )
        return -float((await db.execute(stmt)).scalar_one())

    @staticmethod
    async def list_for_customer(db: AsyncSession, customer_id: str, tenant_id: str):
        """Every redemption row belonging to this customer across all of their
        enrollments, newest first — one query instead of one per enrollment.
        Negative amounts are restorations written by a sale return."""
        stmt = (
            select(SchemeRedemption)
            .where(
                SchemeRedemption.customer_id == customer_id,
                SchemeRedemption.tenant_id == tenant_id,
            )
            .order_by(SchemeRedemption.redeemed_at.desc())
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def sum_for_enrollment(db: AsyncSession, enrollment_id: str, tenant_id: str) -> float:
        """Total scheme credit already spent against jewellery sales."""
        stmt = select(func.coalesce(func.sum(SchemeRedemption.amount), 0.0)).where(
            SchemeRedemption.enrollment_id == enrollment_id,
            SchemeRedemption.tenant_id == tenant_id,
        )
        return float((await db.execute(stmt)).scalar_one())

    @staticmethod
    async def list_for_enrollment(db: AsyncSession, enrollment_id: str, tenant_id: str):
        stmt = (
            select(SchemeRedemption)
            .where(
                SchemeRedemption.enrollment_id == enrollment_id,
                SchemeRedemption.tenant_id == tenant_id,
            )
            .order_by(SchemeRedemption.redeemed_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def sum_successful_contributions(
        db: AsyncSession, enrollment_id: str, tenant_id: str
    ) -> float:
        """Eligible balance numerator: SUM of SUCCESSFUL scheme contributions.

        No bonus is applied — Scheme.bonus_description is free text and there is
        no numeric bonus engine in the product, so inventing one here would
        fabricate money. Failed/pending contributions are excluded."""
        stmt = select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
            Payment.enrollment_id == enrollment_id,
            Payment.tenant_id == tenant_id,
            Payment.payment_status == PAYMENT_STATUS_SUCCESS,
        )
        return float((await db.execute(stmt)).scalar_one())

    @staticmethod
    async def count_successful_contributions(
        db: AsyncSession, enrollment_id: str, tenant_id: str
    ) -> int:
        """How many monthly contributions actually succeeded — shown to the Admin
        beside the balance, never used to compute money."""
        stmt = select(func.count(Payment.id)).where(
            Payment.enrollment_id == enrollment_id,
            Payment.tenant_id == tenant_id,
            Payment.payment_status == PAYMENT_STATUS_SUCCESS,
        )
        return int((await db.execute(stmt)).scalar_one())
