from datetime import date, datetime
from typing import List, Optional, Tuple
from sqlalchemy import select, update, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import SALE_STATUS_COMPLETED, INSPECTION_PENDING
from app.models.billing import (
    PAYMENT_SOURCE_SCHEME_REDEMPTION,
    Vendor,
    CategoryPricingDefault,
    TenantBillingDefaults,
    InventoryItem,
    Sale,
    SalePayment,
    SaleReturn,
    PAYMENT_SOURCE_REFUND,
    BillDraft,
    BILL_DRAFT_OPEN,
    Quotation,
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
    ) -> Tuple[List[InventoryItem], int, float]:
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
        sum_stmt = select(func.coalesce(func.sum(InventoryItem.net_gold_weight_grams), 0.0))
        list_stmt = select(InventoryItem)
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            sum_stmt = sum_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        total_gold_weight_grams = float((await db.execute(sum_stmt)).scalar_one())
        list_stmt = (
            list_stmt.order_by(InventoryItem.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), total, total_gold_weight_grams

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

    @staticmethod
    async def transition_stock_status(
        db: AsyncSession, item_id: str, tenant_id: str, expected_from: str, to_status: str
    ) -> bool:
        """Guarded status transition in a single UPDATE, same concurrency
        contract as mark_sold_if_in_stock: the expected current status is part
        of the WHERE clause, so two callers cannot both believe they made the
        move. Returns True iff this call performed the transition.

        Used for SOLD -> RETURNED_PENDING_INSPECTION (return accepted) and
        RETURNED_PENDING_INSPECTION -> IN_STOCK / DAMAGED (inspection decided)."""
        stmt = (
            update(InventoryItem)
            .where(
                InventoryItem.id == item_id,
                InventoryItem.tenant_id == tenant_id,
                InventoryItem.stock_status == expected_from,
            )
            .values(stock_status=to_status)
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
        # Eager-load the linked inventory item so the response builder can read
        # its category/subcategory without an async lazy-load (MissingGreenlet).
        stmt = (
            select(Sale)
            .options(selectinload(Sale.inventory_item))
            .where(Sale.id == sale_id, Sale.tenant_id == tenant_id)
        )
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
        sale_status: Optional[str] = None,
        customer_id: Optional[str] = None,
        product_code: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Tuple[List[Sale], int, float]:
        conditions = [Sale.tenant_id == tenant_id]
        if payment_status:
            conditions.append(Sale.payment_status == payment_status)
        if sale_status:
            conditions.append(Sale.sale_status == sale_status)
        # Phase 5 — sales-history filters: exact customer, exact product code, and
        # product category. Sale has no category column, so category resolves
        # through the linked inventory item (tenant-scoped subquery — no join
        # fan-out, so the COUNT stays correct).
        if customer_id:
            conditions.append(Sale.customer_id == customer_id)
        if product_code:
            conditions.append(Sale.product_code == product_code)
        if category:
            conditions.append(
                Sale.inventory_item_id.in_(
                    select(InventoryItem.id).where(
                        InventoryItem.tenant_id == tenant_id,
                        func.lower(InventoryItem.category) == category.lower(),
                    )
                )
            )
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
        sum_stmt = select(func.coalesce(func.sum(Sale.net_gold_weight_grams), 0.0))
        # Outstanding is always final_amount - amount_paid; aggregate it across
        # the whole filtered set (not just the page) for the dashboard KPI.
        outstanding_stmt = select(func.coalesce(func.sum(Sale.final_amount - Sale.amount_paid), 0.0))
        # Eager-load inventory_item so _build_response can read its
        # category/subcategory without an async lazy-load (MissingGreenlet).
        list_stmt = select(Sale).options(selectinload(Sale.inventory_item))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
            sum_stmt = sum_stmt.where(cond)
            outstanding_stmt = outstanding_stmt.where(cond)
            list_stmt = list_stmt.where(cond)

        total = int((await db.execute(count_stmt)).scalar_one())
        total_gold_weight_grams = float((await db.execute(sum_stmt)).scalar_one())
        total_outstanding = float((await db.execute(outstanding_stmt)).scalar_one())
        list_stmt = (
            list_stmt.order_by(Sale.sale_timestamp.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        rows = (await db.execute(list_stmt)).scalars().all()
        return list(rows), total, total_gold_weight_grams, total_outstanding

    @staticmethod
    async def list_by_customer(
        db: AsyncSession, tenant_id: str, customer_id: str, limit: int = 200
    ) -> List[Sale]:
        """Every sale billed to this customer, newest first — the purchase side
        of Customer 360. Read-only; the sale rows are returned exactly as the
        billing module wrote them, including their derived amount_paid /
        payment_status / sale_status caches."""
        stmt = (
            select(Sale)
            .where(Sale.tenant_id == tenant_id, Sale.customer_id == customer_id)
            .order_by(Sale.sale_timestamp.desc())
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())

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
        # Phase A current-gold-value profit: net selling value minus the FROZEN
        # gold value recorded at sale time (Sale.gold_value_amount) — never
        # re-derived from today's rate. Signed aggregate over intact sales only.
        current_gold_pl = net_revenue - Sale.gold_value_amount
        # A reversed sale is excluded from every NET figure (net sales, profit,
        # loss, tax, bill count, items sold) but is still reported on its own as
        # gross + returns, so the period reconciles as
        # gross_sales - sales_returns = total_sales and nothing is silently
        # deleted from history. The Sale row itself is never touched.
        intact = Sale.sale_status == SALE_STATUS_COMPLETED
        reversed_ = Sale.sale_status != SALE_STATUS_COMPLETED
        stmt = select(
            func.coalesce(func.sum(case((intact, Sale.final_amount), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((intact & (margin > 0), margin), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((intact & (margin < 0), -margin), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((intact, 1), else_=0)), 0),
            func.coalesce(func.sum(case((intact, Sale.tax_amount), else_=0.0)), 0.0),
            func.coalesce(func.sum(Sale.final_amount), 0.0),
            func.coalesce(func.sum(case((reversed_, Sale.final_amount), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((reversed_, 1), else_=0)), 0),
            func.coalesce(func.sum(Sale.amount_refunded), 0.0),
            func.coalesce(func.sum(case((intact, current_gold_pl), else_=0.0)), 0.0),
        ).where(Sale.tenant_id == tenant_id, Sale.sale_timestamp >= start_dt, Sale.sale_timestamp <= end_dt)
        (
            total_sales, total_profit, total_loss, bill_count, total_tax,
            gross_sales, sales_returns, return_count, total_refunded,
            current_gold_pl_total,
        ) = (await db.execute(stmt)).one()
        return {
            "total_sales": float(total_sales),
            "total_profit": float(total_profit),
            "total_loss": float(total_loss),
            "bill_count": int(bill_count),
            "items_sold": int(bill_count),  # one item per sale in this data model
            "total_tax": float(total_tax),
            "avg_bill_value": float(total_sales) / bill_count if bill_count else 0.0,
            "gross_sales": float(gross_sales),
            "sales_returns": float(sales_returns),
            "return_count": int(return_count),
            "total_refunded": float(total_refunded),
            "current_gold_value_profit_or_loss": float(current_gold_pl_total),
        }

    @staticmethod
    async def get_collections_summary(
        db: AsyncSession, tenant_id: str, start_dt: datetime, end_dt: datetime
    ) -> dict:
        """Money-movement aggregation off the SalePayment ledger by PAYMENT_DATE
        (the collection event date), NOT the sale date — so a payment collected
        the day after the sale counts on the day it was taken.

        Three distinct concepts, never merged:
          - cash_collected: real positive customer collections (any source that
            is neither a refund nor a scheme settlement). This is actual money in.
          - scheme_redemption: SCHEME_REDEMPTION settlements. Settles an invoice
            but is customer scheme credit, never cash — reported separately.
          - refunds: REFUND rows (stored negative) returned as a positive figure.
        Tenant-scoped. payment_date is a Date column; the caller passes a
        [date, date] range via the shared period resolver.
        """
        from datetime import date as _date
        start_d = start_dt.date() if hasattr(start_dt, "date") else start_dt
        end_d = end_dt.date() if hasattr(end_dt, "date") else end_dt
        is_refund = SalePayment.source == PAYMENT_SOURCE_REFUND
        is_scheme = SalePayment.source == PAYMENT_SOURCE_SCHEME_REDEMPTION
        stmt = select(
            func.coalesce(func.sum(case((~is_refund & ~is_scheme, SalePayment.amount), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((is_scheme, SalePayment.amount), else_=0.0)), 0.0),
            func.coalesce(func.sum(case((is_refund, SalePayment.amount), else_=0.0)), 0.0),
        ).where(
            SalePayment.tenant_id == tenant_id,
            SalePayment.payment_date >= start_d,
            SalePayment.payment_date <= end_d,
        )
        cash, scheme, refunds = (await db.execute(stmt)).one()

        # Per-method split of the SAME cash_collected figure — one extra grouped
        # query, same WHERE clause and the same "neither refund nor scheme"
        # filter, so the parts always sum to cash_collected and a scheme
        # settlement can never be double-counted as CASH/UPI/CARD money in.
        method_stmt = (
            select(SalePayment.payment_method, func.coalesce(func.sum(SalePayment.amount), 0.0))
            .where(
                SalePayment.tenant_id == tenant_id,
                SalePayment.payment_date >= start_d,
                SalePayment.payment_date <= end_d,
                ~is_refund,
                ~is_scheme,
            )
            .group_by(SalePayment.payment_method)
        )
        by_method = {
            str(method): float(total)
            for method, total in (await db.execute(method_stmt)).all()
            if method is not None
        }

        return {
            "cash_collected": float(cash),
            "scheme_redemption": float(scheme),
            "refunds": float(-refunds),  # stored negative; report positive
            "collected_by_method": by_method,
        }

    @staticmethod
    async def get_receivables_summary(
        db: AsyncSession, tenant_id: str, start_dt: datetime, end_dt: datetime
    ) -> dict:
        """Receivables aggregation off the Sale snapshot columns, which are the
        transactionally-synced projection of the SalePayment ledger
        (amount_paid/payment_status are recomputed on every ledger write, see
        SalePaymentService.record_payment). No new payment math is introduced.

        Only intact sales (sale_status == COMPLETED) are active receivables: a
        returned/cancelled sale had its balance written off, so counting its
        outstanding would overstate what customers still owe.
        """
        paid = func.coalesce(Sale.amount_paid, 0.0)
        outstanding = case((Sale.final_amount - paid > 0, Sale.final_amount - paid), else_=0.0)
        stmt = select(
            func.coalesce(func.sum(Sale.final_amount), 0.0),
            func.coalesce(func.sum(paid), 0.0),
            func.coalesce(func.sum(outstanding), 0.0),
            func.coalesce(func.sum(case((Sale.payment_status == "PAID", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Sale.payment_status == "PARTIAL", 1), else_=0)), 0),
            func.coalesce(func.sum(case((Sale.payment_status == "PENDING", 1), else_=0)), 0),
            func.count(Sale.id),
        ).where(
            Sale.tenant_id == tenant_id,
            Sale.sale_status == SALE_STATUS_COMPLETED,
            Sale.sale_timestamp >= start_dt,
            Sale.sale_timestamp <= end_dt,
        )
        (invoiced, total_paid, total_outstanding, paid_c, partial_c, pending_c, cnt) = (
            await db.execute(stmt)
        ).one()
        return {
            "total_invoiced": float(invoiced),
            "total_paid": float(total_paid),
            "total_outstanding": float(total_outstanding),
            "paid_count": int(paid_c),
            "partial_count": int(partial_c),
            "pending_count": int(pending_c),
            "sale_count": int(cnt),
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
        sale_status: Optional[str] = None,
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
        if sale_status:
            conditions.append(Sale.sale_status == sale_status)
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
        """Total COLLECTED against one invoice. Refund rows (source=REFUND, stored
        negative) are deliberately excluded: "collected" and "refunded" are two
        separate figures on the invoice, and netting them here would understate
        what was actually taken at the counter and silently reopen an
        outstanding balance on a refunded sale. See sum_refunds_for_sale."""
        stmt = select(func.coalesce(func.sum(SalePayment.amount), 0.0)).where(
            SalePayment.sale_id == sale_id,
            SalePayment.tenant_id == tenant_id,
            SalePayment.source != PAYMENT_SOURCE_REFUND,
        )
        return float((await db.execute(stmt)).scalar_one())

    @staticmethod
    async def scheme_redemption_rows_for_sale(db: AsyncSession, sale_id: str, tenant_id: str):
        """The SCHEME_REDEMPTION ledger rows that settled one sale, carrying the
        funding enrollment_id. Used by the return path to restore scheme credit
        rather than refunding it as cash."""
        stmt = select(SalePayment).where(
            SalePayment.sale_id == sale_id,
            SalePayment.tenant_id == tenant_id,
            SalePayment.source == PAYMENT_SOURCE_SCHEME_REDEMPTION,
        )
        return list((await db.execute(stmt)).scalars().all())

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

    @staticmethod
    async def sum_refunds_for_sale(db: AsyncSession, sale_id: str, tenant_id: str) -> float:
        """Total refunded against one invoice, as a POSITIVE figure. Refund rows
        are stored negative on the shared ledger, so this negates the sum."""
        stmt = select(func.coalesce(func.sum(SalePayment.amount), 0.0)).where(
            SalePayment.sale_id == sale_id,
            SalePayment.tenant_id == tenant_id,
            SalePayment.source == PAYMENT_SOURCE_REFUND,
        )
        return -float((await db.execute(stmt)).scalar_one())


class SaleReturnRepository:
    @staticmethod
    async def create(db: AsyncSession, row: SaleReturn) -> SaleReturn:
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def get_by_sale(db: AsyncSession, sale_id: str, tenant_id: str) -> Optional[SaleReturn]:
        stmt = select(SaleReturn).where(
            SaleReturn.sale_id == sale_id, SaleReturn.tenant_id == tenant_id
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_pending_by_inventory_item(
        db: AsyncSession, inventory_item_id: str, tenant_id: str
    ) -> Optional[SaleReturn]:
        """The return still awaiting inspection for one inventory item, tenant
        scoped. An item can be returned, restocked and returned again over its
        life, so only the PENDING one is the active inspection target."""
        stmt = select(SaleReturn).where(
            SaleReturn.inventory_item_id == inventory_item_id,
            SaleReturn.tenant_id == tenant_id,
            SaleReturn.inspection_status == INSPECTION_PENDING,
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_by_sale_for_update(db: AsyncSession, sale_id: str, tenant_id: str) -> Optional[SaleReturn]:
        stmt = (
            select(SaleReturn)
            .where(SaleReturn.sale_id == sale_id, SaleReturn.tenant_id == tenant_id)
            .with_for_update()
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_by_sale_ids(db: AsyncSession, sale_ids: List[str], tenant_id: str) -> List[SaleReturn]:
        if not sale_ids:
            return []
        stmt = select(SaleReturn).where(
            SaleReturn.sale_id.in_(sale_ids), SaleReturn.tenant_id == tenant_id
        )
        return list((await db.execute(stmt)).scalars().all())


class BillDraftRepository:
    """Data access for unfinished bills. Every read is tenant-scoped; an
    optional owner_id further restricts to a single creator (Staff visibility).
    Kept intentionally thin — all business rules live in BillDraftService."""

    @staticmethod
    async def create(db: AsyncSession, draft: BillDraft) -> BillDraft:
        db.add(draft)
        await db.flush()
        return draft

    @staticmethod
    async def get_by_id(
        db: AsyncSession, draft_id: str, tenant_id: str, owner_id: Optional[str] = None
    ) -> Optional[BillDraft]:
        stmt = select(BillDraft).where(
            BillDraft.id == draft_id, BillDraft.tenant_id == tenant_id
        )
        if owner_id is not None:
            stmt = stmt.where(BillDraft.created_by == owner_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def get_by_id_for_update(
        db: AsyncSession, draft_id: str, tenant_id: str, owner_id: Optional[str] = None
    ) -> Optional[BillDraft]:
        stmt = (
            select(BillDraft)
            .where(BillDraft.id == draft_id, BillDraft.tenant_id == tenant_id)
            .with_for_update()
        )
        if owner_id is not None:
            stmt = stmt.where(BillDraft.created_by == owner_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_drafts(
        db: AsyncSession,
        tenant_id: str,
        owner_id: Optional[str] = None,
        status: Optional[str] = None,
        product_code: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> List[BillDraft]:
        stmt = select(BillDraft).where(BillDraft.tenant_id == tenant_id)
        if owner_id is not None:
            stmt = stmt.where(BillDraft.created_by == owner_id)
        # Default view is OPEN drafts only; an explicit status can widen it.
        stmt = stmt.where(BillDraft.status == (status or BILL_DRAFT_OPEN))
        if product_code is not None:
            stmt = stmt.where(BillDraft.product_code == product_code)
        if customer_id is not None:
            stmt = stmt.where(BillDraft.customer_id == customer_id)
        stmt = stmt.order_by(BillDraft.updated_at.desc())
        return list((await db.execute(stmt)).scalars().all())


class QuotationRepository:
    """Phase 4 — persistence for quotations. Every read is tenant-scoped."""

    @staticmethod
    async def create(db: AsyncSession, row: Quotation) -> Quotation:
        db.add(row)
        return row

    @staticmethod
    async def get_by_id(db: AsyncSession, quotation_id: str, tenant_id: str) -> Optional[Quotation]:
        stmt = select(Quotation).where(
            Quotation.id == quotation_id, Quotation.tenant_id == tenant_id
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_by_tenant(
        db: AsyncSession, tenant_id: str, customer_id: Optional[str] = None
    ) -> List[Quotation]:
        stmt = select(Quotation).where(Quotation.tenant_id == tenant_id)
        if customer_id is not None:
            stmt = stmt.where(Quotation.customer_id == customer_id)
        stmt = stmt.order_by(Quotation.created_at.desc())
        return list((await db.execute(stmt)).scalars().all())
