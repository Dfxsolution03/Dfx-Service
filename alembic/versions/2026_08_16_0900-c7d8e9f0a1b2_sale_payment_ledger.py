"""sale payment ledger (append-only) and derived sales.amount_paid

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-16 09:00:00.000000

Phase 1 of the payment-status rework. Before this, Sale carried only a
free-text payment_status label with no financial data behind it, so a PARTIAL
sale could not say how much had actually been collected or what remained
outstanding.

Adds sale_payments — one append-only row per collection event against an
invoice — plus a derived sales.amount_paid cache. Deliberately a dedicated
table rather than reusing payments (the scheme-contribution ledger, whose
enrollment_id is NOT NULL); scheme contributions and invoice collections stay
separate financial concepts.

Backfill is intentionally conservative and creates NO synthetic ledger rows:
existing PAID sales get amount_paid = final_amount, everything else gets 0.
A historical PAID invoice therefore shows a correct paid/outstanding figure
with an empty payment history (no fabricated collection date, method, or
collector — inventing those would be false financial data). Every payment
recorded from this point forward is a real ledger row.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sale_payments",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=False),
        sa.Column("sale_id", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="COUNTER"),
        sa.Column("reference_no", sa.String(length=100), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column("recorded_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sale_id"], ["sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sale_payments_tenant_id", "sale_payments", ["tenant_id"])
    op.create_index("ix_sale_payments_sale_id", "sale_payments", ["sale_id"])
    op.create_index("ix_sale_payments_payment_date", "sale_payments", ["payment_date"])

    op.add_column(
        "sales",
        sa.Column("amount_paid", sa.Float(), nullable=False, server_default="0"),
    )
    # Existing fully-paid invoices already carry their collected total in
    # final_amount; PARTIAL/PENDING rows have no recoverable paid figure, so
    # they correctly start at 0 and the Admin records the real collections.
    op.execute("UPDATE sales SET amount_paid = final_amount WHERE payment_status = 'PAID'")
    # Index for the Sales History status tabs added in the same phase.
    op.create_index("ix_sales_payment_status", "sales", ["payment_status"])


def downgrade() -> None:
    op.drop_index("ix_sales_payment_status", table_name="sales")
    op.drop_column("sales", "amount_paid")
    op.drop_index("ix_sale_payments_payment_date", table_name="sale_payments")
    op.drop_index("ix_sale_payments_sale_id", table_name="sale_payments")
    op.drop_index("ix_sale_payments_tenant_id", table_name="sale_payments")
    op.drop_table("sale_payments")
