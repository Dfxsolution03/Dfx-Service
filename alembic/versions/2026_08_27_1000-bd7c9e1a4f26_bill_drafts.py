"""bill_drafts table (server-side unfinished bills)

Revision ID: bd7c9e1a4f26
Revises: f0e1d2c3b4a5
Create Date: 2026-08-27 10:00:00

Additive only: creates the bill_drafts table. No existing table is touched and
no data is backfilled, so every existing row stays valid. Fully reversible.
"""
from alembic import op
import sqlalchemy as sa


revision = "bd7c9e1a4f26"
down_revision = "f0e1d2c3b4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bill_drafts",
        sa.Column("id", sa.String(length=50), primary_key=True),
        sa.Column("tenant_id", sa.String(length=50), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(length=50), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("product_code", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.String(length=50), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_name", sa.String(length=150), nullable=True),
        sa.Column("customer_phone", sa.String(length=20), nullable=True),
        sa.Column("customer_query", sa.String(length=150), nullable=True),
        sa.Column("customer_price", sa.Float(), nullable=True),
        sa.Column("gst_applied", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("making_charge_value", sa.Float(), nullable=True),
        sa.Column("wastage_value", sa.Float(), nullable=True),
        sa.Column("gold_profit_percent", sa.Float(), nullable=True),
        sa.Column("discount_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payment_method", sa.String(length=20), nullable=False, server_default="CASH"),
        sa.Column("payment_status", sa.String(length=20), nullable=False, server_default="PAID"),
        sa.Column("initial_payment", sa.Float(), nullable=True),
        sa.Column("scheme_amounts", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("finalized_sale_id", sa.String(length=50), sa.ForeignKey("sales.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bill_drafts_tenant_id", "bill_drafts", ["tenant_id"])
    op.create_index("ix_bill_drafts_created_by", "bill_drafts", ["created_by"])
    op.create_index("ix_bill_drafts_status", "bill_drafts", ["status"])
    op.create_index("ix_bill_drafts_product_code", "bill_drafts", ["product_code"])


def downgrade() -> None:
    op.drop_index("ix_bill_drafts_product_code", table_name="bill_drafts")
    op.drop_index("ix_bill_drafts_status", table_name="bill_drafts")
    op.drop_index("ix_bill_drafts_created_by", table_name="bill_drafts")
    op.drop_index("ix_bill_drafts_tenant_id", table_name="bill_drafts")
    op.drop_table("bill_drafts")
