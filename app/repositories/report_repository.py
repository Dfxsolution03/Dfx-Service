from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment, STATUS_SUCCESS, STATUS_PENDING
from app.models.enrollment import SchemeEnrollment, STATUS_ACTIVE, STATUS_COMPLETED, STATUS_CANCELLED
from app.models.scheme import Scheme
from app.models.goldrate import GoldRate
from app.models.passbook import PassbookEntry
from app.models.auth import User, Role
from app.core.constants import ROLE_CUSTOMER


class ReportRepository:
    """
    Centralized aggregation queries for the Reports/Analytics module (Module 12).
    Every method is tenant-scoped, thin (no business calculations — that lives
    in ReportService), and reusable across multiple frontend pages/future
    modules — report-specific SQL should live here rather than being
    duplicated per-endpoint or per-chart.
    """

    # ─── Payments ───

    @staticmethod
    async def get_payment_totals(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date
    ) -> dict:
        stmt = select(
            func.coalesce(
                func.sum(case((Payment.payment_status == STATUS_SUCCESS, Payment.amount), else_=0.0)), 0.0
            ).label("success_amount"),
            func.count(case((Payment.payment_status == STATUS_SUCCESS, 1))).label("success_count"),
            func.coalesce(
                func.sum(case((Payment.payment_status == STATUS_PENDING, Payment.amount), else_=0.0)), 0.0
            ).label("pending_amount"),
            func.count(case((Payment.payment_status == STATUS_PENDING, 1))).label("pending_count"),
        ).where(
            Payment.tenant_id == tenant_id,
            Payment.payment_date >= date_from,
            Payment.payment_date <= date_to,
        )
        row = (await db.execute(stmt)).one()
        return {
            "success_amount": float(row.success_amount),
            "success_count": int(row.success_count),
            "pending_amount": float(row.pending_amount),
            "pending_count": int(row.pending_count),
        }

    @staticmethod
    async def get_payment_trend(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date, group_by_month: bool
    ) -> List[dict]:
        bucket = func.date_trunc("month", Payment.payment_date) if group_by_month else Payment.payment_date
        stmt = (
            select(
                bucket.label("bucket"),
                func.coalesce(
                    func.sum(case((Payment.payment_status == STATUS_SUCCESS, Payment.amount), else_=0.0)), 0.0
                ).label("total_amount"),
                func.count(case((Payment.payment_status == STATUS_SUCCESS, 1))).label("payment_count"),
            )
            .where(
                Payment.tenant_id == tenant_id,
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {"bucket": row.bucket, "total_amount": float(row.total_amount), "payment_count": int(row.payment_count)}
            for row in rows
        ]

    @staticmethod
    async def get_top_enrollments_by_investment(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date, limit: int
    ) -> List[dict]:
        """Ranks scheme enrollments (not raw customers) by SUCCESS payment total
        within the range — avoids ambiguity when one customer holds multiple
        enrollments, and matches the granularity PassbookEntry is keyed on."""
        stmt = (
            select(
                SchemeEnrollment.id.label("enrollment_id"),
                SchemeEnrollment.customer_id.label("customer_id"),
                SchemeEnrollment.status.label("enrollment_status"),
                User.name.label("customer_name"),
                Scheme.name.label("scheme_name"),
                func.sum(Payment.amount).label("total_invested"),
            )
            .join(Payment, Payment.enrollment_id == SchemeEnrollment.id)
            .join(User, User.id == SchemeEnrollment.customer_id)
            .join(Scheme, Scheme.id == SchemeEnrollment.scheme_id)
            .where(
                SchemeEnrollment.tenant_id == tenant_id,
                Payment.payment_status == STATUS_SUCCESS,
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
            .group_by(SchemeEnrollment.id, SchemeEnrollment.customer_id, SchemeEnrollment.status, User.name, Scheme.name)
            .order_by(func.sum(Payment.amount).desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        if not rows:
            return []

        enrollment_ids = [row.enrollment_id for row in rows]
        gold_stmt = (
            select(
                PassbookEntry.enrollment_id,
                func.coalesce(func.sum(PassbookEntry.gold_weight), 0.0).label("gold_weight"),
            )
            .where(PassbookEntry.enrollment_id.in_(enrollment_ids))
            .group_by(PassbookEntry.enrollment_id)
        )
        gold_rows = (await db.execute(gold_stmt)).all()
        gold_by_enrollment = {r.enrollment_id: float(r.gold_weight) for r in gold_rows}

        return [
            {
                "enrollment_id": row.enrollment_id,
                "customer_id": row.customer_id,
                "customer_name": row.customer_name,
                "scheme_name": row.scheme_name,
                "enrollment_status": row.enrollment_status,
                "total_invested": float(row.total_invested),
                "gold_weight_grams": gold_by_enrollment.get(row.enrollment_id, 0.0),
            }
            for row in rows
        ]

    # ─── Enrollments ───

    @staticmethod
    async def get_enrollment_status_counts(db: AsyncSession, tenant_id: str) -> dict:
        """Current-state snapshot (not date-range scoped) — matches how "Total
        Active Passbooks" reads as a live total, not a period-flow metric."""
        stmt = (
            select(SchemeEnrollment.status, func.count(SchemeEnrollment.id))
            .where(SchemeEnrollment.tenant_id == tenant_id)
            .group_by(SchemeEnrollment.status)
        )
        rows = (await db.execute(stmt)).all()
        counts = {STATUS_ACTIVE: 0, STATUS_COMPLETED: 0, STATUS_CANCELLED: 0}
        for status_val, count in rows:
            counts[status_val] = int(count)
        return counts

    @staticmethod
    async def get_new_enrollment_trend(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date, group_by_month: bool
    ) -> List[dict]:
        bucket = (
            func.date_trunc("month", SchemeEnrollment.joined_date) if group_by_month else SchemeEnrollment.joined_date
        )
        stmt = (
            select(bucket.label("bucket"), func.count(SchemeEnrollment.id).label("new_enrollments"))
            .where(
                SchemeEnrollment.tenant_id == tenant_id,
                SchemeEnrollment.joined_date >= date_from,
                SchemeEnrollment.joined_date <= date_to,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        rows = (await db.execute(stmt)).all()
        return [{"bucket": row.bucket, "new_enrollments": int(row.new_enrollments)} for row in rows]

    # ─── Gold Rate ───

    @staticmethod
    async def get_gold_rate_trend(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date
    ) -> List[dict]:
        stmt = (
            select(GoldRate.effective_date, GoldRate.rate_24k)
            .where(
                GoldRate.tenant_id == tenant_id,
                GoldRate.effective_date >= date_from,
                GoldRate.effective_date <= date_to,
            )
            .order_by(GoldRate.effective_date)
        )
        rows = (await db.execute(stmt)).all()
        return [{"date": row.effective_date, "rate_24k": float(row.rate_24k)} for row in rows]

    # ─── Gold Accumulation ───

    @staticmethod
    async def get_gold_accumulation_total(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date
    ) -> dict:
        stmt = select(
            func.coalesce(func.sum(PassbookEntry.gold_weight), 0.0).label("total_gold_weight"),
            func.count(PassbookEntry.id).label("entry_count"),
        ).where(
            PassbookEntry.tenant_id == tenant_id,
            PassbookEntry.entry_date >= date_from,
            PassbookEntry.entry_date <= date_to,
        )
        row = (await db.execute(stmt)).one()
        return {"total_gold_weight_grams": float(row.total_gold_weight), "entry_count": int(row.entry_count)}

    # ─── Schemes ───

    @staticmethod
    async def get_scheme_summary(
        db: AsyncSession, tenant_id: str, date_from: date, date_to: date
    ) -> List[dict]:
        active_enrollments_subq = (
            select(SchemeEnrollment.scheme_id, func.count(SchemeEnrollment.id).label("active_count"))
            .where(SchemeEnrollment.tenant_id == tenant_id, SchemeEnrollment.status == STATUS_ACTIVE)
            .group_by(SchemeEnrollment.scheme_id)
            .subquery()
        )
        collected_subq = (
            select(
                SchemeEnrollment.scheme_id,
                func.coalesce(func.sum(Payment.amount), 0.0).label("collected"),
            )
            .join(Payment, Payment.enrollment_id == SchemeEnrollment.id)
            .where(
                SchemeEnrollment.tenant_id == tenant_id,
                Payment.payment_status == STATUS_SUCCESS,
                Payment.payment_date >= date_from,
                Payment.payment_date <= date_to,
            )
            .group_by(SchemeEnrollment.scheme_id)
            .subquery()
        )
        stmt = (
            select(
                Scheme.id,
                Scheme.name,
                Scheme.is_active,
                func.coalesce(active_enrollments_subq.c.active_count, 0).label("active_enrollments"),
                func.coalesce(collected_subq.c.collected, 0.0).label("total_collected"),
            )
            .outerjoin(active_enrollments_subq, active_enrollments_subq.c.scheme_id == Scheme.id)
            .outerjoin(collected_subq, collected_subq.c.scheme_id == Scheme.id)
            .where(Scheme.tenant_id == tenant_id)
            .order_by(Scheme.name)
        )
        rows = (await db.execute(stmt)).all()
        return [
            {
                "scheme_id": row.id,
                "scheme_name": row.name,
                "is_active": row.is_active,
                "active_enrollments": int(row.active_enrollments),
                "total_collected": float(row.total_collected),
            }
            for row in rows
        ]

    # ─── Customers ───

    @staticmethod
    async def get_customer_count(
        db: AsyncSession, tenant_id: str, as_of: Optional[datetime] = None
    ) -> int:
        """Count of Customer-role users for a tenant, optionally as of a past
        instant (for period-over-period growth). Generic/reusable — not tied
        to any one report type, usable by a future real Customers list page."""
        stmt = (
            select(func.count(User.id))
            .join(Role, Role.id == User.role_id)
            .where(User.tenant_id == tenant_id, Role.name == ROLE_CUSTOMER)
        )
        if as_of is not None:
            stmt = stmt.where(User.created_at <= as_of)
        result = await db.execute(stmt)
        return int(result.scalar_one())
