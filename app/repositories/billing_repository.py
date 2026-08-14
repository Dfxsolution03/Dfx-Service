from datetime import date, datetime
from typing import List, Optional, Tuple
from sqlalchemy import select, update, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import (
    Vendor,
    CategoryPricingDefault,
    TenantBillingDefaults,
    InventoryItem,
    Sale,
    SalePayment,
)


class CategoryDefaultRepository:
    @staticmethod
    async def get_by_category(
        db: AsyncSession, tenant_id: str, category: str
    ) -> Optional[CategoryPricingDefault]:
        stmt = select(CategoryPricingDefault).where(
            CategoryPricingDefault.tenant_id == tenant_id, CategoryPricingDefault.category == category
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(db: AsyncSession, tenant_id: str) -> List[CategoryPricingDefault]:
        stmt = (
            select(CategoryPricingDefault)
            .where(CategoryPricingDefault.tenant_id == tenant_id)
            .order_by(CategoryPricingDefault.category)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def create(db: AsyncSession, row: CategoryPricingDefault) -> CategoryPricingDefault:
        db.add(row)
        return row


class TenantBillingDefaultsRepository:
    @staticmethod
    async def get_by_tenant(db: AsyncSession, tenant_id: str) -> Optional[TenantBillingDefaults]:
        stmt = select(TenantBillingDefaults).where(TenantBillingDefaults.tenant_id == tenant_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, row: TenantBillingDefaults) -> TenantBillingDefaults:
        db.add(row)
        return row


class VendorRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, vendor_id: str, tenant_id: str) -> Optional[Vendor]:
        stmt = select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(
        db: AsyncSession, tenant_id: str, search: Optional[str] = None, active_only: bool = False
    ) -> List[Vendor]:
        conditions = [Vendor.tenant_id == tenant_id]
        if active_only:
            conditions.append(Vendor.is_active == True)  # noqa: E712
        if search:
            conditions.append(Vendor.name.ilike(f"%{search}%"))
        stmt = select(Vendor).where(*conditions).order_by(Vendor.name)
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def create(db: AsyncSession, vendor: Vendor) -> Vendor:
        db.add(vendor)
        return vendor


class InventoryRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, item_id: str, tenant_id: str) -> Optional[InventoryItem]:
        stmt = select(InventoryItem).where(
            InventoryItem.id == item_id, InventoryItem.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_product_code(
        db: AsyncSession, product_code: str, tenant_id: str
    ) -> Optional[InventoryItem]:
        stmt = select(InventoryItem).where(
            InventoryItem.product_code == product_code, InventoryItem.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(
        db: AsyncSession,
        tenant_id: str,
        page: int,
        limit: int,
        search: Optional[str] = None,
        stock_status: Optional[str] = None,
        category: Optional[str] = None,
        vendor_id: Optional[str] = None,
    ) -> Tuple[List[InventoryItem], int]:
        conditions = [InventoryItem.tenant_id == tenant_id]
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(InventoryItem.product_code.ilike(like), InventoryItem.product_name.ilike(like))
            )
        if stock_status:
            conditions.append(InventoryItem.stock_status == stock_status)
        if category:
            conditions.append(InventoryItem.category == category)
        if vendor_id:
            conditions.append(InventoryItem.vendor_id == vendor_id)

        count_stmt = select(func.count(InventoryItem.id))
        list_stmt = select(InventoryItem)
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        list_stmt = (
            list_stmt.order_by(InventoryItem.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), total

    @staticmethod
    async def create(db: AsyncSession, item: InventoryItem) -> InventoryItem:
        db.add(item)
        return item

    @staticmethod
    async def mark_sold_if_in_stock(db: AsyncSession, item_id: str, tenant_id: str) -> bool:
        """Atomically flips IN_STOCK -> SOLD, guarded in the same UPDATE
        statement so two concurrent sales of the same item can't both
        succeed — whichever commits first wins, the loser's rowcount is 0.
        Returns True iff this call was the one that made the transition."""
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item_id,
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.stock_status == "IN_STOCK",
            )
            .values(stock_status="SOLD")
        )
        result = await db.execute(stmt)
        return result.rowcount == 1


