"""sale return / cancellation lifecycle

Revision ID: d9f3a7c5b1e8
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17 10:00:00.000000

Sale-level returns and cancellations. Adds:

  - sales.sale_status      COMPLETED | RETURNED | CANCELLED — the SALE
                           lifecycle, kept strictly separate from
                           payment_status so neither concept has to encode the
                           other. Backfilled COMPLETED for every existing row:
                           every sale on record today is an intact sale.
  - sales.amount_refunded  derived cache of the sale's REFUND ledger rows,
                           mirroring how amount_paid caches collections.
                           Backfilled 0 — no refund has ever been recorded.
  - sale_returns           one immutable reversal row per sale, unique on
                           sale_id (the schema-level guard against a double
                           return).

No existing column is altered and no historical financial value is rewritten:
a returned sale keeps its original invoice number, product snapshot, gold rate,
charges, GST, customer price, purchase-cost snapshot and margin exactly as
recorded. Refund money itself goes onto the existing sale_payments ledger as a
negative row with source=REFUND, so no second payment system is introduced and
no collection row is ever mutated.

Inventory gains no new column: stock_status is free text at the DB level and
the two new values (RETURNED_PENDING_INSPECTION, DAMAGED) are enforced in
app.core.constants. Both are non-sellable by construction, because the sale
path only ever accepts IN_STOCK.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9f3a7c5b1e8'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales",
        sa.Column("sale_status", sa.String(length=20), nullable=False, server_default="COMPLETED"),
    )
    op.add_column(
        "sales",
        sa.Column("amount_refunded", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_sales_sale_status", "sales", ["sale_status"])

    op.create_table(
        "sale_returns",
        sa.Column("id", sa.String(length=50), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("sale_id", sa.String(length=50), nullable=False),
        sa.Column("invoice_number", sa.String(length=30), nullable=False),
        sa.Column("inventory_item_id", sa.String(length=50), nullable=False),
        sa.Column("product_code", sa.String(length=50), nullable=False),
        sa.Column("return_type", sa.String(length=20), nullable=False, server_default="RETURN"),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("original_sale_amount", sa.Float(), nullable=False),
        sa.Column("amount_collected_at_return", sa.Float(), nullable=False),
        sa.Column("refund_amount", sa.Float(), nullable=False),
        sa.Column("outstanding_written_off", sa.Float(), nullable=False),
        sa.Column("refund_method", sa.String(length=30), nullable=True),
        sa.Column("refund_reference_no", sa.String(length=100), nullable=True),
        sa.Column("inspection_status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("inspection_notes", sa.String(length=500), nullable=True),
        sa.Column("inspected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspected_by", sa.String(length=50), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inventory_item_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inspected_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processed_by"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sale_id", name="uq_sale_returns_sale_id"),
    )
    op.create_index("ix_sale_returns_tenant_id", "sale_returns", ["tenant_id"])
    op.create_index("ix_sale_returns_sale_id", "sale_returns", ["sale_id"])
    op.create_index("ix_sale_returns_invoice_number", "sale_returns", ["invoice_number"])
    op.create_index("ix_sale_returns_inventory_item_id", "sale_returns", ["inventory_item_id"])


def downgrade() -> None:
    op.drop_index("ix_sale_returns_inventory_item_id", table_name="sale_returns")
    op.drop_index("ix_sale_returns_invoice_number", table_name="sale_returns")
    op.drop_index("ix_sale_returns_sale_id", table_name="sale_returns")
    op.drop_index("ix_sale_returns_tenant_id", table_name="sale_returns")
    op.drop_table("sale_returns")
    op.drop_index("ix_sales_sale_status", table_name="sales")
    op.drop_column("sales", "amount_refunded")
    op.drop_column("sales", "sale_status")
