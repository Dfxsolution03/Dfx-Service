from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.payment import Payment
from app.models.enrollment import SchemeEnrollment


class PaymentRepository:
    @staticmethod
    def _with_relations(stmt):
        # Payment -> enrollment -> customer/scheme is an unbroken many-to-one
        # chain, so this collapses what was 4 sequential round trips (base
        # query + enrollment batch + customer batch + scheme batch) into a
        # single query with 3 joins — no duplicate-row risk anywhere in the
        # chain since nothing here fans out per payment.
        return stmt.options(
            joinedload(Payment.enrollment).joinedload(SchemeEnrollment.customer),
            joinedload(Payment.enrollment).joinedload(SchemeEnrollment.scheme),
        )

    @staticmethod
    async def get_payments_by_tenant(db: AsyncSession, tenant_id: str) -> List[Payment]:
        stmt = PaymentRepository._with_relations(
            select(Payment)
            .where(Payment.tenant_id == tenant_id)
            .order_by(Payment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_payment_by_id(db: AsyncSession, payment_id: str, tenant_id: str) -> Optional[Payment]:
        stmt = PaymentRepository._with_relations(
            select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_payments_by_customer(db: AsyncSession, tenant_id: str, customer_id: str) -> List[Payment]:
        stmt = PaymentRepository._with_relations(
            select(Payment)
            .join(SchemeEnrollment, Payment.enrollment_id == SchemeEnrollment.id)
            .where(
                Payment.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
            .order_by(Payment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_payment_by_id_for_customer(
        db: AsyncSession, payment_id: str, tenant_id: str, customer_id: str
    ) -> Optional[Payment]:
        stmt = PaymentRepository._with_relations(
            select(Payment)
            .join(SchemeEnrollment, Payment.enrollment_id == SchemeEnrollment.id)
            .where(
                Payment.id == payment_id,
                Payment.tenant_id == tenant_id,
                SchemeEnrollment.customer_id == customer_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_payment(db: AsyncSession, payment: Payment) -> Payment:
        db.add(payment)
        return payment