class SaleRepository:
    @staticmethod
    async def create(db: AsyncSession, sale: Sale) -> Sale:
        db.add(sale)
        return sale

    @staticmethod
    async def get_by_id(db: AsyncSession, sale_id: str, tenant_id: str) -> Optional[Sale]:
        stmt = select(Sale).where(Sale.id == sale_id, Sale.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_invoice_number(
        db: AsyncSession, invoice_number: str, tenant_id: str
    ) -> Optional[Sale]:
        stmt = select(Sale).where(Sale.invoice_number == invoice_number, Sale.tenant_id == tenant_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(
        db: AsyncSession,
        tenant_id: str,
        page: int,
        limit: int,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        payment_status: Optional[str] = None,
    ) -> Tuple[List[Sale], int]:
        conditions = [Sale.tenant_id == tenant_id]
        if payment_status:
            conditions.append(Sale.payment_status == payment_status)
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    Sale.invoice_number.ilike(like),
                    Sale.product_code.ilike(like),
                    Sale.customer_name.ilike(like),
                )
            )
        if date_from:
            conditions.append(Sale.sale_timestamp >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            conditions.append(Sale.sale_timestamp <= datetime.combine(date_to, datetime.max.time()))

        count_stmt = select(func.count(Sale.id))
        list_stmt = select(Sale)
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        list_stmt = (
            list_stmt.order_by(Sale.sale_timestamp.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), total

    @staticmethod
    async def get_period_summary(db: AsyncSession, tenant_id: str, start_dt: datetime, end_dt: datetime) -> dict:
        """Aggregates directly off the immutable Sale snapshot rows — never
        touches InventoryItem or the live gold rate, so this can never drift
        from what was actually recorded at sale time.

        Margin is re-derived here from the frozen snapshot columns
        (final_amount / tax_rate_percent / gst_applied / purchase_cost_snapshot)
        rather than read from the stored estimated_gross_margin, because rows
        written before the profit definition was corrected hold a margin that
        ignored a negotiated customer_price. Same formula as
        BillingCalculationEngine.realized_profit_or_loss — no historical row
        is rewritten, the arithmetic just always matches today's definition.
        """
        net_revenue = case(
            (Sale.gst_applied.is_(True), Sale.final_amount / (1 + Sale.tax_rate_percent / 100.0)),
            else_=Sale.final_amount,
        )
        margin = case(
            (Sale.purchase_cost_snapshot.is_(None), 0.0),
            else_=net_revenue - Sale.purchase_cost_snapshot,
        )
        stmt = select(
            func.coalesce(func.sum(Sale.final_amount), 0.0),
            func.coalesce(func.sum(case((margin > 0, margin), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((margin < 0, -margin), else_=0.0)), 0.0),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.tax_amount), 0.0),
        ).where(Sale.tenant_id == tenant_id, Sale.sale_timestamp >= start_dt, Sale.sale_timestamp <= end_dt)
        total_sales, total_profit, total_loss, bill_count, total_tax = (await db.execute(stmt)).one()
        return {
            "total_sales": float(total_sales),
            "total_profit": float(total_profit),
            "total_loss": float(total_loss),
            "bill_count": int(bill_count),
            "items_sold": int(bill_count),  # one item per sale in this data model
            "total_tax": float(total_tax),
            "avg_bill_value": float(total_sales) / bill_count if bill_count else 0.0,
        }

    @staticmethod
    async def get_recent(db: AsyncSession, tenant_id: str, limit: int = 5) -> List[Sale]:
        stmt = (
            select(Sale)
            .where(Sale.tenant_id == tenant_id)
            .order_by(Sale.sale_timestamp.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def get_by_id_for_update(db: AsyncSession, sale_id: str, tenant_id: str) -> Optional[Sale]:
        """Tenant-scoped fetch that holds a row lock for the rest of the
        transaction. Used only by the payment-recording path: two Admins
        collecting against the same invoice at the same moment must serialise
        here, or both could pass the "amount <= outstanding" check against the
        same stale outstanding figure and together collect more than the
        invoice total."""
        stmt = (
            select(Sale)
            .where(Sale.id == sale_id, Sale.tenant_id == tenant_id)
            .with_for_update()
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_all_filtered(
        db: AsyncSession,
        tenant_id: str,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        payment_status: Optional[str] = None,
        cap: int = 20000,
    ) -> List[Sale]:
        """Unpaginated, same filter semantics as list_by_tenant — used by the
        Sales History export so the downloaded file matches exactly what the
        Admin has filtered on screen. `cap` is a memory backstop, not a
        business limit; the caller reports when it is hit rather than silently
        truncating (see SaleService.export_sales_history)."""
        conditions = [Sale.tenant_id == tenant_id]
        if payment_status:
            conditions.append(Sale.payment_status == payment_status)
        if search:
            like = f"%{search}%"
            conditions.append(
                or_(
                    Sale.invoice_number.ilike(like),
                    Sale.product_code.ilike(like),
                    Sale.customer_name.ilike(like),
                )
            )
        if date_from:
            conditions.append(Sale.sale_timestamp >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            conditions.append(Sale.sale_timestamp <= datetime.combine(date_to, datetime.max.time()))

        stmt = select(Sale)
        for cond in conditions:
            stmt = stmt.where(cond)
        stmt = stmt.order_by(Sale.sale_timestamp.desc()).limit(cap)
        return list((await db.execute(stmt)).scalars().all())


class SalePaymentRepository:
    """Append-only ledger access. There is deliberately no update() or
    delete() here — a recorded collection is permanent financial history."""

    @staticmethod
    async def create(db: AsyncSession, payment: SalePayment) -> SalePayment:
        db.add(payment)
        return payment

    @staticmethod
    async def list_by_sale(db: AsyncSession, sale_id: str, tenant_id: str) -> List[SalePayment]:
        stmt = (
            select(SalePayment)
            .where(SalePayment.sale_id == sale_id, SalePayment.tenant_id == tenant_id)
            .order_by(SalePayment.payment_date.asc(), SalePayment.created_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def sum_for_sale(db: AsyncSession, sale_id: str, tenant_id: str) -> float:
        """Authoritative amount-paid figure, read straight off the ledger —
        never off Sale.amount_paid, which is only a cache of this."""
        stmt = select(func.coalesce(func.sum(SalePayment.amount), 0.0)).where(
            SalePayment.sale_id == sale_id, SalePayment.tenant_id == tenant_id
        )
        return float((await db.execute(stmt)).scalar_one())

    @staticmethod
    async def list_by_sale_ids(
        db: AsyncSession, sale_ids: List[str], tenant_id: str
    ) -> List[SalePayment]:
        """Batch fetch for the export, so building N rows does not issue N
        ledger queries."""
        if not sale_ids:
            return []
        stmt = (
            select(SalePayment)
            .where(SalePayment.sale_id.in_(sale_ids), SalePayment.tenant_id == tenant_id)
            .order_by(SalePayment.payment_date.asc(), SalePayment.created_at.asc())
        )
        return list((await db.execute(stmt)).scalars().all())
