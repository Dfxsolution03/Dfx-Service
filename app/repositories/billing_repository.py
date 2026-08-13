from datetime import date, datetime
from typing import List, Optional, Tuple
from sqlalchemy import select, update, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Vendor, CategoryPricingDefault, TenantBillingDefaults, InventoryItem, Sale


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
    ) -> Tuple[List[Sale], int]:
        conditions = [Sale.tenant_id == tenant_id]
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
        from what was actually recorded at sale time."""
        margin = Sale.estimated_gross_margin
        stmt = select(
            func.coalesce(func.sum(Sale.final_amount), 0.0),
            func.coalesce(func.sum(case((margin > 0, margin), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((margin < 0, -margin), else_=0.0)), 0.0),
            func.count(Sale.id),
        ).where(Sale.tenant_id == tenant_id, Sale.sale_timestamp >= start_dt, Sale.sale_timestamp <= end_dt)
        total_sales, total_profit, total_loss, bill_count = (await db.execute(stmt)).one()
        return {
            "total_sales": float(total_sales),
            "total_profit": float(total_profit),
            "total_loss": float(total_loss),
            "bill_count": int(bill_count),
            "items_sold": int(bill_count),  # one item per sale in this data model
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
